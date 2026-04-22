from flask import Flask, render_template, redirect, request, session, send_file
from flask_bcrypt import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
import psycopg2
import psycopg2.pool
import tempfile
import os
import re
import secrets
from datetime import timedelta, datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "$2b$12$L8e2YqgYLVHhMcp4xXpsKOpDQC6xNW11.hqM8V0TCRXFVcbsOb8SG")

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)
app.config["SESSION_COOKIE_HTTPONLY"]    = True
app.config["SESSION_COOKIE_SAMESITE"]   = "Lax"

DATABASE_URL = os.getenv("DATABASE_URL", "")

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

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2, maxconn=10, dsn=DATABASE_URL
        )
    return _pool

def query(sql, params=()):
    conn = get_pool().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
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
        SELECT a.id,
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
        sql += " AND (u.username ILIKE %s OR CAST(u.user_id AS TEXT) ILIKE %s OR a.razon ILIKE %s)"
        params.extend([f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"])
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
               (SELECT MAX(timestamp) FROM conversaciones c WHERE c.user_id = u.user_id) AS ultima
        FROM usuarios u
        WHERE u.facultad IN ({placeholders})
        ORDER BY ultima DESC NULLS LAST
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
        SELECT role, content, timestamp
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

    alertas = query("""
        SELECT tema, nivel_riesgo, timestamp, razon
        FROM alertas WHERE user_id=%s ORDER BY timestamp DESC
    """, (id,))

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

    perfil = query("""
        SELECT analisis, timestamp FROM perfil_emocional
        WHERE user_id=%s ORDER BY timestamp DESC LIMIT 1
    """, (id,))

    alertas = query("""
        SELECT tema, nivel_riesgo, timestamp, razon
        FROM alertas WHERE user_id=%s ORDER BY timestamp DESC
    """, (id,))

    mensajes = query("""
        SELECT role, content FROM conversaciones
        WHERE user_id=%s ORDER BY id DESC LIMIT 30
    """, (id,))

    chats = []
    temp_user = None
    for role, content in reversed(mensajes):
        if role == "user":
            temp_user = content
        elif role == "assistant" and temp_user:
            chats.append((temp_user, content))
            temp_user = None

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c    = canvas.Canvas(temp.name, pagesize=A4)

    margin_left = 2 * cm
    margin_top  = 28 * cm
    width, _    = A4
    y           = margin_top

    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_left, y, "Reporte Psicológico - Serenity")
    y -= 14
    c.line(margin_left, y, width - margin_left, y)
    y -= 20

    c.setFont("Helvetica", 11)
    c.drawString(margin_left, y, f"Usuario evaluado: {user_name}")
    y -= 25

    if perfil:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin_left, y, "Perfil Emocional")
        y -= 15
        c.setFont("Helvetica", 10)
        c.drawString(margin_left, y, str(perfil[0][0])[:120])
        y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_left, y, "Alertas Detectadas")
    y -= 15
    c.setFont("Helvetica", 10)
    if alertas:
        for a in alertas:
            c.drawString(margin_left, y, f"- {a[0]} (Nivel: {a[1]})  {a[2]}")
            y -= 12
            c.drawString(margin_left + 10, y, f"Razón: {a[3]}")
            y -= 18
            if y < 2 * cm:
                c.showPage()
                y = margin_top
    else:
        c.drawString(margin_left, y, "Sin alertas registradas.")
        y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_left, y, "Resumen Conversacional")
    y -= 15
    for u_msg, b_msg in chats:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin_left, y, f"Usuario: {u_msg[:100]}")
        y -= 11
        c.setFont("Helvetica", 9)
        c.drawString(margin_left + 10, y, f"Serenity: {b_msg[:100]}")
        y -= 14
        if y < 2 * cm:
            c.showPage()
            y = margin_top

    c.save()
    try:
        return send_file(temp.name, as_attachment=True, download_name=f"Reporte_{user_name}.pdf")
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
    codigo_ingresado = request.form.get("codigo", "").strip()
    nueva = request.form.get("nueva", "")
    confirmar = request.form.get("confirmar", "")

    # 1. Buscar al usuario y su código temporal
    row = query(
        "SELECT id, codigo_temporal FROM psicologos WHERE usuario=%s AND activo=TRUE",
        (usuario,)
    )
    if not row:
        return render_template("recuperar.html", error="Usuario no encontrado o inactivo.")
    
    user_id, codigo_real = row[0]

    # 2. Verificar que el código temporal coincida
    if not codigo_real or codigo_ingresado != codigo_real:
        return render_template("recuperar.html", error="El código temporal es incorrecto.")

    # 3. Validar que las contraseñas nuevas coincidan
    if nueva != confirmar:
        return render_template("recuperar.html", error="Las contraseñas no coinciden.")

    # 4. Validar seguridad de la nueva contraseña
    error_pwd = validar_password(nueva)
    if error_pwd:
        return render_template("recuperar.html", error=error_pwd)

    # 5. Guardar la nueva contraseña
    hashed = generate_password_hash(nueva).decode("utf-8")
    execute(
        "UPDATE psicologos SET password_hash=%s, primer_acceso=FALSE WHERE id=%s",
        (hashed, user_id)
    )

    # Mandar al login con mensaje de éxito (usamos 'error' para aprovechar la alerta visual que ya tienes en login.html)
    return render_template("login.html", error="✅ Contraseña actualizada. Ya puedes iniciar sesión.")


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