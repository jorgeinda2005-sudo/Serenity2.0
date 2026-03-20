import os
import re
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from config import TOKEN_TELEGRAM, TMP_DIR, PDF_DIRECTORIO, logger
from database import (
    crear_base_datos, guardar_usuario, completar_registro,
    usuario_registrado, obtener_datos_usuario
)
from ai_core import obtener_respuesta_ia, groq_client
from alertas import enviar_correo_alerta, enviar_whatsapp_emergencia

# ── Estados del flujo de registro ─────────────────────────────────────────────
ESTADO_NOMBRE    = "nombre"
ESTADO_MATRICULA = "matricula"
ESTADO_CORREO    = "correo"
ESTADO_TELEFONO  = "telefono"

# ── Líneas de crisis ───────────────────────────────────────────────────────────
NUMEROS_CRISIS = (
    "📞 *Líneas de apoyo disponibles las 24 horas:*\n\n"
    "🇲🇽 *SAPTEL (México)*\n"
    "📞 55 5259-8121 — todos los días\n\n"
    "🏥 *IMSS Salud Mental*\n"
    "📞 800 290-0024 — gratuito\n\n"
    "💬 *Crisis Text Line*\n"
    "Escribe HOME al 741741"
)

# ── Palabras inapropiadas ──────────────────────────────────────────────────────
PALABRAS_INAPROPIADAS = [
    "puta", "puto", "pendejo", "pendeja", "idiota", "imbécil", "imbecil",
    "estúpido", "estupido", "cabrón", "cabron", "hijo de puta", "mierda",
    "chinga", "chingada", "verga", "culero", "culera", "mamón", "mamon",
    "pinche", "joto", "perra", "bastardo", "inútil", "inutil",
    "fuck", "shit", "asshole", "bitch", "damn"
]

def contiene_insulto(texto):
    return any(p in texto.lower() for p in PALABRAS_INAPROPIADAS)


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS
# ══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    guardar_usuario(user.id, user.username, user.first_name, user.last_name)
    context.user_data.clear()
    await update.message.reply_text(
        f"Hola {user.first_name} 👋 Soy *Serenity*, tu espacio seguro en la UNACAR.\n\n"
        "🔒 *Tu privacidad es lo primero:*\n"
        "Todo lo que me cuentes es confidencial. Solo compartiría información "
        "con un especialista si detectara que estás en riesgo, "
        "y siempre te lo haré saber antes.\n\n"
        "Estoy aquí para escucharte, sin juicios y sin prisa. "
        "¿Cómo estás hoy? 💙\n\n"
        "_Usa /menu para ver las opciones disponibles._",
        parse_mode="Markdown"
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Menú de Serenity*\n\n"
        "💬 *Hablar conmigo* — Escríbeme cómo te sientes, estoy aquí para escucharte.\n\n"
        "🎤 *Mensaje de voz* — También puedes mandarme un audio.\n\n"
        "🧠 *Apoyo emocional* — Si estás pasando por estrés, ansiedad o tristeza, cuéntame.\n\n"
        "👩‍⚕️ *Directorio de psicólogos* — Escribe _\"quiero hablar con un psicólogo\"_ "
        "y te doy la información completa + el PDF oficial.\n\n"
        "──────────────────\n"
        "Comandos:\n"
        "/start — Bienvenida\n"
        "/menu — Ver este menú\n"
        "/directorio — Directorio de psicólogos en PDF",
        parse_mode="Markdown"
    )


async def directorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Un momento, te envío el directorio oficial 📋")
    await _enviar_directorio_pdf(update)


