import os
import re
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

from config import TOKEN_TELEGRAM, TMP_DIR, PDF_DIRECTORIO, logger
from database import (
    crear_base_datos, guardar_usuario, completar_registro,
    usuario_registrado, obtener_datos_usuario
)
from ai_core import obtener_respuesta_ia, groq_client
from alertas import enviar_correo_alerta, enviar_whatsapp_emergencia

# ── Estados del flujo de registro por alerta ──────────────────────────────────
NOMBRE, MATRICULA, CORREO, TELEFONO = range(4)

PALABRAS_INAPROPIADAS = [
    "puta", "puto", "pendejo", "pendeja", "idiota", "imbécil", "imbecil",
    "estúpido", "estupido", "cabrón", "cabron", "hijo de puta", "mierda",
    "chinga", "chingada", "verga", "culero", "culera", "mamón", "mamon",
    "pinche", "joto", "perra", "bastardo", "inútil", "inutil",
    "fuck", "shit", "asshole", "bitch", "damn"
]

def contiene_insulto(texto):
    return any(p in texto.lower() for p in PALABRAS_INAPROPIADAS)


# ── Comandos principales ───────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    guardar_usuario(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(
        f"Hola {user.first_name} 👋 Soy *Serenity*, tu acompañante emocional de la UNACAR.\n\n"
        "Estoy aquí para escucharte en un espacio seguro. "
        "Puedes escribirme cuando quieras. Usa /menu para ver las opciones.",
        parse_mode="Markdown"
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_menu = (
        "📋 *Menú de Serenity*\n\n"
        "💬 *Hablar conmigo* — Escríbeme cómo te sientes, estoy aquí para escucharte.\n\n"
        "🎤 *Mensaje de voz* — También puedes mandarme un audio.\n\n"
        "🧠 *Apoyo emocional* — Si estás pasando por estrés, ansiedad o tristeza, cuéntame.\n\n"
        "👩‍⚕️ *Directorio de psicólogos* — Escribe algo como _\"quiero hablar con un psicólogo\"_ "
        "y te doy la información completa + el PDF oficial.\n\n"
        "──────────────────\n"
        "Comandos:\n"
        "/start — Bienvenida\n"
        "/menu — Ver este menú\n"
        "/directorio — Directorio de psicólogos en PDF"
    )
    await update.message.reply_text(texto_menu, parse_mode="Markdown")


async def directorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Un momento, te envío el directorio oficial 📋")
    await _enviar_directorio_pdf(update)


# ── Mensajes y lógica principal ────────────────────────────────────────────────

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mensaje_texto = update.message.text

    data = await obtener_respuesta_ia(user_id, mensaje_texto)
    await update.message.reply_text(data["respuesta"])

    if data.get("enviar_directorio"):
        await _enviar_directorio_pdf(update)

    if data.get("nivel_riesgo") == "alto":
        await update.message.reply_text(
            "He detectado que podrías estar pasando por un momento muy difícil. "
            "Estoy aquí para apoyarte. 💙\n\n"
            "Para poder conectarte con un orientador de la UNACAR, "
            "necesito algunos datos. ¿Cuál es tu *nombre completo*?",
            parse_mode="Markdown"
        )
        context.user_data["alerta_pendiente"] = data.get("razon", "")
        return NOMBRE

    return ConversationHandler.END


# ── Flujo de registro activado por alerta alta ────────────────────────────────

async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.message.text.strip()

    if contiene_insulto(nombre) or len(nombre) < 5 or not re.search(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ]', nombre):
        await update.message.reply_text(
            "⚠️ Por favor ingresa un nombre válido. ¿Cuál es tu nombre completo?"
        )
        return NOMBRE

    context.user_data["nombre_completo"] = nombre
    await update.message.reply_text(
        f"Gracias, *{nombre}* ✅\n\nAhora dime tu *matrícula* (6 dígitos numéricos):",
        parse_mode="Markdown"
    )
    return MATRICULA


