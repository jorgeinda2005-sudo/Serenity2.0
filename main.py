import os
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

from serenity.config import TOKEN_TELEGRAM, PDF_DIRECTORIO, logger
from serenity.database import (
    crear_base_datos, guardar_usuario, completar_registro,
    usuario_registrado, obtener_datos_usuario, obtener_psicologos_por_facultad,
    registrar_correo_enviado
)
from serenity.ai_core import obtener_respuesta_ia
from serenity.alertas import enviar_correo_alerta, enviar_whatsapp_emergencia
from serenity.audio_transcription import AudioTranscriptionError, transcribir_audio_telegram

# ── Estados del flujo de registro ─────────────────────────────────────────────
ESTADO_NOMBRE    = "nombre"
ESTADO_MATRICULA = "matricula"
ESTADO_CORREO    = "correo"
ESTADO_TELEFONO  = "telefono"
ESTADO_FACULTAD  = "facultad"

# ── Facultades UNACAR ──────────────────────────────────────────────────────────
FACULTADES = [
    "Facultad de Ciencias de la Información",
    "Facultad de Ciencias Económicas Administrativas",
    "Facultad de Ciencias Educativas",
    "Facultad de Derecho",
    "Facultad de Química",
    "Facultad de Ciencias de la Salud",
    "Facultad de Ciencias Naturales",
    "Facultad de Ingeniería",
]

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
        "🔒 *Tu privacidad es importante para nosotros.*\n"
        "Tus conversaciones son privadas y no se comparten con otras personas. En caso de que durante una conversación se active "
        "una alerta de riesgo, la información podrá ser compartida únicamente con los psicólogos de la universidad, "
        "y esto se realizará con tu consentimiento para que puedan brindarte el apoyo adecuado.\n\n"
        "No tienes que enfrentar todo en silencio. Puedes contarme cómo te sientes, qué está pasando o simplemente comenzar una conversación. "
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
        "👩‍⚕️ *Directorio de psicólogos* — ¿Quieres hablar con un profesional? Escribe _\"quiero hablar con un profesional\"_ "
        "o usando /directorio y te doy la información oficial.\n\n"
        "🔒 Privacidad — Tus conversaciones son privadas. Si se activa una alerta de riesgo, la información podrá compartirse con los "
        "psicólogos de la universidad únicamente con tu consentimiento, para brindarte el apoyo adecuado."
        "\n──────────────────\n"
        "Comandos:\n"
        "/start — Iniciar Serenity\n"
        "/menu — Ver este menú\n"
        "/directorio — Directorio de psicólogos en PDF",
        parse_mode="Markdown"
    )


async def directorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Un momento, te envío el directorio oficial 📋")
    await _enviar_directorio_pdf(update)


