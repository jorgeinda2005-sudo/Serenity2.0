import json
import re
from groq import Groq
from openai import OpenAI
from config import logger
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

system_prompt = (
    "Eres Serenity, un acompañante emocional para estudiantes de la UNACAR. "
    "Responde SIEMPRE en formato JSON con esta estructura exacta: "
    '{"respuesta": "tu mensaje empático", "nivel_riesgo": "bajo/medio/alto", '
    '"tema": "tema detectado", "razon": "por qué ese riesgo", "dependencia": false}'
)

    # Convertir el historial al formato que requiere la API llamando primero a llama y despues a GPT
def llamar_groq(mensajes):
    """Intento principal con Groq - Llama 3.3 70B."""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=mensajes,
        temperature=0.7,
        max_tokens=1024,
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

def llamar_openai(mensajes):
    """Fallback con OpenAI - GPT-4o mini."""
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=mensajes,
        temperature=0.7,
        max_tokens=1024,
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
                "dependencia": False
            }

    try:
        data = json.loads(extraer_json(contenido))
        logger.info(f"Respuesta generada con {modelo_usado}")

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
            "dependencia": False
        }