"""
server.py — Punto de entrada único para Render
================================================
Un solo proceso, un solo puerto:
  - Flask/waitress atiende el panel web (rutas /dashboard, /alertas, etc.)
  - Flask también recibe los webhooks de Telegram en /webhook/<token>
  - El bot corre en un hilo dedicado con su propio event loop asyncio

Ventajas frente al diseño anterior:
  ✅ No hay dos instancias haciendo polling → nunca más error "Conflict"
  ✅ Bot y Flask comparten el mismo PORT → sin conflicto de puertos
  ✅ Render puede hacer zero-downtime deploys sin problema
"""

import os
import asyncio
import threading
import logging
from waitress import serve
from flask import request as flask_request
from app import app as flask_app
from main import build_app
from serenity.database import crear_base_datos
from serenity.config import TOKEN_TELEGRAM, logger
from serenity.messenger import validar_firma_meta, procesar_webhook
from telegram import Update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

WEBHOOK_URL = os.getenv("WEBHOOK_URL") or os.getenv("WEBHOOK_HOST", "")
WEBHOOK_URL = WEBHOOK_URL.rstrip("/")
PORT        = int(os.getenv("PORT", 10000))

# ── Event loop exclusivo para el bot ─────────────────────────────────────────
_bot_loop = asyncio.new_event_loop()
_bot_app  = None   # se asigna en _init_bot()


def _run_bot_loop():
    """Hilo de fondo: ejecuta el event loop del bot indefinidamente."""
    asyncio.set_event_loop(_bot_loop)
    _bot_loop.run_forever()


# ── Ruta webhook de Telegram dentro de Flask ─────────────────────────────────
# FIX: ruta con parámetro variable en lugar de f-string con TOKEN_TELEGRAM,
# que Pylance marcaba como potencialmente None en tiempo de importación.
# El token se valida dentro del handler para mayor seguridad.
@flask_app.route("/webhook/<token>", methods=["POST"])
def telegram_webhook(token: str):
    """
    Telegram llama a este endpoint cada vez que llega un update.
    Lo procesamos en el event loop del bot (hilo separado) y respondemos OK.
    """
    if token != TOKEN_TELEGRAM:
        return "Unauthorized", 403

    if _bot_app is None:
        return "Bot no inicializado", 503

    data   = flask_request.get_json(force=True, silent=True) or {}
    update = Update.de_json(data, _bot_app.bot)

    # Enviamos la corrutina al loop del bot y respondemos rápido a Telegram.
    # Las respuestas al usuario se mandan desde los handlers de python-telegram-bot.
    future = asyncio.run_coroutine_threadsafe(
        _bot_app.process_update(update),
        _bot_loop,
    )

    def _log_update_error(done_future):
        try:
            done_future.result()
        except Exception as e:
            logger.error(f"Error procesando update de Telegram: {e}")

    future.add_done_callback(_log_update_error)

    return "OK", 200


@flask_app.route("/webhook/messenger", methods=["GET", "POST"])
def messenger_webhook():
    """Webhook de Meta: handshake GET y recepción firmada de mensajes POST."""
    if flask_request.method == "GET":
        verify_token = os.getenv("MESSENGER_VERIFY_TOKEN", "")
        if (
            flask_request.args.get("hub.mode") == "subscribe"
            and verify_token
            and flask_request.args.get("hub.verify_token") == verify_token
        ):
            return flask_request.args.get("hub.challenge", ""), 200
        return "Forbidden", 403

    raw_body = flask_request.get_data(cache=True)
    signature = flask_request.headers.get("X-Hub-Signature-256", "")
    if not validar_firma_meta(raw_body, signature):
        return "Forbidden", 403

    payload = flask_request.get_json(silent=True)
    if not isinstance(payload, dict):
        return "Bad Request", 400
    try:
        asyncio.run(procesar_webhook(payload))
    except Exception:
        logger.exception("Error general en webhook de Messenger")
        return "Temporary failure", 500
    return "EVENT_RECEIVED", 200


# ── Inicialización del bot ────────────────────────────────────────────────────
async def _init_bot():
    """Inicializa la Application y registra el webhook en Telegram."""
    global _bot_app
    _bot_app = build_app()

    await _bot_app.initialize()
    await _bot_app.start()

    webhook_url = f"{WEBHOOK_URL}/webhook/{TOKEN_TELEGRAM}"
    await _bot_app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,   # descarta mensajes acumulados de deploys anteriores
        allowed_updates=Update.ALL_TYPES,
    )
    logger.info(f"✅ Webhook registrado → {webhook_url}")


# ── Arranque principal ────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN_TELEGRAM:
        raise RuntimeError("TELEGRAM_TOKEN no está configurado en las variables de entorno.")
    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL no está configurado. "
            "Agrégala en Render → Environment como: https://tu-app.onrender.com"
        )

    # 1. Verificar conexión con Supabase
    crear_base_datos()

    # 2. Iniciar el event loop del bot en un hilo de fondo
    bot_thread = threading.Thread(target=_run_bot_loop, daemon=True, name="bot-loop")
    bot_thread.start()
    logger.info("✅ Event loop del bot iniciado en hilo de fondo.")

    # 3. Inicializar bot y registrar webhook (bloquea hasta completar)
    init_future = asyncio.run_coroutine_threadsafe(_init_bot(), _bot_loop)
    init_future.result(timeout=30)

    # 4. Arrancar Flask con waitress (proceso principal, bloquea aquí)
    logger.info(f"✅ Panel web iniciado en puerto {PORT}")
    serve(flask_app, host="0.0.0.0", port=PORT, threads=4)
