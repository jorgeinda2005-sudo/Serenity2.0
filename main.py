import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
 
# Importamos nuestras propias piezas del rompecabezas
from config import TOKEN_TELEGRAM, TMP_DIR, PDF_DIRECTORIO, logger
from database import crear_base_datos, guardar_usuario
from ai_core import obtener_respuesta_ia, groq_client
from alertas import enviar_correo_alerta, enviar_whatsapp_emergencia
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    guardar_usuario(user.id, user.username, user.first_name, user.last_name)
    
    texto_bienvenida = (
        f"Hola {user.first_name} 👋 Soy **Serenity**, tu acompañante emocional.\n\n"
        "Estoy aquí para escucharte en un espacio seguro. Tus datos son privados "
        "y solo se compartirán con especialistas en caso de riesgo detectado.\n\n"
        "Puedes escribirme o mandarme un mensaje de voz. "
        "También puedes usar /menu para ver las opciones disponibles."
    )
    await update.message.reply_text(texto_bienvenida, parse_mode="Markdown")
 
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_menu = (
        "📋 *Menú de Serenity*\n\n"
        "Aquí tienes todo lo que puedo hacer por ti:\n\n"
        "💬 *Hablar conmigo* — Solo escríbeme cómo te sientes, estoy aquí para escucharte.\n\n"
        "🎤 *Mensaje de voz* — También puedes mandarme un audio y lo escucho.\n\n"
        "🧠 *Apoyo emocional* — Si estás pasando por estrés, ansiedad, tristeza o cualquier "
        "situación difícil, cuéntame.\n\n"
        "👩‍⚕️ *Directorio de psicólogos* — Escribe algo como _\"quiero hablar con un psicólogo\"_ "
        "o _\"necesito apoyo profesional\"_ y te doy la información completa + el PDF oficial.\n\n"
        "──────────────────\n"
        "Comandos disponibles:\n"
        "/start — Mensaje de bienvenida\n"
        "/menu — Ver este menú\n"
        "/directorio — Recibir el directorio de psicólogos en PDF"
    )
    await update.message.reply_text(texto_menu, parse_mode="Markdown")
 
async def directorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando directo para obtener el PDF sin pasar por la IA."""
    await update.message.reply_text("Un momento, te envío el directorio oficial 📋")
    await _enviar_directorio_pdf(update)
 
async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mensaje_texto = update.message.text
 
    # 1. Obtenemos respuesta de la IA (esto ya guarda en DB y analiza riesgo)
    data = await obtener_respuesta_ia(user_id, mensaje_texto)
 
    # 2. Responder al usuario con el mensaje de Serenity
    await update.message.reply_text(data["respuesta"])
 
    # 3. Enviar el PDF del directorio si la IA lo detectó como necesario
    if data.get("enviar_directorio"):
        await _enviar_directorio_pdf(update)
 
    # 4. Lógica de Alerta Crítica
    if data.get("nivel_riesgo") == "alto":
        await update.message.reply_text(
            "He detectado que podrías estar pasando por un momento muy difícil. "
            "Estoy aquí para apoyarte. 💙"
        )
        enviar_whatsapp_emergencia(
            f"Riesgo ALTO detectado en usuario {user_id}. Motivo: {data.get('razon')}"
        )
 
async def _enviar_directorio_pdf(update: Update):
    """Envía el PDF oficial del directorio de psicólogos al usuario."""
    if not os.path.exists(PDF_DIRECTORIO):
        logger.warning(f"PDF del directorio no encontrado en: {PDF_DIRECTORIO}")
        await update.message.reply_text(
            "📎 Quise enviarte el directorio oficial en PDF, pero no lo encontré en el servidor. "
            "Puedes pedirlo directamente en la USP (puerta 204, Campus Principal)."
        )
        return
 
    try:
        with open(PDF_DIRECTORIO, "rb") as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename="Directorio_Psicopedagogico_UNACAR_2026.pdf",
                caption=(
                    "📋 *Directorio Oficial de la Unidad de Servicios Psicopedagógicos — UNACAR 2026*\n\n"
                    "Aquí encontrarás los datos de contacto, horarios y facultades que atiende "
                    "cada psicólogo/a. Recuerda enviar tu horario de clases al escribirles por correo. 💙"
                ),
                parse_mode="Markdown"
            )
        logger.info(f"Directorio PDF enviado al usuario {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Error enviando el PDF del directorio: {e}")
        await update.message.reply_text(
            "Tuve un problema enviando el PDF, pero puedes consultar el directorio "
            "directamente en la USP (puerta 204, Campus Principal)."
        )
 
async def manejar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    archivo = await update.message.voice.get_file()
    ruta_audio = os.path.join(TMP_DIR, f"{user_id}_{archivo.file_id}.ogg")
    
    await archivo.download_to_drive(ruta_audio)
    
    # Transcribir audio a texto usando Groq (Whisper en la nube)
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
        # Eliminar archivo temporal siempre
        if os.path.exists(ruta_audio):
            os.remove(ruta_audio)
    
    # Procesar como si fuera un mensaje de texto
    update.message.text = texto_transcrito
    await manejar_mensaje(update, context)
 
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("directorio", directorio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_audio))

    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    PORT = int(os.getenv("PORT", "8080"))

    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{TOKEN_TELEGRAM}"
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