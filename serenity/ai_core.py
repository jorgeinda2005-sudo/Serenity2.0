import json
import re
from groq import Groq
from openai import OpenAI
from .config import logger, JSON_PATH
from .database import guardar_mensaje, obtener_historial, registrar_alerta, registrar_contexto_alerta
import os
from dotenv import load_dotenv

load_dotenv()

# Clientes
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extraer_json(texto):
    """Mantiene tu lógica original de limpieza."""
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    return match.group(0) if match else texto

# ── Cargar info.json una sola vez al iniciar ───────────────────────────────────
try:
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        _info = json.load(f)
    INFO_USP = json.dumps(_info, ensure_ascii=False, indent=2)
except Exception as e:
    logger.warning(f"No se pudo cargar info.json: {e}")
    INFO_USP = "{}"

# ── Directorio completo de psicólogos (extraído del PDF) ──────────────────────
DIRECTORIO_PSICOLOGOS = """
UNIDAD DE SERVICIOS PSICOPEDAGÓGICOS (USP) — UNACAR 2026

TITULAR:
- María del Carmen Duarte Cardel | Pedagoga (administrativa)
  Correo: mduarte@delfin.unacar.mx | Campus I | Lun-Vie 7:00-16:00
  Cita: vía correo institucional

CAMPUS I — PSICÓLOGAS ORIENTADORAS:

1. Celia María Ramos Massa | Psicóloga
   Correo: crmassa@pampano.unacar.mx
   Facultades: Ciencias de la Información, Ciencias Económico-Administrativas
   Horario: Lun-Jue 7:00-14:30 | Modalidad: Presencial
   Cita: correo institucional, tutor/a, presencial en USP o asistente virtual
   (Enviar horario de clases al escribir por correo)

2. Rossana Karina Carrillo Sanguino | Psicóloga
   Correo: rcarrillo@delfin.unacar.mx
   Facultades: Derecho, Ciencias Educativas, Química
   Horario: Lun-Jue 9:00-17:00 | Modalidad: Presencial
   Cita: correo institucional, tutor/a, presencial en USP o asistente virtual

CAMPUS III — PSICÓLOGOS ORIENTADORES:

3. Gilberto Franco Basto | Psicólogo Clínico
   Correo: gfranco@delfin.unacar.mx
   Facultades: Ingeniería y Arquitectura, Ciencias Naturales
   Horario: Lun-Jue 9:00-17:00 | Modalidad: Presencial y en línea
   Cita: correo institucional, tutor/a, presencial en USP o asistente virtual

4. Jovanna Janely Martínez Caballero | Psicóloga Clínica
   Correo: jcaballero@delfin.unacar.mx
   Facultades: Ciencias de la Salud
   Horario: Lun-Jue 9:00-17:00 | Modalidad: Presencial y en línea
   Cita: correo institucional, tutor/a, presencial en USP o asistente virtual

SERVICIOS QUE OFRECE LA USP:
- Atención psicológica individual
- Contención en crisis emocional
- Programa de Ajuste Vocacional (cambio de carrera)
- Canalización a servicios externos (CIJ, DIF, OUVS)
- Seguimiento psicológico
- Talleres psicológicos y educativos
- Asesoramiento académico-emocional

UBICACIÓN: Campus Principal, Plaza Cultural Universitaria, puerta 204
HORARIO GENERAL: Lun-Vie 9:00-14:00 y 16:00-19:00
"""

