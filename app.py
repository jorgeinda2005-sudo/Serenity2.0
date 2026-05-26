from flask import Flask, render_template, redirect, request, session, send_file
from flask_bcrypt import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import psycopg2
import psycopg2.pool
import tempfile
import os
import re
import json
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import timedelta, datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# FIX: La secret_key nunca debe estar hardcodeada. Genera una con:
#   python -c "import secrets; print(secrets.token_hex(32))"
# y ponla en tu .env como SECRET_KEY=...
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY no configurada en el .env")

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)
app.config["SESSION_COOKIE_HTTPONLY"]    = True
app.config["SESSION_COOKIE_SAMESITE"]   = "Lax"

DATABASE_URL = os.getenv("DATABASE_URL", "")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL no configurada en el .env")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=DATABASE_URL
        )
    return _pool

def validar_password(password):
    if len(password) < 8:
        return "❌ Mínimo 8 caracteres"
    if not re.search(r'[A-Z]', password):
        return "❌ Debe tener al menos una letra mayúscula"
    if not re.search(r'[0-9]', password):
        return "❌ Debe tener al menos un número"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', password):
        return "❌ Debe tener al menos un símbolo (!@#$%...)"
    return None

def login_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def query(sql, params=()):
    conn = get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        # FIX: cerrar la conexión rota para evitar "envenenamiento" del pool.
        # putconn() detectará que está cerrada y la descartará correctamente.
        try:
            conn.close()
        except Exception:
            pass
        print(f"Error en query: {e}")
        return []
    finally:
        get_pool().putconn(conn)

def execute(sql, params=()):
    conn = get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        # FIX: cerrar la conexión rota
        try:
            conn.close()
        except Exception:
            pass
        print(f"Error en execute: {e}")
    finally:
        get_pool().putconn(conn)

def contar_mensajes_usuario(user_id):
    res = query("SELECT COUNT(*) FROM conversaciones WHERE user_id=%s AND role='user'", (user_id,))
    return res[0][0] if res else 0

def registrar_dependencia(user_id, nivel, reporte):
    execute("""
        INSERT INTO dependencias (user_id, nivel, reporte, timestamp) 
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
    """, (user_id, nivel, reporte))

def registrar_perfil_emocional(user_id, analisis):
    execute("""
        INSERT INTO perfil_emocional (user_id, analisis, timestamp) 
        VALUES (%s, %s, CURRENT_TIMESTAMP)
    """, (user_id, analisis))


def backfill_contexto_alerta(alerta_id, user_id, alerta_ts):
    msgs = query(
        """
        SELECT id, content, timestamp, TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS ts
        FROM conversaciones
        WHERE user_id=%s
          AND role='user'
          AND timestamp <= %s
        ORDER BY timestamp DESC
        LIMIT 6
        """,
        (user_id, alerta_ts),
    )
    if not msgs:
        return

    detonante = msgs[0][1]

    previos = []
    for r in msgs[1:]:
        ans = query(
            """
            SELECT content
            FROM conversaciones
            WHERE user_id=%s
              AND role='assistant'
              AND timestamp >= %s
              AND timestamp <= %s
            ORDER BY timestamp ASC, id ASC
            LIMIT 1
            """,
            (user_id, r[2], alerta_ts),
        )
        if not ans:
            ans = query(
                """
                SELECT content
                FROM conversaciones
                WHERE user_id=%s
                  AND role='assistant'
                  AND id > %s
                ORDER BY id ASC
                LIMIT 1
                """,
                (user_id, r[0]),
            )
        previos.append({
            "mensaje": r[1],
            "fecha": r[3],
            "respuesta_serenity": ans[0][0] if ans else "",
        })
    execute(
        """
        INSERT INTO alertas_contexto (alerta_id, user_id, mensaje_detonante, mensajes_previos_json, timestamp)
        VALUES (%s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        ON CONFLICT (alerta_id) DO UPDATE
        SET mensaje_detonante=EXCLUDED.mensaje_detonante,
            mensajes_previos_json=EXCLUDED.mensajes_previos_json
        """,
        (alerta_id, user_id, detonante, json.dumps(previos, ensure_ascii=False)),
    )