async def recibir_matricula(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matricula = update.message.text.strip()

    if not re.fullmatch(r'\d{6}', matricula) or contiene_insulto(matricula):
        await update.message.reply_text(
            "⚠️ La matrícula debe ser exactamente *6 dígitos numéricos* (ej. 213456):",
            parse_mode="Markdown"
        )
        return MATRICULA

    context.user_data["matricula"] = matricula
    correo_esperado = f"{matricula}@mail.unacar.mx"
    await update.message.reply_text(
        f"Matrícula *{matricula}* ✅\n\n"
        f"Ahora tu *correo institucional* (formato: `{correo_esperado}`):",
        parse_mode="Markdown"
    )
    return CORREO


async def recibir_correo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correo = update.message.text.strip().lower()
    matricula = context.user_data.get("matricula", "")
    correo_esperado = f"{matricula}@mail.unacar.mx"

    if correo != correo_esperado or contiene_insulto(correo):
        await update.message.reply_text(
            f"⚠️ Debe ser exactamente: `{correo_esperado}`\nInténtalo de nuevo:",
            parse_mode="Markdown"
        )
        return CORREO

    context.user_data["correo"] = correo
    await update.message.reply_text(
        f"Correo verificado ✅\n\nPor último, tu *número de teléfono* (10 dígitos):",
        parse_mode="Markdown"
    )
    return TELEFONO


async def recibir_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telefono = update.message.text.strip()

    if not re.fullmatch(r'\d{10}', telefono) or contiene_insulto(telefono):
        await update.message.reply_text(
            "⚠️ El número debe tener exactamente *10 dígitos* (ej. 9381234567):",
            parse_mode="Markdown"
        )
        return TELEFONO

    user_id = update.effective_user.id
    nombre = context.user_data["nombre_completo"]
    matricula = context.user_data["matricula"]
    correo = context.user_data["correo"]
    razon = context.user_data.get("alerta_pendiente", "")

    completar_registro(user_id, nombre, matricula, correo, telefono)

    await update.message.reply_text(
        f"Gracias, *{nombre}*. Tus datos han sido enviados a un orientador de la UNACAR 💙\n\n"
        "Estarán contigo pronto. Mientras tanto, aquí estoy si necesitas hablar.",
        parse_mode="Markdown"
    )

    # Disparar alerta con datos completos
    usuario_info = obtener_datos_usuario(user_id)
    enviar_whatsapp_emergencia(
        f"🚨 Riesgo ALTO\n"
        f"Nombre: {nombre}\n"
        f"Matrícula: {matricula}\n"
        f"Correo: {correo}\n"
        f"Tel: {telefono}\n"
        f"Motivo: {razon}"
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Entendido. Aquí estoy si necesitas hablar. 💙")
    return ConversationHandler.END


# ── PDF ────────────────────────────────────────────────────────────────────────

async def _enviar_directorio_pdf(update: Update):
    if not os.path.exists(PDF_DIRECTORIO):
        await update.message.reply_text(
            "📎 No encontré el PDF en el servidor. "
            "Puedes pedirlo en la USP (puerta 204, Campus Principal)."
        )
        return
    try:
        with open(PDF_DIRECTORIO, "rb") as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename="Directorio_Psicopedagogico_UNACAR_2026.pdf",
                caption=(
                    "📋 *Directorio Oficial USP — UNACAR 2026*\n\n"
                    "Datos de contacto, horarios y facultades de cada psicólogo/a. "
                    "Recuerda enviar tu horario de clases al escribirles. 💙"
                ),
                parse_mode="Markdown"
            )
        logger.info(f"PDF enviado al usuario {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error enviando PDF: {e}")
        await update.message.reply_text(
            "Tuve un problema enviando el PDF. Puedes pedirlo en la USP (puerta 204)."
        )


# ── Audio ──────────────────────────────────────────────────────────────────────

async def manejar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    archivo = await update.message.voice.get_file()
    ruta_audio = os.path.join(TMP_DIR, f"{user_id}_{archivo.file_id}.ogg")
    await archivo.download_to_drive(ruta_audio)

    try:
        with open(ruta_audio, "rb") as file:
            transcription = await groq_client.audio.transcriptions.create(
                file=(ruta_audio, file.read()),
                model="whisper-large-v3-turbo",
                response_format="text"
            )
        texto_transcrito = transcription
    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        texto_transcrito = "Lo siento, tuve problemas escuchando el audio. ¿Podrías escribirlo?"
    finally:
        if os.path.exists(ruta_audio):
            os.remove(ruta_audio)

    update.message.text = texto_transcrito
    await manejar_mensaje(update, context)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    crear_base_datos()

    if not TOKEN_TELEGRAM:
        logger.error("No se encontró el TOKEN_TELEGRAM en el archivo .env")
        return

    app = (
        Application.builder()
        .token(TOKEN_TELEGRAM)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # ConversationHandler para registro activado por alerta alta
    alerta_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje)],
        states={
            NOMBRE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            MATRICULA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_matricula)],
            CORREO:    [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_correo)],
            TELEFONO:  [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("directorio", directorio))
    app.add_handler(alerta_handler)
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_audio))

    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    PORT = int(os.getenv("PORT", "8080"))

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{TOKEN_TELEGRAM}"
        logger.info(f"Serenity en línea con WEBHOOK → {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN_TELEGRAM,
            webhook_url=webhook_url,
        )
    else:
        logger.info("Serenity en línea con POLLING (modo local)...")
        app.run_polling(poll_interval=0.0, timeout=20, bootstrap_retries=-1, drop_pending_updates=True)


if __name__ == "__main__":
    main()