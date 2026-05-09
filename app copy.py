import os
import threading
import logging
from waitress import serve
from app import app as flask_app
from main import main as run_bot

# Configurar logs para ver qué pasa en Render
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def start_telegram_bot():
    """Ejecuta el bot de Telegram en un hilo de fondo."""
    try:
        run_bot()
    except Exception as e:
        logging.error(f"Error crítico en el hilo del bot: {e}")

if __name__ == "__main__":
    # 1. Arrancar el bot en un hilo secundario (daemon=True significa que si el web se apaga, el bot también)
    bot_thread = threading.Thread(target=start_telegram_bot, daemon=True)
    bot_thread.start()
    logging.info("✅ Bot de Telegram iniciado en segundo plano.")

    # 2. Arrancar el panel web (Flask) en el hilo principal
    port = int(os.environ.get('PORT', 10000))
    logging.info(f"✅ Panel web (Flask) iniciado en el puerto {port}")
    
    # Usamos waitress en lugar de gunicorn porque es más estable en Windows y maneja bien los threads
    serve(flask_app, host="0.0.0.0", port=port)