def enviar_codigo_recuperacion(destinatario, codigo_temporal):
    if not GMAIL_USER or not GMAIL_PASS:
        raise RuntimeError("GMAIL_USER/GMAIL_PASS no configurados")

    msg = MIMEText(
        "Hola.\n\n"
        "Recibimos una solicitud de recuperacion de contrasena para Serenity.\n"
        f"Tu codigo temporal es: {codigo_temporal}\n\n"
        "Si no solicitaste este cambio, ignora este mensaje."
    )
    msg["Subject"] = "Serenity - Codigo de recuperacion"
    msg["From"] = GMAIL_USER
    msg["To"] = destinatario

    server = smtplib.SMTP("smtp.gmail.com", 587)
    try:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)
    finally:
        server.quit()


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def login():
    return render_template("login.html")


@app.route("/auth", methods=["POST"])
def auth():
    usuario  = request.form["user"]
    password = request.form["pass"]

    row = query(
        "SELECT id, nombre, password_hash, primer_acceso, codigo_temporal, rol "
        "FROM psicologos WHERE usuario=%s AND activo=TRUE",
        (usuario,)
    )
    if not row:
        return render_template("login.html", error="❌ Usuario no encontrado o inactivo")

    user_id, nombre, password_hash, primer_acceso, codigo_temporal, rol = row[0]

    if primer_acceso:
        if password != codigo_temporal:
            return render_template("login.html", error="❌ Código temporal incorrecto")
        session["user"]          = nombre
        session["id"]            = user_id
        session["rol"]           = rol
        session["primer_acceso"] = True
        return redirect("/cambiar_password")

    if not password_hash or not check_password_hash(password_hash, password):
        return render_template("login.html", error="❌ Contraseña incorrecta")

    facultades = query(
        "SELECT facultad FROM psicologos_facultades WHERE psicologo_id=%s",
        (user_id,)
    )
    session.permanent     = True
    session["user"]       = nombre
    session["id"]         = user_id
    session["rol"]        = rol
    session["facultades"] = [f[0] for f in facultades]

    if rol == "admin":
        return redirect("/admin")
    return redirect("/dashboard")