# ── System prompt ──────────────────────────────────────────────────────────────
system_prompt = f"""Eres Serenity, un acompañante emocional para estudiantes de la UNACAR (Universidad Autónoma del Carmen).

Tu rol es escuchar con empatía, detectar señales de malestar emocional y orientar a los estudiantes \
cuando lo necesiten. Tienes acceso al directorio real de la USP y debes usarlo siempre que sea relevante.

NUNCA menciones psicólogos, directorio ni servicios de la USP a menos que: \
1) El usuario lo pida EXPLÍCITAMENTE con frases como "quiero un psicólogo", "necesito ayuda profesional", "¿hay orientación?", "¿con quién puedo hablar?", o \
2) El usuario exprese una crisis severa como ideación suicida o autolesiones. \
Si el usuario expresa estrés, soledad, cansancio, tristeza o desmotivación, PRIMERO responde con empatía y escucha activa. \
Pregúntale cómo se siente, qué está viviendo. NO menciones la USP ni psicólogos todavía. \
Pon "enviar_directorio": false en estos casos. \
Solo cuando el usuario pida explícitamente apoyo profesional, activa el directorio.

── INFORMACIÓN OFICIAL DE LA USP ──
{INFO_USP}

── DIRECTORIO DE PSICÓLOGOS ──
{DIRECTORIO_PSICOLOGOS}

── REGLAS CLAVE ──
1. Responde SIEMPRE en formato JSON con la estructura exacta indicada abajo.
2. ESCUCHA PRIMERO. Si el usuario expresa estrés, soledad, tristeza, cansancio o desmotivación, \
responde con empatía y escucha activa. Pregúntale cómo se siente. NO menciones psicólogos ni la USP todavía.
3. Activa el directorio (enviar_directorio: true) SOLO cuando el usuario pida EXPLÍCITAMENTE \
hablar con alguien, pida orientación profesional, o pregunte por servicios de la universidad. \
Frases que SÍ activan el directorio: "¿hay psicólogos?", "¿con quién puedo hablar?", \
"necesito ayuda profesional", "¿cómo pido cita?", "quiero orientación".
4. Frases que NO activan el directorio: "me siento solo", "estoy estresado", "tengo problemas", \
"ya no sé qué hacer", "estoy cansado". Para estas, solo escucha y acompaña.
5. NIVEL DE RIESGO — úsalo con criterio estricto: \
"alto" SOLO para ideación suicida, autolesiones o peligro inmediato. \
"medio" para tristeza persistente, aislamiento severo o desesperanza prolongada. \
"bajo" para estrés académico, cansancio, problemas cotidianos. \
NO uses "alto" solo porque alguien esté triste o agobiado.
6. Sé cálido, empático y nunca robótico.
7. LÍMITE DE TEMA: Tu único propósito es el bienestar emocional. Si el usuario te hace preguntas académicas (matemáticas, programación, historia, etc.) o de cualquier tema ajeno a la psicología, declina amablemente la solicitud y recuérdale que eres exclusivamente un espacio de apoyo emocional.

── ESTRUCTURA JSON OBLIGATORIA ──
{{
  "respuesta": "tu mensaje empático y completo",
  "nivel_riesgo": "bajo | medio | alto",
  "tema": "suicidio | depresión | violencia | abuso | otro",
  "razon": "por qué ese nivel de riesgo",
  "dependencia": "bajo | medio | alto | ninguno",
  "reporte_dependencia": "breve resumen de 2 líneas sobre el apego (o vacío si no se evalúa)",
  "perfil_emocional": "análisis psicológico profundo del estado actual del alumno (vacio si no toca evaluar)",
  "enviar_directorio": false
}}"""


def llamar_groq(mensajes):
    """Intento principal con Groq - Llama 3.3 70B."""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=mensajes,
        temperature=0.7,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

def llamar_openai(mensajes):
    """Fallback con OpenAI - GPT-4o mini."""
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=mensajes,
        temperature=0.7,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

