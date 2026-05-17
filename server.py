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
from telegram import Update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT        = int(os.getenv("PORT", 10000))

# ── Event loop exclusivo para el bot ─────────────────────────────────────────
_bot_loop = asyncio.new_event_loop()
_bot_app  = None   # se asigna en _init_bot()


def _run_bot_loop():
    """Hilo de fondo: ejecuta el event loop del bot indefinidamente."""
    asyncio.set_event_loop(_bot_loop)
    _bot_loop.run_forever()


# ── Ruta webhook de Telegram dentro de Flask ─────────────────────────────────
@flask_app.route(f"/webhook/{TOKEN_TELEGRAM}", methods=["POST"])
def telegram_webhook():
    """
    Telegram llama a este endpoint cada vez que llega un update.
    Lo procesamos en el event loop del bot (hilo separado) y respondemos OK.
    """
    if _bot_app is None:
        return "Bot no inicializado", 503

    data   = flask_request.get_json(force=True, silent=True) or {}
    update = Update.de_json(data, _bot_app.bot)

    # Enviamos la corrutina al loop del bot y esperamos a que termine
    future = asyncio.run_coroutine_threadsafe(
        _bot_app.process_update(update),
        _bot_loop,
    )
    try:
        future.result(timeout=30)   # máximo 30 s para procesar el update
    except Exception as e:
        logger.error(f"Error procesando update de Telegram: {e}")

    return "OK", 200


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