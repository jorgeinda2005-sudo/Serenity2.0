import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "serenity.db"))
from flask import Flask, render_template, redirect, url_for, request, session
from flask_bcrypt import Bcrypt
import sqlite3
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib import colors
from flask import send_file
import tempfile

app = Flask(__name__)
bcrypt = Bcrypt(app)
app.secret_key = "$2b$12$L8e2YqgYLVHhMcp4xXpsKOpDQC6xNW11.hqM8V0TCRXFVcbsOb8SG"

import os

@app.route("/cambiar_password", methods=["GET", "POST"])
def cambiar_password():
    if "user" not in session:
        return redirect("/")

    if request.method == "POST":
        actual = request.form["actual"]
        nueva = request.form["nueva"]
        confirmar = request.form["confirmar"]

        if nueva != confirmar:
            return render_template(
                "cambiar_password.html",
                error="Las contraseñas no coinciden",
                user=session["user"]
            )

        conn = sqlite3.connect(DB)
        cur = conn.cursor()

        cur.execute(
            "SELECT password_hash FROM psicologos WHERE id=?",
            (session["id"],)
        )
        row = cur.fetchone()

        if not row or not bcrypt.check_password_hash(row[0], actual):
            conn.close()
            return render_template(
                "cambiar_password.html",
                error="Contraseña actual incorrecta",
                user=session["user"]
            )

        nuevo_hash = bcrypt.generate_password_hash(nueva).decode("utf-8")

        cur.execute(
            "UPDATE psicologos SET password_hash=? WHERE id=?",
            (nuevo_hash, session["id"])
        )

        conn.commit()
        conn.close()

        session.clear()
        return redirect("/")

    return render_template("cambiar_password.html", user=session["user"])

@app.route("/verdb")
def verdb():
    return os.path.abspath(DB)

def query(sql, params=()):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute(sql, params)
    data = cur.fetchall()
    conn.close()
    return data

@app.route("/")
def login():
    return render_template("login.html")