async def obtener_respuesta_ia(user_id, mensaje_usuario):
    """Llama a Groq primero, si falla cae a OpenAI automáticamente."""
    from .database import contar_mensajes_usuario, registrar_dependencia, registrar_perfil_emocional

    historial_previo = obtener_historial(user_id, limite=10)

    # Lógica de evaluación
    num_mensajes = contar_mensajes_usuario(user_id)
    evaluar_dependencia = (num_mensajes + 1) % 15 == 0
    evaluar_perfil = (num_mensajes + 1) % 30 == 0

    prompt_adicional = ""
    if evaluar_perfil:
        prompt_adicional = "\n¡AVISO CRÍTICO!: El usuario llegó a 30 mensajes. DEBES redactar un 'perfil_emocional' profundo (mínimo 3 líneas) analizando su evolución psicológica y estado actual."
    elif evaluar_dependencia:
        prompt_adicional = "\nNOTA: Evalúa el nivel de 'dependencia' emocional y escribe el 'reporte_dependencia'."

    mensajes = [
        {"role": "system", "content": system_prompt + prompt_adicional},
        *historial_previo,
        {"role": "user", "content": mensaje_usuario}
    ]

    contenido = None
    modelo_usado = None

    # --- Intento 1: Groq ---
    try:
        contenido = llamar_groq(mensajes)
        modelo_usado = "Groq (Llama 3.3 70B)"
    except Exception as e:
        logger.warning(f"Groq falló, cambiando a OpenAI. Motivo: {e}")

        # --- Intento 2: OpenAI ---
        try:
            contenido = llamar_openai(mensajes)
            modelo_usado = "OpenAI (GPT-4o mini)"
        except Exception as e2:
            logger.error(f"OpenAI también falló: {e2}")
            return {
                "respuesta": "Lo siento, tuve un pequeño problema técnico. Pero aquí estoy para escucharte.",
                "nivel_riesgo": "bajo",
                "tema": "error",
                "razon": str(e2),
                "dependencia": "ninguno",
                "reporte_dependencia": "",
                "perfil_emocional": "",
                "enviar_directorio": False
            }

    try:
        data = json.loads(extraer_json(contenido))
        logger.info(f"Respuesta generada con {modelo_usado}")

        # Asegurar que el campo siempre exista aunque el modelo lo omita
        data.setdefault("enviar_directorio", False)

        # Guardar en base de datos
        guardar_mensaje(user_id, "user", mensaje_usuario)
        guardar_mensaje(user_id, "assistant", data["respuesta"])

        # Registrar alerta si es necesario
        if data["nivel_riesgo"] in ["medio", "alto"]:
            alerta_id = registrar_alerta(user_id, data["nivel_riesgo"], data["tema"], data["razon"])
            if alerta_id:
                registrar_contexto_alerta(alerta_id, user_id)

        # Registrar dependencia si se evaluó y detectó
        if evaluar_dependencia and data.get("dependencia") and data["dependencia"] != "ninguno":
            reporte = data.get("reporte_dependencia", "Sin detalles adicionales.")
            registrar_dependencia(user_id, data["dependencia"], reporte)

        # Registrar Perfil Emocional (cada 30 mensajes)
        if evaluar_perfil:
            perfil = (data.get("perfil_emocional") or "").strip()
            if not perfil:
                # Fallback: evita perder el corte de 30 mensajes si el modelo omite el campo.
                perfil = (
                    "Perfil emocional de respaldo: se detecta malestar relevante en el alumno. "
                    f"Riesgo reportado: {data.get('nivel_riesgo', 'bajo')}. "
                    f"Tema principal: {data.get('tema', 'otro')}. "
                    f"Motivo observado: {data.get('razon', 'sin detalle')}. "
                    "Se recomienda seguimiento cercano y reevaluacion clinica en la siguiente sesion."
                )
            registrar_perfil_emocional(user_id, perfil)
            data["perfil_emocional"] = perfil

        return data

    except Exception as e:
        logger.error(f"Error procesando respuesta de {modelo_usado}: {e}")
        return {
            "respuesta": "Lo siento, tuve un pequeño problema técnico. Pero aquí estoy para escucharte.",
            "nivel_riesgo": "bajo",
            "tema": "error",
            "razon": str(e),
            "dependencia": "ninguno",
            "reporte_dependencia": "",
            "perfil_emocional": "",
            "enviar_directorio": False
        }