# ══════════════════════════════════════════════════════════════════════════════
# MENSAJE PRINCIPAL — todo el estado se maneja aquí
# ══════════════════════════════════════════════════════════════════════════════

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto   = update.message.text.strip()
    estado  = context.user_data.get("estado")

    # ── Flujo de registro ──────────────────────────────────────────────────────
    if estado == ESTADO_NOMBRE:
        if contiene_insulto(texto) or len(texto) < 5 or not re.search(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ]', texto):
            await update.message.reply_text("⚠️ Por favor ingresa un nombre válido. ¿Cuál es tu nombre completo?")
            return
        context.user_data["nombre_completo"] = texto
        context.user_data["estado"] = ESTADO_MATRICULA
        await update.message.reply_text(
            f"Gracias, *{texto}* ✅\n\nAhora dime tu *matrícula* (6 dígitos numéricos):",
            parse_mode="Markdown"
        )
        return

    if estado == ESTADO_MATRICULA:
        if not re.fullmatch(r'\d{6}', texto) or contiene_insulto(texto):
            await update.message.reply_text(
                "⚠️ La matrícula debe ser exactamente *6 dígitos numéricos* (ej. 213456):",
                parse_mode="Markdown"
            )
            return
        context.user_data["matricula"] = texto
        context.user_data["estado"] = ESTADO_CORREO
        correo_esperado = f"{texto}@mail.unacar.mx"
        await update.message.reply_text(
            f"Matrícula *{texto}* ✅\n\n"
            f"Ahora tu *correo institucional* (formato: `{correo_esperado}`):",
            parse_mode="Markdown"
        )
        return

    if estado == ESTADO_CORREO:
        matricula       = context.user_data.get("matricula", "")
        correo_esperado = f"{matricula}@mail.unacar.mx"
        correo          = texto.lower()
        if correo != correo_esperado or contiene_insulto(correo):
            await update.message.reply_text(
                f"⚠️ Debe ser exactamente: `{correo_esperado}`\nInténtalo de nuevo:",
                parse_mode="Markdown"
            )
            return
        context.user_data["correo"] = correo
        context.user_data["estado"] = ESTADO_TELEFONO
        await update.message.reply_text(
            "Correo verificado ✅\n\nPor último, tu *número de teléfono* (10 dígitos):",
            parse_mode="Markdown"
        )
        return

    if estado == ESTADO_TELEFONO:
        if not re.fullmatch(r'\d{10}', texto) or contiene_insulto(texto):
            await update.message.reply_text(
                "⚠️ El número debe tener exactamente *10 dígitos* (ej. 9381234567):",
                parse_mode="Markdown"
            )
            return

        nombre    = context.user_data["nombre_completo"]
        matricula = context.user_data["matricula"]
        correo    = context.user_data["correo"]
        razon     = context.user_data.get("alerta_pendiente", "")

        completar_registro(user_id, nombre, matricula, correo, texto)

        await update.message.reply_text(
            "💙 Quiero que sepas que no estás solo/a en esto.\n\n"
            "Hay personas especializadas que pueden acompañarte "
            "de una manera más profunda. Te comparto el directorio "
            "para que puedas contactar al psicólogo que más te convenga:\n\n"
            "No tienes que hacer nada ahora. Yo sigo aquí contigo 🤗",
            parse_mode="Markdown"
        )
        await _enviar_directorio_pdf(update)

        enviar_whatsapp_emergencia(
            f"🚨 Riesgo ALTO\n"
            f"Nombre: {nombre}\nMatrícula: {matricula}\n"
            f"Correo: {correo}\nTel: {texto}\nMotivo: {razon}"
        )
        try:
            usuario_info = obtener_datos_usuario(user_id)
            enviar_correo_alerta(
                "mduarte@delfin.unacar.mx",
                usuario_info,
                f"El alumno solicitó apoyo voluntariamente. Motivo: {razon}"
            )
        except Exception as e:
            logger.error(f"Error enviando correo al psicólogo: {e}")

        # ── Limpiar estado y volver a conversación normal ──
        context.user_data.clear()
        return

    # ── Conversación normal con la IA ──────────────────────────────────────────
    data = await obtener_respuesta_ia(user_id, texto)
    await update.message.reply_text(data["respuesta"])

    # Solo mandar PDF si no hay riesgo alto (en ese caso el PDF va después del consentimiento)
    if data.get("enviar_directorio") and data.get("nivel_riesgo") != "alto":
        await _enviar_directorio_pdf(update)

    if data.get("nivel_riesgo") == "alto":
        # Cooldown: no repetir la alerta si ya se mostró en los últimos 30 minutos
        ultima_alerta = context.user_data.get("ultima_alerta")
        cooldown_ok = (
            ultima_alerta is None or
            datetime.now() - ultima_alerta > timedelta(minutes=30)
        )
        if cooldown_ok:
            context.user_data["alerta_pendiente"] = data.get("razon", "")
            context.user_data["ultima_alerta"] = datetime.now()
            await preguntar_apoyo(update, context)


# ══════════════════════════════════════════════════════════════════════════════
# FLUJO DE CONSENTIMIENTO (botones inline)
# ══════════════════════════════════════════════════════════════════════════════

