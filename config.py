import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from twilio.rest import Client as TwilioClient

# Carga el archivo .env para ocultar contraseñas
load_dotenv()

# --- CONFIGURACIÓN DE RUTAS ---
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TMP_DIR = Path(BASE_DIR) / "tmp_audio"
TMP_DIR.mkdir(parents=True, exist_ok=True)

db_file = os.path.join(BASE_DIR, "serenity.db")
JSON_PATH = os.path.join(BASE_DIR, "info.json")
PDF_DIRECTORIO = os.path.join(BASE_DIR, "Directorio Psicopedagógico.pdf")

# --- VARIABLES DE ENTORNO (Contraseñas y Tokens) ---
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")
TWILIO_WHATSAPP_TO = os.getenv("TWILIO_WHATSAPP_TO", "")

COOLDOWN_DIAS = int(os.getenv("COOLDOWN_DIAS_INFO", "3"))
LINK_UNACAR = os.getenv(
    "LINK_UNACAR",
    "https://www.unacar.mx/unacar/Documentos/DIRECTORIO_COMPLETO_MOD_08_06_23.pdf",
)
RISK_COOLDOWN_MINUTES = 0

# --- INICIALIZACIÓN DE CLIENTES (APIs) ---
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
twilio_client = TwilioClient(TWILIO_SID, TWILIO_TOKEN) if TWILIO_SID and TWILIO_TOKEN else None

# --- CONFIGURACIÓN DEL REGISTRO DE ERRORES (Logs) ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("serenity")