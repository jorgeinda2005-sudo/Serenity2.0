═══════════════════════════════════════════════════════════════════════════════
  SERENITY — Bot de Acompañamiento Emocional para la UNACAR
═══════════════════════════════════════════════════════════════════════════════

Descripción:
  Serenity es un chatbot de Telegram diseñado para brindar acompañamiento
  emocional a estudiantes de la Universidad Autónoma del Carmen (UNACAR).
  Detecta señales de malestar, ofrece apoyo empático y, en caso de riesgo
  alto, conecta al alumno con un psicólogo de la USP.

═══════════════════════════════════════════════════════════════════════════════
  ESTRUCTURA DEL PROYECTO
═══════════════════════════════════════════════════════════════════════════════

Proyecto Serenity/
│
├── server.py                  Punto de entrada principal
│                              Arranca el bot de Telegram y el panel web
│                              en paralelo usando multiprocessing + waitress
│
├── main.py                    Bot de Telegram
│                              Handlers de comandos, mensajes, audio,
│                              flujo de registro, consentimiento y alertas
│
├── app.py                     Panel web para psicólogos (Flask)
│                              Login, dashboard, alertas, perfiles,
│                              usuarios, reportes PDF, admin
│
├── serenity/                  Paquete — lógica del bot
│   ├── __init__.py            Descripción del paquete
│   ├── config.py              Variables de entorno, rutas y clientes API
│   ├── database.py            Conexión PostgreSQL (pool) y funciones CRUD
│   ├── ai_core.py             Lógica de IA (Groq + OpenAI fallback)
│   └── alertas.py             Envío de alertas por correo y WhatsApp
│
├── templates/                 Plantillas HTML del panel web (Flask)
├── static/                    Archivos estáticos (CSS, JS, imágenes)
├── Documentacion/             Documentos del proyecto
│
├── .env                       Variables de entorno (NO subir a GitHub)
├── .gitignore                 Archivos ignorados por Git
├── requirements.txt           Dependencias de Python
├── info.json                  Información oficial de la USP
└── Directorio Psicopedagógico.pdf   PDF del directorio de psicólogos


═══════════════════════════════════════════════════════════════════════════════
  ARCHIVOS PRINCIPALES (LOS 3 QUE VERÁS EN LA RAÍZ)
═══════════════════════════════════════════════════════════════════════════════

1. server.py  —  Punto de entrada
   ┌──────────────────────────────────────────────────┐
   │  Arranca el bot en un proceso separado           │
   │  Arranca Flask con waitress en el proceso principal│
   │  Usa multiprocessing.Process para evitar errores  │
   │  de asyncio entre Telegram y Flask               │
   └──────────────────────────────────────────────────┘

2. main.py  —  Bot de Telegram
   ┌──────────────────────────────────────────────────┐
   │  Comandos:  /start, /menu, /directorio           │
   │  Maneja mensajes de texto y audio                │
   │  Flujo de registro de alumnos (5 pasos)          │
   │  Sistema de consentimiento para alertas          │
   │  Detección de palabras inapropiadas              │
   │  Envío del PDF del directorio                    │
   └──────────────────────────────────────────────────┘

3. app.py  —  Panel Web (Flask)
   ┌──────────────────────────────────────────────────┐
   │  Login de psicólogos con bcrypt                  │
   │  Dashboard con estadísticas por facultad         │
   │  Vista de alertas con filtros                    │
   │  Perfiles emocionales de alumnos                 │
   │  Lista de usuarios y perfil individual           │
   │  Generación de reportes PDF (ReportLab)          │
   │  Panel de admin (gestión de psicólogos)          │
   │  Recuperación de contraseña                      │
   └──────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════════
  PAQUETE serenity/
═══════════════════════════════════════════════════════════════════════════════

  serenity/config.py  —  Configuración centralizada
    ├── Rutas: BASE_DIR, TMP_DIR, JSON_PATH, PDF_DIRECTORIO
    ├── Variables de entorno: TOKEN_TELEGRAM, GROQ_API_KEY, OPENAI_API_KEY,
    │                         GMAIL_USER, GMAIL_PASS, TWILIO_*, DATABASE_URL
    ├── Clientes: OpenAI, Twilio
    └── Logger: logging.getLogger("serenity")

  serenity/database.py  —  Base de datos PostgreSQL (Supabase)
    ├── Pool de conexiones con psycopg2
    ├── Funciones CRUD: guardar_usuario, completar_registro,
    │  obtener_datos_usuario, guardar_mensaje, obtener_historial,
    │  registrar_alerta, contar_mensajes_usuario,
    │  registrar_dependencia, registrar_perfil_emocional
    └── Helpers: get_conn, release_conn, execute_query

  serenity/ai_core.py  —  Inteligencia Artificial
    ├── Groq (Llama 3.3 70B) como modelo principal
    ├── OpenAI (GPT-4o mini) como fallback
    ├── System prompt con reglas de comportamiento
    ├── Evaluación de dependencia cada 15 mensajes
    ├── Evaluación de perfil emocional cada 30 mensajes
    └── Respuesta en formato JSON estructurado

  serenity/alertas.py  —  Sistema de alertas
    ├── enviar_correo_alerta: Genera Excel + envía por Gmail SMTP
    └── enviar_whatsapp_emergencia: Mensaje rápido vía Twilio