async def preguntar_apoyo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("✅ Sí, me gustaría", callback_data="apoyo_si"),
        InlineKeyboardButton("❌ No por ahora",    callback_data="apoyo_no"),
    ]]
    await update.message.reply_text(
        "💙 Noto que estás pasando por un momento difícil "
        "y me gustaría que pudieras recibir apoyo especializado.\n\n"
        "¿Te gustaría hablar con alguien que pueda acompañarte "
        "de manera más cercana?\n\n"
        "_Puedes decir que no, está completamente bien_ 🤗",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def manejar_consentimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "apoyo_si":
        keyboard = [[
            InlineKeyboardButton("✅ Sí, comparte mis datos", callback_data="datos_si"),
            InlineKeyboardButton("❌ Prefiero no",            callback_data="datos_no"),
        ]]
        await query.edit_message_text(
            "Me alegra que quieras recibir apoyo 💙\n\n"
            "Para conectarte con el psicólogo adecuado, "
            "¿te gustaría compartir tus datos con él o ella?\n\n"
            "_Tu información solo será vista por el especialista_ 🔒",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "apoyo_no":
        await query.edit_message_text(
            "Está bien, respeto completamente tu decisión 💙\n\n"
            f"{NUMEROS_CRISIS}\n\n"
            "Y cuando te sientas listo/a, también puedes acercarte "
            "a cualquiera de los psicólogos de la UNACAR:",
            parse_mode="Markdown"
        )
        await _enviar_directorio_pdf_desde_callback(query)
        context.user_data.clear()

    elif query.data == "datos_si":
        await query.edit_message_text(
            "Gracias por confiar en mí 💙\n\n"
            "Para conectarte con el psicólogo adecuado, "
            "¿me podrías decir tu *nombre completo*?",
            parse_mode="Markdown"
        )
        context.user_data["estado"] = ESTADO_NOMBRE

    elif query.data == "datos_no":
        await query.edit_message_text(
            "Está bien, no tienes que compartir nada que no quieras 💙\n\n"
            f"{NUMEROS_CRISIS}\n\n"
            "Y cuando te sientas listo/a, también puedes acercarte "
            "a cualquiera de los psicólogos de la UNACAR:",
            parse_mode="Markdown"
        )
        await _enviar_directorio_pdf_desde_callback(query)
        context.user_data.clear()


# ══════════════════════════════════════════════════════════════════════════════
# PDF
# ══════════════════════════════════════════════════════════════════════════════

async def _enviar_directorio_pdf_desde_callback(query):
    """Envía el PDF desde un callback (botón inline)."""
    import os
    from config import PDF_DIRECTORIO
    if not os.path.exists(PDF_DIRECTORIO):
        await query.message.reply_text(
            "📎 No encontré el PDF en el servidor. "
            "Puedes pedirlo en la USP (puerta 204, Campus Principal)."
        )
        return
    try:
        with open(PDF_DIRECTORIO, "rb") as pdf_file:
            await query.message.reply_document(
                document=pdf_file,
                filename="Directorio_Psicopedagogico_UNACAR_2026.pdf",
                caption=(
                    "📋 *Directorio Oficial USP — UNACAR 2026*\n\n"
                    "Datos de contacto, horarios y facultades de cada psicólogo/a. "
                    "Recuerda enviar tu horario de clases al escribirles. 💙"
                ),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error enviando PDF desde callback: {e}")
        await query.message.reply_text(
            "Tuve un problema enviando el PDF. Puedes pedirlo en la USP (puerta 204)."
        )


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


# ══════════════════════════════════════════════════════════════════════════════
# AUDIO
# ══════════════════════════════════════════════════════════════════════════════

async def manejar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id    = update.effective_user.id
    archivo    = await update.message.voice.get_file()
    ruta_audio = os.path.join(TMP_DIR, f"{user_id}_{archivo.file_id}.ogg")
    await archivo.download_to_drive(ruta_audio)

    try:
        def transcribir():
            with open(ruta_audio, "rb") as file:
                return groq_client.audio.transcriptions.create(
                    file=(ruta_audio, file.read()),
                    model="whisper-large-v3-turbo",
                    response_format="text"
                )
        texto_transcrito = await asyncio.to_thread(transcribir)
    except Exception as e:
        logger.error(f"Error transcribiendo audio: {e}")
        texto_transcrito = "Lo siento, tuve problemas escuchando el audio. ¿Podrías escribirlo?"
    finally:
        if os.path.exists(ruta_audio):
            os.remove(ruta_audio)

    update.message.text = texto_transcrito
    await manejar_mensaje(update, context)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

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

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("menu",       menu))
    app.add_handler(CommandHandler("directorio", directorio))
    app.add_handler(CallbackQueryHandler(manejar_consentimiento))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,   manejar_audio))

    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    PORT        = int(os.getenv("PORT", "8080"))

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