@app.route("/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
    if "user" not in session:
        return redirect("/")

    if request.method == "POST":
        actual    = request.form.get("actual", "")
        nueva     = request.form["nueva"]
        confirmar = request.form["confirmar"]

        if not session.get("primer_acceso"):
            row = query("SELECT password_hash FROM psicologos WHERE id=%s", (session["id"],))
            if not row or not row[0] or not row[0][0] or not check_password_hash(row[0][0], actual):
                return render_template("cambiar_password.html",
                                       error="❌ La contraseña actual es incorrecta",
                                       user=session["user"])

        if nueva != confirmar:
            return render_template("cambiar_password.html",
                                   error="❌ Las contraseñas no coinciden",
                                   user=session["user"])

        error_pwd = validar_password(nueva)
        if error_pwd:
            return render_template("cambiar_password.html",
                                   error=error_pwd,
                                   user=session["user"])

        hashed = generate_password_hash(nueva).decode("utf-8")

        if session.get("primer_acceso"):
            correo_propio = request.form.get("correo", "").strip().lower()
            execute(
                "UPDATE psicologos SET password_hash=%s, primer_acceso=FALSE, correo=%s WHERE id=%s",
                (hashed, correo_propio, session["id"])
            )
        else:
            execute(
                "UPDATE psicologos SET password_hash=%s, primer_acceso=FALSE WHERE id=%s",
                (hashed, session["id"])
            )
        session.pop("primer_acceso", None)

        facultades = query(
            "SELECT facultad FROM psicologos_facultades WHERE psicologo_id=%s",
            (session["id"],)
        )
        session["facultades"] = [f[0] for f in facultades]

        if session.get("rol") == "admin":
            return redirect("/admin")
        return redirect("/dashboard")

    return render_template("cambiar_password.html", user=session["user"])


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    # Si es admin, redirigir a su panel
    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    usuarios = query(f"""
        SELECT COUNT(DISTINCT u.user_id)
        FROM usuarios u
        WHERE u.facultad IN ({placeholders})
        AND u.registrado = TRUE
    """, facs)[0][0] if facs else 0

    alertas = query(f"""
        SELECT COUNT(*)
        FROM alertas a
        JOIN usuarios u ON u.user_id = a.user_id
        WHERE u.facultad IN ({placeholders})
    """, facs)[0][0] if facs else 0

    perfiles = query(f"""
        SELECT COUNT(*)
        FROM perfil_emocional p
        JOIN usuarios u ON u.user_id = p.user_id
        WHERE u.facultad IN ({placeholders})
    """, facs)[0][0] if facs else 0

    return render_template("dashboard.html",
                           usuarios=usuarios,
                           alertas=alertas,
                           perfiles=perfiles,
                           user=session["user"])


# ══════════════════════════════════════════════════════════════════════════════
# ALERTAS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/alertas")
def ver_alertas():
    if "user" not in session:
        return redirect("/")

    # Si es admin, redirigir a su panel
    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    tipo         = request.args.get("tipo", "")
    buscar       = request.args.get("buscar", "")
    fecha_inicio = request.args.get("inicio", "")
    fecha_fin    = request.args.get("fin", "")

    sql = f"""
        SELECT ROW_NUMBER() OVER (ORDER BY a.timestamp DESC) AS folio,
               a.user_id,
               COALESCE(NULLIF(u.nombre_completo,''), u.username, CAST(u.user_id AS TEXT)) AS alumno,
               a.tema, a.razon, a.nivel_riesgo,
               TO_CHAR(a.timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS fecha
        FROM alertas a
        JOIN usuarios u ON u.user_id = a.user_id
        WHERE u.facultad IN ({placeholders})
    """
    params = list(facs)

    if buscar:
        sql += """ AND (
            u.username       ILIKE %s
            OR u.nombre_completo ILIKE %s
            OR CAST(u.user_id AS TEXT) ILIKE %s
            OR a.razon       ILIKE %s
        )"""
        params.extend([f"%{buscar}%", f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"])
    if tipo:
        sql += " AND a.tema ILIKE %s"
        params.append(f"%{tipo}%")
    if fecha_inicio:
        sql += " AND a.timestamp::date >= %s::date"
        params.append(fecha_inicio)
    if fecha_fin:
        sql += " AND a.timestamp::date <= %s::date"
        params.append(fecha_fin)

    sql += " ORDER BY a.timestamp DESC"
    datos = query(sql, params)

    return render_template("alertas.html",
                           datos=datos,
                           user=session["user"],
                           tipo=tipo,
                           buscar=buscar,
                           inicio=fecha_inicio,
                           fin=fecha_fin)


# ══════════════════════════════════════════════════════════════════════════════
# PERFILES EMOCIONALES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/perfiles")
def ver_perfiles():
    if "user" not in session:
        return redirect("/")

    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    sql = f"""
        SELECT * FROM (
            SELECT DISTINCT ON (p.user_id)
                   p.user_id,
                   COALESCE(NULLIF(u.nombre_completo,''), u.username, CAST(u.user_id AS TEXT)) AS alumno,
                   u.facultad,
                   p.analisis,
                   TO_CHAR(p.timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS fecha,
                   p.timestamp
            FROM perfil_emocional p
            JOIN usuarios u ON u.user_id = p.user_id
            WHERE u.facultad IN ({placeholders})
            ORDER BY p.user_id, p.timestamp DESC
        ) sub
        ORDER BY timestamp DESC
    """
    datos = query(sql, list(facs))

    return render_template("perfiles.html", datos=datos, user=session["user"])


# ══════════════════════════════════════════════════════════════════════════════
# USUARIOS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/usuarios")
def ver_usuarios():
    if "user" not in session:
        return redirect("/")

    # Si es admin, redirigir a su panel
    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    datos = query(f"""
        SELECT u.user_id, u.username, u.nombre_completo, u.facultad,
               (SELECT COUNT(*) FROM conversaciones c WHERE c.user_id = u.user_id) AS mensajes,
               (SELECT TO_CHAR(MAX(timestamp) AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') 
                FROM conversaciones c WHERE c.user_id = u.user_id) AS ultima
        FROM usuarios u
        WHERE u.facultad IN ({placeholders})
        ORDER BY (SELECT MAX(timestamp) FROM conversaciones c WHERE c.user_id = u.user_id) DESC NULLS LAST
    """, facs)

    return render_template("usuarios.html", datos=datos, user=session["user"])


# ══════════════════════════════════════════════════════════════════════════════
# PERFIL DE ALUMNO
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/usuario/<int:id>")
def perfil_usuario(id):
    if "user" not in session:
        return redirect("/")

    # Si es admin, redirigir a su panel
    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    valid = query(
        f"SELECT 1 FROM usuarios WHERE user_id=%s AND facultad IN ({placeholders}) LIMIT 1",
        (id, *facs)
    )
    if not valid:
        return "🚫 No tienes permiso para ver usuarios de otras facultades."

    datos_personales = query("""
        SELECT nombre_completo, matricula, correo, telefono, facultad
        FROM usuarios WHERE user_id=%s
    """, (id,))
    datos_personales = datos_personales[0] if datos_personales else None

    # Busca el nombre completo, si no hay, busca el username, si no, usa el ID
    usuario = query("SELECT COALESCE(NULLIF(nombre_completo,''), username, CAST(user_id AS TEXT)) FROM usuarios WHERE user_id=%s", (id,))
    if not usuario or not usuario[0] or not usuario[0][0]:
        return "⚠ Usuario no encontrado"
    user_name = usuario[0][0]

    mensajes = query("""
        SELECT role, content, TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI')
        FROM conversaciones WHERE user_id=%s ORDER BY id
    """, (id,))

    chats = []
    temp_user = None
    for role, content, ts in mensajes:
        if role == "user":
            temp_user = (content, ts)
        elif role == "assistant" and temp_user:
            chats.append((temp_user[0], content, temp_user[1]))
            temp_user = None

    alertas_raw = query("""
        SELECT a.id, a.tema, a.nivel_riesgo,
               TO_CHAR(a.timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS fecha,
               a.timestamp,
               a.razon,
               ac.mensaje_detonante,
               ac.mensajes_previos_json
        FROM alertas a
        LEFT JOIN alertas_contexto ac ON ac.alerta_id = a.id
        WHERE a.user_id=%s
        ORDER BY a.timestamp DESC
    """, (id,))

    alertas = []
    for row in alertas_raw:
        alerta_id = row[0]
        fecha = row[3]
        alerta_ts = row[4]
        razon = row[5]
        detonante = row[6]
        previos = row[7] if row[7] else []

        if isinstance(previos, str):
            try:
                previos = json.loads(previos)
            except Exception:
                previos = []

        necesita_backfill = (not detonante or detonante.strip() == "") or not previos
        if not necesita_backfill and isinstance(previos, list):
            for m in previos:
                if isinstance(m, dict) and ("respuesta_serenity" not in m or not str(m.get("respuesta_serenity", "")).strip()):
                    necesita_backfill = True
                    break

        if necesita_backfill:
            backfill_contexto_alerta(alerta_id, id, alerta_ts)
            ctx = query(
                """
                SELECT mensaje_detonante, mensajes_previos_json
                FROM alertas_contexto
                WHERE alerta_id=%s
                LIMIT 1
                """,
                (alerta_id,),
            )
            if ctx:
                detonante = ctx[0][0] or detonante
                previos = ctx[0][1] or previos
                if isinstance(previos, str):
                    try:
                        previos = json.loads(previos)
                    except Exception:
                        previos = []

        alertas.append({
            "id": alerta_id,
            "tema": row[1],
            "nivel": row[2],
            "fecha": fecha,
            "razon": razon,
            "detonante": detonante or "No hay mensaje detonante",
            "previos": previos,
        })

    perfil = query("""
        SELECT analisis, timestamp FROM perfil_emocional
        WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1
    """, (id,))

    dependencia = query("""
        SELECT nivel, TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI'), reporte
        FROM dependencias WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1
    """, (id,))

    return render_template(
        "perfil_usuario.html",
        nombre=user_name,
        user_id=id,
        datos_personales=datos_personales,
        chats=chats,
        alertas=alertas,
        perfil=perfil[0] if perfil else None,
        dependencia=dependencia[0] if dependencia else None,
        user=session["user"]
    )


# ══════════════════════════════════════════════════════════════════════════════
# REPORTE PDF
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/reporte_pdf/<int:id>")
def reporte_pdf(id):
    if "user" not in session:
        return redirect("/")

    # Si es admin, redirigir a su panel
    if session.get("rol") == "admin":
        return redirect("/admin")

    facs         = session.get("facultades", [])
    placeholders = ",".join(["%s"] * len(facs)) if facs else "'__vacío__'"

    valid = query(
        f"SELECT 1 FROM usuarios WHERE user_id=%s AND facultad IN ({placeholders}) LIMIT 1",
        (id, *facs)
    )
    if not valid:
        return "🚫 No puedes generar reportes de usuarios fuera de tu facultad."

    # Busca el nombre completo, si no hay, busca el username, si no, usa el ID
    usuario = query("SELECT COALESCE(NULLIF(nombre_completo,''), username, CAST(user_id AS TEXT)) FROM usuarios WHERE user_id=%s", (id,))
    if not usuario or not usuario[0] or not usuario[0][0]:
        return "⚠ Usuario no encontrado"
    user_name = usuario[0][0]

    datos_personales = query(
        """
        SELECT nombre_completo, matricula, correo, telefono, facultad
        FROM usuarios WHERE user_id=%s
        """,
        (id,),
    )
    datos_personales = datos_personales[0] if datos_personales else None

    perfil = query("""
        SELECT analisis, TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI')
        FROM perfil_emocional
        WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1
    """, (id,))

    alertas = query("""
        SELECT id, tema, nivel_riesgo,
               TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS fecha,
               razon, timestamp
        FROM alertas WHERE user_id=%s ORDER BY timestamp DESC
    """, (id,))

    mensajes = query("""
        SELECT role, content,
               TO_CHAR(timestamp AT TIME ZONE 'America/Mexico_City', 'DD/MM/YYYY HH24:MI') AS ts,
               timestamp
        FROM conversaciones
        WHERE user_id=%s
        ORDER BY id ASC
    """, (id,))

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    doc = SimpleDocTemplate(
        temp.name,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )

    styles = getSampleStyleSheet()
    palette_primary = colors.HexColor("#1F4E78")
    palette_secondary = colors.HexColor("#2E6AA0")
    palette_soft = colors.HexColor("#F1F6FB")
    palette_border = colors.HexColor("#AFC4DA")
    title_style = ParagraphStyle(
        "TitleSerenity",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        textColor=colors.white,
        alignment=0,
        leading=15,
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "SectionSerenity",
        parent=styles["Heading4"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        textColor=colors.white,
        leading=13,
        spaceBefore=3,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "BodySerenity",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12.5,
        textColor=colors.HexColor("#1C2733"),
    )
    small_style = ParagraphStyle(
        "SmallSerenity",
        parent=body_style,
        fontSize=8.4,
        leading=11.6,
    )

    story = []
    section_num = 0

    def section_title(text):
        nonlocal section_num
        section_num += 1
        t = Table([[Paragraph(f"{section_num}. {text}", section_style)]], colWidths=[17.6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), palette_secondary),
            ("BOX", (0, 0), (-1, -1), 1, palette_secondary),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(Spacer(1, 5))
        story.append(t)
        story.append(Spacer(1, 4))

    def bordered_paragraph(text, style=body_style, bg=colors.white):
        box = Table([[Paragraph(text, style)]], colWidths=[17.6 * cm])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 1, palette_border),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(box)
        story.append(Spacer(1, 3))

    # Header visual
    head = Table([[Paragraph("Reporte Psicologico Evolutivo por Sesiones - Serenity", title_style)]], colWidths=[17.6 * cm])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), palette_primary),
        ("BOX", (0, 0), (-1, -1), 1.2, palette_primary),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(head)
    story.append(Spacer(1, 8))

    # 1 Datos del alumno
    section_title("Datos del alumno")
    dp = datos_personales or ("-", "-", "-", "-", "-")
    data_tbl = Table(
        [
            ["Nombre", dp[0] or "-"],
            ["Matricula", dp[1] or "-"],
            ["Correo", dp[2] or "-"],
            ["Telefono", dp[3] or "-"],
            ["Facultad", dp[4] or "-"],
        ],
        colWidths=[4.0 * cm, 13.6 * cm],
    )
    data_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), palette_soft),
        ("BOX", (0, 0), (-1, -1), 1.2, palette_border),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#D5E0EC")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(data_tbl)

    # 2 Linea de tiempo
    section_title("Linea de tiempo de interacciones clave")
    claves = [m for m in mensajes if m[0] == "user"][-12:]
    if claves:
        for _, content, ts, _ in claves:
            bordered_paragraph(f"<b>[{ts}]</b> {content or '(sin contenido)'}", small_style, bg=colors.HexColor("#FAFCFF"))
    else:
        bordered_paragraph("Sin interacciones registradas.", body_style, bg=colors.HexColor("#FAFCFF"))

    # 3 Evolucion emocional
    section_title("Evolucion emocional (inicio -> actual)")
    if mensajes:
        primer_user = next((m[1] for m in mensajes if m[0] == "user"), "")
        ultimo_user = next((m[1] for m in reversed(mensajes) if m[0] == "user"), "")
        bordered_paragraph(f"<b>Inicio:</b> {primer_user or '(sin contenido)'}", body_style, bg=palette_soft)
        bordered_paragraph(f"<b>Actual:</b> {ultimo_user or '(sin contenido)'}", body_style, bg=palette_soft)
    else:
        bordered_paragraph("No hay suficientes datos para evaluar evolucion.", body_style, bg=palette_soft)
    if perfil:
        bordered_paragraph(f"<b>Perfil emocional mas reciente ({perfil[0][1]}):</b> {perfil[0][0]}", body_style, bg=palette_soft)

    # 4 Alertas criticas
    section_title("Alertas criticas con detonantes")
    if alertas:
        for _, tema, nivel, fecha, razon, _ in alertas[:8]:
            box = Table([[Paragraph(f"<b>{fecha}</b> | Tema: {tema} | Nivel: {nivel}<br/>{razon}", body_style)]], colWidths=[17.6 * cm])
            box.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 1.1, palette_border),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAFCFF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(box)
            story.append(Spacer(1, 4))
    else:
        bordered_paragraph("Sin alertas registradas.", body_style, bg=colors.HexColor("#FAFCFF"))

    # 5 Cambios de lenguaje
    section_title("Cambios de lenguaje (desesperanza, culpa, etc.)")
    texto_total = " ".join([(m[1] or "").lower() for m in mensajes if m[0] == "user"])
    marcadores = {
        "desesperanza": ["no puedo", "no valgo", "sin salida", "ya no", "inutil"],
        "culpa": ["culpa", "mi culpa", "perdon", "falle"],
        "aislamiento": ["solo", "nadie", "aislado", "sin apoyo"],
    }
    hallazgos = [f"{k}: {sum(1 for w in v if w in texto_total)} indicador(es)" for k, v in marcadores.items()]
    bordered_paragraph(" | ".join(hallazgos), body_style, bg=palette_soft)

    # 6 Respuestas de Serenity
    section_title("Respuestas de Serenity y efecto esperado")
    pares = []
    temp_user = None
    for role, content, ts, _ in mensajes:
        if role == "user":
            temp_user = (content, ts)
        elif role == "assistant" and temp_user:
            pares.append((temp_user[0], content, temp_user[1]))
            temp_user = None
    if pares:
        for u, b, ts in pares[-6:]:
            bordered_paragraph(
                f"<b>[{ts}] Usuario:</b> {u or '(sin contenido)'}<br/><b>Serenity:</b> {b or '(sin contenido)'}"
                "<br/><i>Efecto esperado:</i> contencion emocional y orientacion gradual.",
                small_style,
                bg=colors.HexColor("#FAFCFF"),
            )
    else:
        bordered_paragraph("No hay pares usuario-serenity suficientes.", body_style, bg=colors.HexColor("#FAFCFF"))

    # 7 Conclusion
    section_title("Conclusion clinica breve")
    bordered_paragraph(
        "Se observa malestar emocional con variacion en la intensidad. "
        "El seguimiento debe centrarse en identificar detonantes recurrentes y fortalecer recursos de afrontamiento.",
        body_style,
        bg=palette_soft,
    )

    # 8 Objetivos terapeuticos
    section_title("Objetivos terapeuticos cortos (3-5)")
    objetivos = [
        "1) Identificar 3 detonantes personales y su contexto.",
        "2) Practicar una tecnica breve de regulacion emocional diaria.",
        "3) Reestructurar 2 pensamientos automaticos negativos por semana.",
        "4) Activar una red minima de apoyo (1 persona de confianza).",
        "5) Mantener seguimiento psicologico semanal.",
    ]
    for o in objetivos:
        bordered_paragraph(o, body_style, bg=colors.HexColor("#FAFCFF"))

    # 9 Semaforo
    section_title("Semaforo de riesgo (alto/medio/bajo) con justificacion")
    nivel_top = alertas[0][2] if alertas else "bajo"
    color_txt = "ROJO" if nivel_top == "alto" else ("AMARILLO" if nivel_top == "medio" else "VERDE")
    just = alertas[0][4] if alertas else "Sin alertas recientes; mantener monitoreo preventivo."
    sem_box = Table(
        [[Paragraph(f"<b>Semaforo actual:</b> {color_txt} ({nivel_top.upper()})<br/><b>Justificacion:</b> {just}", body_style)]],
        colWidths=[17.6 * cm]
    )
    sem_color = colors.HexColor("#FDECEC") if nivel_top == "alto" else (colors.HexColor("#FFF9E6") if nivel_top == "medio" else colors.HexColor("#ECF9F0"))
    sem_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), sem_color),
        ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#C9D3DD")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(sem_box)

    doc.build(story)
    try:
        ts_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        return send_file(temp.name, as_attachment=True, download_name=f"Reporte_{user_name}_{ts_name}.pdf")
    finally:
        try:
            os.unlink(temp.name)
        except:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin")
