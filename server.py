import os
import multiprocessing
import logging
from waitress import serve
from app import app as flask_app
from main import main as run_bot

# Configurar logs para Render
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def start_telegram_bot():
    """Ejecuta el bot en un proceso separado (no un hilo) para evitar errores de asyncio."""
    try:
        run_bot()
    except Exception as e:
        logging.error(f"Error crítico en el proceso del bot: {e}")

if __name__ == "__main__":
    # Usamos Process en lugar de Thread. Así el bot tiene su propio "hilo principal"
    bot_process = multiprocessing.Process(target=start_telegram_bot, daemon=True)
    bot_process.start()
    logging.info("✅ Bot de Telegram iniciado en segundo plano (Proceso separado).")

    # Arrancar el panel web en el proceso principal
    port = int(os.environ.get('PORT', 10000))
    logging.info(f"✅ Panel web (Flask) iniciado en el puerto {port}")
    
    serve(flask_app, host="0.0.0.0", port=port)