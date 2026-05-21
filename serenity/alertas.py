import smtplib
import pandas as pd
import psycopg2
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.chart import BarChart, PieChart, Reference
from .config import (
    GMAIL_USER, GMAIL_PASS, TWILIO_WHATSAPP_FROM,
    TWILIO_WHATSAPP_TO, twilio_client, logger
)


def generar_excel_clasificacion(usuario_info):
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL no configurada para generar clasificacion.")

    archivo = f"clasificacion_serenity_{usuario_info['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    conn = psycopg2.connect(database_url)
    try:
        df_tema = pd.read_sql_query(
            """
            SELECT tema, COUNT(*) AS total
            FROM alertas
            WHERE user_id = %s
            GROUP BY tema
            ORDER BY total DESC
            """,
            conn,
            params=(usuario_info["id"],),
        )
        df_nivel = pd.read_sql_query(
            """
            SELECT nivel_riesgo, COUNT(*) AS total
            FROM alertas
            WHERE user_id = %s
            GROUP BY nivel_riesgo
            ORDER BY total DESC
            """,
            conn,
            params=(usuario_info["id"],),
        )

        if df_tema.empty:
            df_tema = pd.DataFrame([{"tema": "sin_datos", "total": 0}])
        if df_nivel.empty:
            df_nivel = pd.DataFrame([{"nivel_riesgo": "sin_datos", "total": 0}])

        with pd.ExcelWriter(archivo, engine="openpyxl") as writer:
            df_tema.to_excel(writer, sheet_name="clasif_tema", index=False)
            df_nivel.to_excel(writer, sheet_name="clasif_nivel", index=False)

        wb = load_workbook(archivo)
        ws_tema = wb["clasif_tema"]
        ws_nivel = wb["clasif_nivel"]

        bar = BarChart()
        bar.title = "Interacciones por tema"
        bar.y_axis.title = "Total"
        bar.x_axis.title = "Tema"
        data = Reference(ws_tema, min_col=2, min_row=1, max_row=ws_tema.max_row)
        cats = Reference(ws_tema, min_col=1, min_row=2, max_row=ws_tema.max_row)
        bar.add_data(data, titles_from_data=True)
        bar.set_categories(cats)
        ws_tema.add_chart(bar, "E2")

        pie = PieChart()
        pie.title = "Distribucion por nivel de riesgo"
        data2 = Reference(ws_nivel, min_col=2, min_row=1, max_row=ws_nivel.max_row)
        cats2 = Reference(ws_nivel, min_col=1, min_row=2, max_row=ws_nivel.max_row)
        pie.add_data(data2, titles_from_data=True)
        pie.set_categories(cats2)
        ws_nivel.add_chart(pie, "E2")

        wb.save(archivo)
    finally:
        conn.close()

    return archivo


def enviar_correo_alerta(destinatario, usuario_info, motivo_riesgo):
    """Genera 2 reportes Excel y los envia por correo al orientador."""
    if not GMAIL_USER or not GMAIL_PASS:
        raise RuntimeError("No se han configurado las credenciales de Gmail.")

    archivo_excel = f"alerta_{usuario_info['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    archivo_clasificacion = generar_excel_clasificacion(usuario_info)

    df = pd.DataFrame([usuario_info])
    df.to_excel(archivo_excel, index=False)

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = destinatario
    msg['Subject'] = f"ALERTA DE RIESGO - Proyecto Serenity - Usuario: {usuario_info['id']}"

    cuerpo = f"Se ha detectado un nivel de riesgo importante.\n\nMotivo: {motivo_riesgo}\n\nSe adjuntan los reportes generados."
    msg.attach(MIMEText(cuerpo, 'plain'))

    try:
        with open(archivo_excel, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={archivo_excel}")
            msg.attach(part)

        with open(archivo_clasificacion, "rb") as attachment2:
            part2 = MIMEBase("application", "octet-stream")
            part2.set_payload(attachment2.read())
            encoders.encode_base64(part2)
            part2.add_header("Content-Disposition", f"attachment; filename={archivo_clasificacion}")
            msg.attach(part2)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"Correo de alerta enviado a {destinatario}")
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")
        raise
    finally:
        for f in (archivo_excel, archivo_clasificacion):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass


def enviar_whatsapp_emergencia(mensaje):
    """Envia un mensaje rapido de WhatsApp via Twilio."""
    if not twilio_client:
        logger.error("Twilio no esta configurado.")
        return

    try:
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=f"SERENITY ALERT: {mensaje}",
            to=TWILIO_WHATSAPP_TO
        )
        logger.info(f"WhatsApp enviado con exito. SID: {message.sid}")
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")