def admin():
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")

    psicologos = query("""
        SELECT id, nombre, usuario, activo, primer_acceso, rol
        FROM psicologos ORDER BY nombre
    """)

    resultado = []
    for p in psicologos:
        facs = query(
            "SELECT id, facultad FROM psicologos_facultades WHERE psicologo_id=%s",
            (p[0],)
        )
        resultado.append({
            "id": p[0], "nombre": p[1], "usuario": p[2],
            "activo": p[3], "primer_acceso": p[4], "rol": p[5],
            "facultades": facs
        })

    return render_template("admin_dashboard.html",
                           psicologos=resultado,
                           user=session["user"])


@app.route("/admin/reset_base_datos", methods=["POST"])
def reset_base_datos():
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")

    execute("""
        TRUNCATE TABLE
            alertas_contexto,
            alertas,
            perfil_emocional,
            dependencias,
            conversaciones,
            correos_enviados,
            usuarios
        RESTART IDENTITY CASCADE
    """)
    return redirect("/admin")


@app.route("/admin/agregar_facultad", methods=["POST"])
def agregar_facultad():
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")
    psicologo_id = request.form["psicologo_id"]
    facultad     = request.form["facultad"].strip()
    if facultad:
        execute(
            "INSERT INTO psicologos_facultades (psicologo_id, facultad) VALUES (%s, %s)",
            (psicologo_id, facultad)
        )
    return redirect("/admin")