# ══════════════════════════════════════════════════════════════════════════════
# MENSAJE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE, texto_override=None):
    user_id = update.effective_user.id
    texto   = (texto_override if texto_override is not None else update.message.text).strip()
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
        context.user_data["telefono"] = texto
        context.user_data["estado"]   = ESTADO_FACULTAD

        keyboard = []
        for i in range(0, len(FACULTADES), 2):
            row = [InlineKeyboardButton(FACULTADES[i], callback_data=f"fac_{i}")]
            if i + 1 < len(FACULTADES):
                row.append(InlineKeyboardButton(FACULTADES[i+1], callback_data=f"fac_{i+1}"))
            keyboard.append(row)

        await update.message.reply_text(
            "Casi listo 😊 ¿A qué facultad perteneces?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if estado == ESTADO_FACULTAD:
        facultad = texto.strip()
        if facultad not in FACULTADES:
            await update.message.reply_text(
                "Por favor selecciona tu facultad usando los botones 😊"
            )
            return
        context.user_data["facultad"] = facultad
        await _guardar_y_notificar(update, context)
        return

    # ── Conversación normal con la IA ──────────────────────────────────────────
    try:
        data = await obtener_respuesta_ia(user_id, texto)
    except Exception as e:
        logger.error(f"Error en obtener_respuesta_ia: {e}")
        await update.message.reply_text(
            "Tuve un problema procesando tu mensaje. ¿Podrías intentarlo de nuevo? 💙"
        )
        return

    await update.message.reply_text(data["respuesta"])

    ultima = context.user_data.get("ultima_alerta")
    cooldown_ok = (ultima is None or datetime.now() - ultima > timedelta(minutes=60))

    if data.get("nivel_riesgo") == "alto" and cooldown_ok:
        context.user_data["ultima_alerta"] = datetime.now()
        context.user_data["alerta_pendiente"] = data.get("razon", "")
        context.user_data["ya_registrado"] = usuario_registrado(user_id)
        await preguntar_apoyo(update, context)

    elif data.get("enviar_directorio") and data.get("nivel_riesgo") != "alto":
        await _enviar_directorio_pdf(update)


# ══════════════════════════════════════════════════════════════════════════════
# FLUJO DE CONSENTIMIENTO
# ══════════════════════════════════════════════════════════════════════════════

async def preguntar_apoyo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("👩‍⚕️ Quiero hablar con un psicólogo", callback_data="datos_si"),
        InlineKeyboardButton("💬 Quiero seguir hablando aquí", callback_data="datos_no"),
        InlineKeyboardButton("🆘 Necesito ayuda ahora", callback_data="apoyo_sos"),
    ]]
    await update.message.reply_text(
        "💙 Noto que estás pasando por un momento difícil "
        "y me gustaría que pudieras recibir apoyo especializado.\n\n"
        "¿Te gustaría hablar con alguien que pueda acompañarte "
        "de manera más cercana?\n\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def manejar_consentimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "apoyo_sos":
        await query.edit_message_text(
            "💙 Está bien, no tienes que decidirlo todo ahora.\n\nQuiero que sepas que puedes volver a pedir ayuda cuando lo necesites. "
            "Si en algún momento sientes que podrías hacerte daño o que estás en peligro, busca ayuda inmediata y procura no quedarte a solas.\n\n"
            f"{NUMEROS_CRISIS}\n\n"
            "👩‍⚕️ También puedes acercarte a cualquiera de los psicólogos de la UNACAR. A continuación te comparto el directorio oficial "
            "para que puedas consultarlo cuando lo necesites. \n\n💙 No estás solo/a. Puedes volver a hablar conmigo en cualquier momento.",
            parse_mode="Markdown"
        )
        await _enviar_directorio_pdf_desde_callback(query)
        context.user_data.clear()

    elif query.data == "datos_si":
        ya_registrado = context.user_data.get("ya_registrado", False)
        if ya_registrado:
            user_id = query.from_user.id
            usuario_info = obtener_datos_usuario(user_id)
            razon = context.user_data.get("alerta_pendiente", "")
            await query.edit_message_text(
                "💙 Gracias por confiar. Ya tenemos tus datos registrados.\n\n"
                "Compartiremos tu solicitud con el equipo de psicología de la universidad para que puedan brindarte seguimiento.\n\n"
                "No tienes que hacer nada más. Yo sigo aquí contigo 🤗",
                parse_mode="Markdown"
            )
            await _enviar_directorio_pdf_desde_callback(query)
            try:
                enviar_whatsapp_emergencia(
                    f"🚨 Riesgo ALTO (usuario ya registrado)\n"
                    f"Nombre: {usuario_info.get('nombre_completo', '—')}\n"
                    f"Matrícula: {usuario_info.get('matricula', '—')}\n"
                    f"Correo: {usuario_info.get('correo', '—')}\n"
                    f"Tel: {usuario_info.get('telefono', '—')}\n"
                    f"Motivo: {razon}"
                )
            except Exception as e:
                logger.error(f"Error enviando WhatsApp: {e}")
            try:
                facultad = usuario_info.get("facultad", "") or context.user_data.get("facultad", "")
                _notificar_psicologos_por_facultad(
                    user_id=user_id,
                    facultad=facultad,
                    usuario_info=usuario_info,
                    motivo=f"El alumno solicito apoyo nuevamente. Motivo: {razon}",
                )
            except Exception as e:
                logger.error(f"Error enviando correo: {e}")
            context.user_data.clear()
        else:
            await query.edit_message_text(
                "Gracias por confiar en mí 💙\n\n"
                "Para conectarte con un profesional, "
                "¿me podrías decir tu *nombre completo*?",
                parse_mode="Markdown"
            )
            context.user_data["estado"] = ESTADO_NOMBRE

    elif query.data == "datos_no":
        await query.edit_message_text(
            "💙 Está bien, respeto tu decisión. No tienes que hacerlo ahora.\n\n"
            "Podemos seguir hablando aquí y puedes contarme cómo te sientes "
            "o qué estás pasando. Estoy aquí para escucharte.\n\n"
            f"{NUMEROS_CRISIS}\n\n"
            "Y cuando te sientas listo/a, también puedes acercarte "
            "a cualquiera de los psicólogos de la UNACAR:",
            parse_mode="Markdown"
        )
        await _enviar_directorio_pdf_desde_callback(query)
        context.user_data.clear()

    elif query.data.startswith("fac_"):
        idx = int(query.data.split("_")[1])
        facultad = FACULTADES[idx]
        context.user_data["facultad"] = facultad
        await query.edit_message_text(
            f"Facultad registrada: *{facultad}* ✅",
            parse_mode="Markdown"
        )
        await _guardar_y_notificar_query(query, context)

# ══════════════════════════════════════════════════════════════════════════════
# GUARDAR REGISTRO Y NOTIFICAR
# ══════════════════════════════════════════════════════════════════════════════

def limpiar_historial_usuario(user_id):
    from serenity.database import get_conn, release_conn
    conn = get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM conversaciones WHERE user_id=%s", (user_id,))
        conn.commit()
        logger.info(f"Historial limpiado para user_id {user_id}")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Error limpiando historial: {e}")
    finally:
        release_conn(conn)


def _notificar_psicologos_por_facultad(user_id, facultad, usuario_info, motivo):
    destinatario = "josemoscosotareas2017@gmail.com"
    asunto = f"ALERTA DE RIESGO - Serenity - Usuario {usuario_info.get('id', user_id)}"
    try:
        enviar_correo_alerta(destinatario, usuario_info, motivo)
        registrar_correo_enviado(
            user_id=user_id,
            psicologo_id=None,
            destinatario=destinatario,
            facultad=facultad,
            asunto=asunto,
            motivo=motivo,
            estado="enviado",
            error=None,
        )
        return 1
    except Exception as e:
        registrar_correo_enviado(
            user_id=user_id,
            psicologo_id=None,
            destinatario=destinatario,
            facultad=facultad,
            asunto=asunto,
            motivo=motivo,
            estado="error",
            error=str(e)[:500],
        )
        logger.error(f"Error enviando correo a {destinatario}: {e}")
        return 0


async def _guardar_y_notificar(update, context):
    user_id   = update.effective_user.id
    nombre    = context.user_data.get("nombre_completo", "")
    matricula = context.user_data.get("matricula", "")
    correo    = context.user_data.get("correo", "")
    telefono  = context.user_data.get("telefono", "")
    facultad  = context.user_data.get("facultad", "")
    razon     = context.user_data.get("alerta_pendiente", "")

    completar_registro(user_id, nombre, matricula, correo, telefono)

    from serenity.database import get_conn, release_conn
    conn = get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE usuarios SET facultad=%s WHERE user_id=%s", (facultad, user_id))
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Error guardando facultad: {e}")
        finally:
            release_conn(conn)

    await update.message.reply_text(
        "💙 Quiero que sepas que no estás solo/a en esto.\n\n"
        "Hay personas especializadas que pueden acompañarte de una manera más profunda. "
        "Te comparto el directorio para que puedas contactar al psicólogo adecuado:\n\n"
        "No tienes que hacer nada ahora. Yo sigo aquí contigo 🤗",
        parse_mode="Markdown"
    )
    await _enviar_directorio_pdf(update)

    try:
        enviar_whatsapp_emergencia(
            f"🚨 Riesgo ALTO\n"
            f"Nombre: {nombre}\nMatrícula: {matricula}\n"
            f"Correo: {correo}\nTel: {telefono}\n"
            f"Facultad: {facultad}\nMotivo: {razon}"
        )
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")

    try:
        usuario_info = obtener_datos_usuario(user_id)
        _notificar_psicologos_por_facultad(
            user_id=user_id,
            facultad=facultad,
            usuario_info=usuario_info,
            motivo=f"El alumno solicito apoyo voluntariamente. Facultad: {facultad}. Motivo: {razon}",
        )
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")

    limpiar_historial_usuario(user_id)
    context.user_data.clear()
    context.user_data["ultima_alerta"] = datetime.now()


async def _guardar_y_notificar_query(query, context):
    user_id   = query.from_user.id
    nombre    = context.user_data.get("nombre_completo", "")
    matricula = context.user_data.get("matricula", "")
    correo    = context.user_data.get("correo", "")
    telefono  = context.user_data.get("telefono", "")
    facultad  = context.user_data.get("facultad", "")
    razon     = context.user_data.get("alerta_pendiente", "")

    completar_registro(user_id, nombre, matricula, correo, telefono)

    from serenity.database import get_conn, release_conn
    conn = get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE usuarios SET facultad=%s WHERE user_id=%s", (facultad, user_id))
            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Error guardando facultad: {e}")
        finally:
            release_conn(conn)

    await query.message.reply_text(
        "💙 Quiero que sepas que no estás solo/a en esto.\n\n"
        "Hay personas especializadas que pueden acompañarte de una manera más profunda. "
        "Te comparto el directorio para que puedas contactar al psicólogo adecuado:\n\n"
        "No tienes que hacer nada ahora. Yo sigo aquí contigo 🤗",
        parse_mode="Markdown"
    )
    await _enviar_directorio_pdf_desde_callback(query)

    try:
        enviar_whatsapp_emergencia(
            f"🚨 Riesgo ALTO\nNombre: {nombre}\nMatrícula: {matricula}\n"
            f"Correo: {correo}\nTel: {telefono}\nFacultad: {facultad}\nMotivo: {razon}"
        )
    except Exception as e:
        logger.error(f"Error enviando WhatsApp: {e}")

    try:
        usuario_info = obtener_datos_usuario(user_id)
        _notificar_psicologos_por_facultad(
            user_id=user_id,
            facultad=facultad,
            usuario_info=usuario_info,
            motivo=f"El alumno solicito apoyo. Facultad: {facultad}. Motivo: {razon}",
        )
    except Exception as e:
        logger.error(f"Error enviando correo: {e}")

    limpiar_historial_usuario(user_id)
    context.user_data.clear()
    context.user_data["ultima_alerta"] = datetime.now()

    await query.message.reply_text("Sigo aquí si quieres hablar de cualquier otra cosa 💙")


# ══════════════════════════════════════════════════════════════════════════════
# PDF
# ══════════════════════════════════════════════════════════════════════════════

async def _enviar_directorio_pdf_desde_callback(query):
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
    user_id = update.effective_user.id
    try:
        texto_transcrito = await transcribir_audio_telegram(update.message, user_id)
    except AudioTranscriptionError as e:
        await update.message.reply_text(e.user_message)
        return

    await update.message.reply_text(f"Transcribi tu audio asi:\n\n{texto_transcrito}")
    await manejar_mensaje(update, context, texto_override=texto_transcrito)

# BUILD APP — usado por server.py para el webhook integrado en Flask
# ══════════════════════════════════════════════════════════════════════════════

def build_app() -> Application:
    """
    Construye y configura la Application de python-telegram-bot.
    No inicia ningún servidor ni bucle de eventos propio.
    Usado por server.py para el modo webhook integrado en Flask.
    """
    if not TOKEN_TELEGRAM:
        raise RuntimeError("TOKEN_TELEGRAM no configurado en .env")

    application = (
        Application.builder()
        .token(TOKEN_TELEGRAM)
        .connect_timeout(60)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(60)
        .build()
    )

    application.add_handler(CommandHandler("start",      start))
    application.add_handler(CommandHandler("menu",       menu))
    application.add_handler(CommandHandler("directorio", directorio))
    application.add_handler(CallbackQueryHandler(manejar_consentimiento))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,   manejar_audio))

    return application


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — solo para ejecución local con polling  (python main.py)
# ══════════════════════════════════════════════════════════════════════════════

def main():
    crear_base_datos()
    application = build_app()
    logger.info("Serenity en línea con POLLING (modo local)...")
    application.run_polling(
        poll_interval=0.0,
        timeout=20,
        bootstrap_retries=-1,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