═══════════════════════════════════════════════════════════════════════════════
  VARIABLES DE ENTORNO (.env)
═══════════════════════════════════════════════════════════════════════════════

  # ── Telegram ──
  TELEGRAM_TOKEN=123456:ABC-DEF...

  # ── IA ──
  GROQ_API_KEY=gsk_...
  OPENAI_API_KEY=sk-...

  # ── Base de datos ──
  DATABASE_URL=postgresql://user:pass@host:5432/db

  # ── Correo (Gmail) ──
  GMAIL_USER=tu-correo@gmail.com
  GMAIL_PASS=xxxx-xxxx-xxxx     # Contraseña de aplicación

  # ── WhatsApp (Twilio) ──
  TWILIO_SID=AC...
  TWILIO_TOKEN=...
  TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
  TWILIO_WHATSAPP_TO=whatsapp:+521938...

  # ── Panel web ──
  SECRET_KEY=genera-con-python-secrets-token_hex-32

  # ── Deploy ──
  WEBHOOK_URL=https://tu-app.onrender.com   # Solo para producción
  PORT=10000                                  # Puerto para Render

  # ── Opcional ──
  COOLDOWN_DIAS_INFO=3


═══════════════════════════════════════════════════════════════════════════════
  INSTALACIÓN Y EJECUCIÓN
═══════════════════════════════════════════════════════════════════════════════

  1. Clonar el repositorio:
     $ git clone https://github.com/tu-usuario/serenity.git
     $ cd serenity

  2. Crear entorno virtual:
     $ python -m venv venv
     $ source venv/bin/activate    # Linux/Mac
     $ venv\Scripts\activate       # Windows

  3. Instalar dependencias:
     $ pip install -r requirements.txt

  4. Configurar el archivo .env:
     $ Copiar las variables de entorno listadas arriba con tus datos reales

  5. Ejecutar en modo local (polling):
     $ python server.py

  6. Ejecutar solo el bot (sin panel web):
     $ python main.py

  7. Ejecutar solo el panel web:
     $ python app.py


═══════════════════════════════════════════════════════════════════════════════
  DEPLOY EN RENDER
═══════════════════════════════════════════════════════════════════════════════

  1. Subir el proyecto a GitHub
  2. Crear un nuevo Web Service en Render
  3. Configurar:
     - Build Command:  pip install -r requirements.txt
     - Start Command:  python server.py
  4. Agregar las variables de entorno en el panel de Render
  5. Configurar WEBHOOK_URL con la URL de Render
  6. Configurar el webhook de Telegram:
     https://api.telegram.org/bot<TOKEN>/setWebhook?url=<WEBHOOK_URL>/<TOKEN>


═══════════════════════════════════════════════════════════════════════════════
  FLUJO DEL BOT
═══════════════════════════════════════════════════════════════════════════════

  1. El alumno envía /start → Saludo de bienvenida
  2. El alumno escribe cómo se siente → La IA responde con empatía
  3. Si la IA detecta riesgo ALTO:
     a. Pregunta si quiere apoyo especializado
     b. Si acepta → Pregunta si quiere compartir sus datos
     c. Si ya está registrado → Notifica al psicólogo directamente
     d. Si no está registrado → Inicia flujo de registro (5 pasos):
        - Nombre completo
        - Matrícula (6 dígitos)
        - Correo institucional
        - Teléfono (10 dígitos)
        - Facultad (botones inline)
     e. Envía alerta por WhatsApp + correo con Excel adjunto
  4. Si el alumno pide explícitamente un psicólogo → Envía el PDF
  5. El alumno puede enviar audio → Se transcribe con Whisper y se procesa


═══════════════════════════════════════════════════════════════════════════════
  DEPENDENCIAS
═══════════════════════════════════════════════════════════════════════════════

  python-telegram-bot    → Bot de Telegram
  python-dotenv          → Variables de entorno
  psycopg2-binary        → PostgreSQL (Supabase)
  groq                   → IA principal (Llama 3.3 70B)
  openai                 → IA fallback (GPT-4o mini) + Whisper (audio)
  flask                  → Panel web para psicólogos
  flask-bcrypt           → Encriptación de contraseñas
  reportlab              → Generación de reportes PDF
  pandas + openpyxl      → Generación de reportes Excel
  twilio                 → Alertas por WhatsApp
  waitress               → Servidor WSGI para producción


═══════════════════════════════════════════════════════════════════════════════
  NOTAS IMPORTANTES
═══════════════════════════════════════════════════════════════════════════════

  - NUNCA subir el archivo .env a GitHub (ya está en .gitignore)
  - La SECRET_KEY del panel web debe generarse con:
    python -c "import secrets; print(secrets.token_hex(32))"
  - Para Gmail, usar una "Contraseña de aplicación" (no la normal)
  - El PDF del directorio debe estar en la raíz del proyecto
  - info.json contiene la información oficial de la USP
  - Las facultades están hardcodeadas en main.py (8 facultades UNACAR)
  - El cooldown de alertas es de 60 minutos por usuario
  - La evaluación de dependencia corre cada 15 mensajes
  - La evaluación de perfil emocional corre cada 30 mensajes


═══════════════════════════════════════════════════════════════════════════════
  CRÉDITOS
═══════════════════════════════════════════════════════════════════════════════

  Proyecto Serenity — UNACAR 2026
  NEGRURAS.
  Unidad de Servicios Psicopedagógicos (USP)
