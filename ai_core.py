import json
import re
from groq import Groq
from openai import OpenAI
from config import logger, JSON_PATH
from database import guardar_mensaje, obtener_historial, registrar_alerta
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

Cuando el usuario solo saluda (hola, hey, buenas, etc), responde ÚNICAMENTE con un saludo \
cálido y una pregunta abierta como: "Hola, ¿cómo estás? Estoy aquí para ti." \
NUNCA menciones psicólogos, directorio ni servicios de la USP a menos que: \
1) El usuario lo pida explícitamente, o \
2) Detectes señales claras de malestar emocional en su mensaje. \
Primero escucha, luego orienta. Sé natural, no un folleto informativo.
 
── INFORMACIÓN OFICIAL DE LA USP ──
{INFO_USP}
 
── DIRECTORIO DE PSICÓLOGOS ──
{DIRECTORIO_PSICOLOGOS}
 
── REGLAS CLAVE ──
1. Responde SIEMPRE en formato JSON con la estructura exacta indicada abajo.
2. Usa la información del directorio cuando el usuario pregunte por psicólogos, orientación, \
apoyo emocional, citas, servicios o cualquier intención similar (aunque no lo pida con palabras exactas). \
Ejemplos de frases que DEBEN activar el directorio:
   - "quiero hablar con alguien", "necesito ayuda profesional", "¿hay psicólogos?",
   - "me siento mal y quiero apoyo", "¿a quién puedo acudir?", "tengo problemas y no sé qué hacer",
   - "¿cómo pido cita?", "servicios de la universidad", "orientación psicológica".
3. Cuando compartas el directorio en tu respuesta, menciona que también enviarás el PDF oficial.
4. Pon "enviar_directorio": true SOLO cuando el usuario claramente quiere información sobre \
psicólogos/orientadores/servicios de la USP. En cualquier otro caso ponlo en false.
5. Sé cálido, empático y nunca robótico.
 
── ESTRUCTURA JSON OBLIGATORIA ──
{{
  "respuesta": "tu mensaje empático y completo",
  "nivel_riesgo": "bajo | medio | alto",
  "tema": "tema detectado",
  "razon": "por qué ese nivel de riesgo",
  "dependencia": false,
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
    historial_previo = obtener_historial(user_id, limite=10)
 
    mensajes = [
        {"role": "system", "content": system_prompt},
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
                "dependencia": False,
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
            registrar_alerta(user_id, data["nivel_riesgo"], data["tema"], data["razon"])
 
        return data
 
    except Exception as e:
        logger.error(f"Error procesando respuesta de {modelo_usado}: {e}")
        return {
            "respuesta": "Lo siento, tuve un pequeño problema técnico. Pero aquí estoy para escucharte.",
            "nivel_riesgo": "bajo",
            "tema": "error",
            "razon": str(e),
            "dependencia": False,
            "enviar_directorio": False
        }