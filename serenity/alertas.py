import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from .config import (
    GMAIL_USER, GMAIL_PASS, TWILIO_WHATSAPP_FROM,
    TWILIO_WHATSAPP_TO, twilio_client, logger
)

def enviar_correo_alerta(destinatario, usuario_info, motivo_riesgo):
    """Genera un reporte Excel y lo envía por correo al orientador."""
    if not GMAIL_USER or not GMAIL_PASS:
        raise RuntimeError("No se han configurado las credenciales de Gmail.")

    archivo_excel = f"alerta_{usuario_info['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    # Crear un pequeño reporte con Pandas
    df = pd.DataFrame([usuario_info])
    df.to_excel(archivo_excel, index=False)

    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = destinatario
    msg['Subject'] = f"⚠️ ALERTA DE RIESGO - Proyecto Serenity - Usuario: {usuario_info['id']}"

    cuerpo = f"Se ha detectado un nivel de riesgo importante.\n\nMotivo: {motivo_riesgo}\n\nSe adjunta el expediente generado."
    msg.attach(MIMEText(cuerpo, 'plain'))

    # Adjuntar el archivo Excel
    try:
        with open(archivo_excel, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={archivo_excel}")
            msg.attach(part)

        # Enviar vía SMTP
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"Correo de alerta enviado a {destinatario}")
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")
        raise

def enviar_whatsapp_emergencia(mensaje):
    """Envía un mensaje rápido de WhatsApp vía Twilio."""
    if not twilio_client:
        logger.error("Twilio no está configurado.")
        return

    try:
        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            body=f"🚨 SERENITY ALERT: {mensaje}",
            to=TWILIO_WHATSAPP_TO
        )
        logger.info(f"WhatsApp enviado con éxito. SID: {message.sid}")
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")