@app.route("/auth", methods=["POST"])
def auth():
    usuario = request.form["user"]
    password = request.form["pass"]

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, nombre, password_hash
        FROM admins
        WHERE usuario=? AND activo=1
    """, (usuario,))
    admin = cur.fetchone()

    if admin and bcrypt.check_password_hash(admin[2], password):
        conn.close()
        session.clear()
        session["admin"] = admin[1]
        session["admin_id"] = admin[0]
        return redirect("/admin/dashboard")

    cur.execute("""
        SELECT id, nombre, password_hash
        FROM psicologos
        WHERE usuario=? AND activo=1
    """, (usuario,))
    psicologo = cur.fetchone()
    conn.close()

    if not psicologo:
        return render_template("login.html", error="Usuario no encontrado o inactivo")

    if not bcrypt.check_password_hash(psicologo[2], password):
        return render_template("login.html", error="Contraseña incorrecta")

    facultades = query(
        "SELECT facultad FROM psicologos_facultades WHERE psicologo_id=?",
        (psicologo[0],)
    )
    facultades = [f[0] for f in facultades]

    if not facultades:
        return render_template(
            "login.html",
            error="Este psicólogo no tiene facultades asignadas."
        )

    session.clear()
    session["user"] = psicologo[1]
    session["id"] = psicologo[0]
    session["facultades"] = facultades

    return redirect("/dashboard")

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    facs = session["facultades"]
    placeholders = ",".join("?" * len(facs))

    usuarios = query(f"""
        SELECT COUNT(*)
        FROM usuarios u
        JOIN datos d ON d.user_id=u.id
        WHERE d.facultad IN ({placeholders})
    """, facs)[0][0]

    alertas = query(f"""
        SELECT COUNT(*)
        FROM alertas a
        JOIN datos d ON d.user_id=a.usuario_id
        WHERE d.facultad IN ({placeholders})
    """, facs)[0][0]

    perfiles = query(f"""
        SELECT COUNT(*)
        FROM perfil_emocional p
        JOIN datos d ON d.user_id=p.user_id
        WHERE d.facultad IN ({placeholders})
    """, facs)[0][0]

    return render_template("dashboard.html",
                           usuarios=usuarios,
                           alertas=alertas,
                           perfiles=perfiles,
                           user=session["user"])

@app.route("/alertas")
def ver_alertas():
    if "user" not in session:
        return redirect("/")

    facs = session["facultades"]
    placeholders = ",".join("?" * len(facs))

    tipo = request.args.get("tipo", "")
    buscar = request.args.get("buscar", "")
    fecha_inicio = request.args.get("inicio", "")
    fecha_fin = request.args.get("fin", "")

    sql = f"""
        SELECT a.id, u.user_name, a.tipo_alerta, a.descripcion, a.fecha
        FROM alertas a
        JOIN usuarios u ON a.usuario_id=u.id
        JOIN datos d ON d.user_id=u.id
        WHERE d.facultad IN ({placeholders})
    """
    params = facs.copy()

    if buscar:
        sql += " AND (u.user_name LIKE ? OR u.id LIKE ? OR a.descripcion LIKE ?)"
        params.extend([f"%{buscar}%", f"%{buscar}%", f"%{buscar}%"])

    if tipo:
        sql += " AND a.tipo_alerta LIKE ?"
        params.append(f"%{tipo}%")

    if fecha_inicio:
        sql += " AND date(a.fecha) >= date(?)"
        params.append(fecha_inicio)
    if fecha_fin:
        sql += " AND date(a.fecha) <= date(?)"
        params.append(fecha_fin)

    sql += " ORDER BY a.fecha DESC"

    datos = query(sql, params)

    return render_template("alertas.html",
                           datos=datos,
                           user=session["user"],
                           tipo=tipo,
                           buscar=buscar,
                           inicio=fecha_inicio,
                           fin=fecha_fin)

@app.route("/usuarios")
def ver_usuarios():
    if "user" not in session:
        return redirect("/")

    facs = session["facultades"]
    placeholders = ",".join("?" * len(facs))

    datos = query(f"""
    SELECT u.id, u.user_name,
        d.facultad,
        (SELECT COUNT(*) FROM conversaciones c WHERE c.user_id=u.id) AS mensajes,
        (SELECT MAX(timestamp) FROM conversaciones c WHERE c.user_id=u.id) AS ultima
        FROM usuarios u
        JOIN datos d ON d.user_id=u.id
        WHERE d.facultad IN ({placeholders})
        ORDER BY ultima DESC
    """, facs)

    return render_template("usuarios.html", datos=datos, user=session["user"])

@app.route("/usuario/<int:id>")
def perfil_usuario(id):
    if "user" not in session:
        return redirect("/")

    facs = session["facultades"]
    placeholders = ",".join("?" * len(facs))

    valid = query(
        f"SELECT 1 FROM datos WHERE user_id=? AND facultad IN ({placeholders}) LIMIT 1",
        (id, *facs)
    )

    if not valid:
        return "No tienes permiso para ver usuarios de otras facultades."

    datos_personales = query("""
        SELECT nombre, numero, correo_institucional, facultad, fecha
        FROM datos
        WHERE user_id=?
        ORDER BY id DESC LIMIT 1
    """, (id,))
    datos_personales = datos_personales[0] if datos_personales else None

    usuario = query("SELECT user_name FROM usuarios WHERE id=?", (id,))
    if not usuario:
        return "⚠ Usuario no encontrado"
    user_name = usuario[0][0]

    chats = query("""
        SELECT user_message, bot_message, timestamp
        FROM conversaciones WHERE user_id=? ORDER BY id
    """, (id,))

    alertas = query("""
        SELECT tipo_alerta, nivel, fecha, descripcion
        FROM alertas WHERE usuario_id=? ORDER BY fecha DESC
    """, (id,))

    perfil = query("""
        SELECT estado_emocional_predominante, patrones_expresion, intencion_divulgacion,
               rasgos_personalidad, necesidades_esperadas, recomendaciones, fecha
        FROM perfil_emocional WHERE user_id=?
        ORDER BY fecha DESC LIMIT 1
    """, (id,))

    dependencia = query("""
        SELECT nivel_dependencia, puntaje_total, ultima_evaluacion
        FROM dependencias WHERE user_id=?
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

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
@app.route("/admin/dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect("/")

    psicologos = query("""
        SELECT id, nombre, usuario, activo
        FROM psicologos
        ORDER BY nombre
    """)

    return render_template(
        "admin_dashboard.html",
        psicologos=psicologos,
        admin=session["admin"]
    )

@app.route("/admin/toggle_psicologo/<int:id>")
def toggle_psicologo(id):
    if "admin" not in session:
        return redirect("/")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        UPDATE psicologos
        SET activo = CASE WHEN activo=1 THEN 0 ELSE 1 END
        WHERE id=?
    """, (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/dashboard")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    session.pop("admin_id", None)
    return redirect("/")

@app.route("/reporte_pdf/<int:id>")
def reporte_pdf(id):
    if "user" not in session:
        return redirect("/")

    facs = session["facultades"]
    placeholders = ",".join("?" * len(facs))

    valid = query(
        f"SELECT 1 FROM datos WHERE user_id=? AND facultad IN ({placeholders}) LIMIT 1",
        (id, *facs)
    )
    if not valid:
        return "No puedes generar reportes de usuarios fuera de tu facultad."

    usuario = query("SELECT user_name FROM usuarios WHERE id=?", (id,))
    if not usuario:
        return "⚠ Usuario no encontrado"
    user_name = usuario[0][0]

    perfil = query("""
        SELECT estado_emocional_predominante, patrones_expresion, intencion_divulgacion,
               rasgos_personalidad, necesidades_esperadas, recomendaciones, fecha
        FROM perfil_emocional WHERE user_id=?
        ORDER BY fecha DESC LIMIT 1
    """, (id,))

    alertas = query("""
        SELECT tipo_alerta, nivel, fecha, descripcion
        FROM alertas WHERE usuario_id=?
        ORDER BY fecha DESC
    """, (id,))

    chats = query("""
        SELECT user_message, bot_message
        FROM conversaciones WHERE user_id=?
        ORDER BY id DESC LIMIT 15
    """, (id,))

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    c = canvas.Canvas(temp.name, pagesize=A4)

    margin_left = 2 * cm
    margin_top = 28 * cm
    width, height = A4
    y = margin_top

    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_left, y, "Reporte Psicológico - Serenity")
    y -= 14
    c.setStrokeColor(colors.black)
    c.line(margin_left, y, width - margin_left, y)
    y -= 20

    c.setFont("Helvetica", 11)
    c.drawString(margin_left, y, f"Usuario evaluado: {user_name}")
    y -= 25

    if perfil:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin_left, y, "Perfil Emocional")
        y -= 15

        labels = [
            ("Estado emocional predominante", perfil[0][0]),
            ("Patrones de expresión", perfil[0][1]),
            ("Apertura emocional", perfil[0][2]),
            ("Rasgos de personalidad", perfil[0][3]),
            ("Necesidades esperadas", perfil[0][4]),
            ("Recomendaciones", perfil[0][5]),
        ]

        c.setFont("Helvetica", 10)
        for title, value in labels:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin_left, y, f"{title}:")
            y -= 12
            c.setFont("Helvetica", 10)
            c.drawString(margin_left + 10, y, str(value))
            y -= 16

            if y < 2*cm:
                c.showPage()
                y = margin_top

    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin_left, y, "Alertas Detectadas")
    y -= 15

    c.setFont("Helvetica", 10)
    if alertas:
        for a in alertas:
            c.drawString(margin_left, y, f"- {a[0]} (Nivel: {a[1]})  {a[2]}")
            y -= 12
            c.drawString(margin_left + 10, y, f"Descripción: {a[3]}")
            y -= 20

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
        c.drawString(margin_left, y, f"Usuario: {u_msg}")
        y -= 11
        c.setFont("Helvetica", 9)
        c.drawString(margin_left + 10, y, f"Serenity: {b_msg}")
        y -= 14

        if y < 2 * cm:
            c.showPage()
            y = margin_top

    c.save()
    return send_file(temp.name, as_attachment=True, download_name=f"Reporte_{user_name}.pdf")

if __name__ == "__main__":
    app.run(debug=True, port=5001)
    