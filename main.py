import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from faster_whisper import WhisperModel

# Importamos nuestras propias piezas del rompecabezas
from config import TOKEN_TELEGRAM, TMP_DIR, logger, JSON_PATH, PDF_DIRECTORIO
from database import crear_base_datos, guardar_usuario
from ai_core import obtener_respuesta_ia
from alertas import enviar_correo_alerta, enviar_whatsapp_emergencia

# --- INICIALIZACIÓN DE MODELO DE AUDIO ---
# Lo cargamos aquí para que solo se cargue una vez al encender
model_audio = WhisperModel("small", device="cpu", compute_type="int8")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    guardar_usuario(user.id, user.username, user.first_name, user.last_name)
    
    texto_bienvenida = (
        f"Hola {user.first_name} 👋 Soy **Serenity**, tu acompañante emocional.\n\n"
        "Estoy aquí para escucharte en un espacio seguro. Tus datos son privados "
        "y solo se compartirán con especialistas en caso de riesgo detectado.\n\n"
        "Puedes escribirme, mandarme un audio o usar /menu."
    )
    await update.message.reply_text(texto_bienvenida, parse_mode="Markdown")

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mensaje_texto = update.message.text

    # 1. Obtenemos respuesta de la IA (esto ya guarda en DB y analiza riesgo)
    data = await obtener_respuesta_ia(user_id, mensaje_texto)
    
    # 2. Responder al usuario
    await update.message.reply_text(data["respuesta"])

    # 3. Lógica de Alerta Crítica
    if data["nivel_riesgo"] == "alto":
        await update.message.reply_text("He detectado que podrías estar pasando por un momento muy difícil. Estoy aquí para apoyarte.")
        # Ejemplo de activación de alerta
        enviar_whatsapp_emergencia(f"Riesgo ALTO detectado en usuario {user_id}. Motivo: {data['razon']}")

async def manejar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    archivo = await update.message.voice.get_file()
    ruta_audio = os.path.join(TMP_DIR, f"{user_id}_{archivo.file_id}.ogg")
    
    await archivo.download_to_drive(ruta_audio)
    
    # Transcribir audio a texto
    segments, _ = model_audio.transcribe(ruta_audio, beam_size=5)
    texto_transcrito = " ".join([s.text for s in segments])
    
    # Eliminar archivo temporal
    os.remove(ruta_audio)
    
    # Procesar como si fuera un mensaje de texto
    update.message.text = texto_transcrito
    await manejar_mensaje(update, context)

def main():
    # Asegurarnos de que la DB exista
    crear_base_datos()

    if not TOKEN_TELEGRAM:
        logger.error("No se encontró el TOKEN_TELEGRAM en el archivo .env")
        return

    # Configurar el Bot
    # app = Application.builder().token(TOKEN_TELEGRAM).build() <--( el origianl )
    # Configuración de timeouts de red profesional
    app = (
        Application.builder()
        .token(TOKEN_TELEGRAM)
        .connect_timeout(30) # Tiempo para conectar al servidor
        .read_timeout(30)    # Tiempo esperando respuesta
        .write_timeout(30)   # Tiempo para enviar la respuesta
        .pool_timeout(30)    # Tiempo de espera en la cola de conexiones
        .build()
    )

    # Manejadores
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, manejar_audio))

    logger.info("Serenity Modularizada está en línea...")
    app.run_polling()

# IMPORTANTE: Aquí ajustamos el polling para que sea reactivo
    # bootstrap_retries=-1 hace que no se rinda si hay micro-cortes
    app.run_polling(poll_interval=0.0, timeout=20, bootstrap_retries=-1)

if __name__ == "__main__":
    main()