@app.route("/admin/quitar_facultad/<int:id>")
def quitar_facultad(id):
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")
    execute("DELETE FROM psicologos_facultades WHERE id=%s", (id,))
    return redirect("/admin")


@app.route("/admin/toggle_activo/<int:id>")
def toggle_activo(id):
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")
    execute("UPDATE psicologos SET activo = NOT activo WHERE id=%s", (id,))
    return redirect("/admin")


@app.route("/admin/agregar_psicologo", methods=["POST"])
def agregar_psicologo():
    if "user" not in session or session.get("rol") != "admin":
        return redirect("/")
    nombre  = request.form["nombre"].strip()
    usuario = request.form["usuario"].strip()
    codigo  = request.form["codigo"].strip()
    try:
        execute(
            "INSERT INTO psicologos (nombre, usuario, activo, rol, primer_acceso, codigo_temporal) "
            "VALUES (%s, %s, TRUE, 'psicologo', TRUE, %s)",
            (nombre, usuario, codigo)
        )
    except psycopg2.IntegrityError:
        return render_template("admin_dashboard.html",
                               error="❌ El usuario ya existe",
                               user=session["user"])
    return redirect("/admin")


# ══════════════════════════════════════════════════════════════════════════════
# RECUPERACIÓN DE CONTRASEÑA (MÉTODO POR CÓDIGO TEMPORAL)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "GET":
        return render_template("recuperar.html")

    usuario = request.form.get("usuario", "").strip()
    accion = request.form.get("accion", "reset")

    if not usuario:
        return render_template("recuperar.html", error="Debes ingresar tu usuario.")

    row = query(
        "SELECT id, codigo_temporal, correo FROM psicologos WHERE usuario=%s AND activo=TRUE",
        (usuario,)
    )
    if not row:
        return render_template("recuperar.html", error="Usuario no encontrado o inactivo.")

    user_id, codigo_real, correo_destino = row[0]

    if accion == "enviar_codigo":
        if not correo_destino:
            return render_template(
                "recuperar.html",
                error="Este usuario no tiene correo registrado. Contacta al administrador."
            )
        try:
            enviar_codigo_recuperacion(correo_destino, codigo_real)
            return render_template(
                "recuperar.html",
                error="Codigo enviado al correo registrado del psicologo."
            )
        except Exception as e:
            return render_template("recuperar.html", error=f"No se pudo enviar el correo: {e}")

    codigo_ingresado = request.form.get("codigo", "").strip()
    nueva = request.form.get("nueva", "")
    confirmar = request.form.get("confirmar", "")

    if not codigo_real or codigo_ingresado != codigo_real:
        return render_template("recuperar.html", error="El codigo temporal es incorrecto.")

    if nueva != confirmar:
        return render_template("recuperar.html", error="Las contrasenas no coinciden.")

    error_pwd = validar_password(nueva)
    if error_pwd:
        return render_template("recuperar.html", error=error_pwd)

    hashed = generate_password_hash(nueva).decode("utf-8")
    execute(
        "UPDATE psicologos SET password_hash=%s, primer_acceso=FALSE WHERE id=%s",
        (hashed, user_id)
    )

    return render_template("login.html", error="Contrasena actualizada. Ya puedes iniciar sesion.")



# ══════════════════════════════════════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    PORT = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=PORT, debug=False)
