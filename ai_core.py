import json
import re
from openai import AsyncOpenAI
from config import logger, GROQ_API_KEY
from database import guardar_mensaje, obtener_historial, registrar_alerta

# Cliente de Groq para usar Llama 3.1 70B y Whisper
groq_client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

def extraer_json(texto):
    """Mantiene tu lógica original de limpieza."""
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    return match.group(0) if match else texto

async def obtener_respuesta_ia(user_id, mensaje_usuario):
    """Cambio a Llama 3.1 70B mediante la API de Groq."""
    historial_previo = obtener_historial(user_id, limite=10)
    
    system_prompt = (
        "Eres Serenity, un acompañante emocional para estudiantes de la UNACAR. "
        "Responde SIEMPRE en formato JSON con esta estructura exacta: "
        '{"respuesta": "tu mensaje empático", "nivel_riesgo": "bajo/medio/alto", '
        '"tema": "tema detectado", "razon": "por qué ese riesgo", "dependencia": boolean}'
    )

    # Convertir el historial al formato que requiere la API
    mensajes_api = [{"role": "system", "content": system_prompt}]
    for msg in historial_previo:
        mensajes_api.append({"role": msg["role"], "content": msg["content"]})
    
    mensajes_api.append({"role": "user", "content": mensaje_usuario})

    try:
        # Petición a Groq
        response = await groq_client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=mensajes_api,
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        
        contenido = response.choices[0].message.content
        data = json.loads(extraer_json(contenido))
        
        # Guardar en base de datos
        guardar_mensaje(user_id, "user", mensaje_usuario)
        guardar_mensaje(user_id, "assistant", data["respuesta"])
        
        # Registrar alerta si es necesario
        if data.get("nivel_riesgo") in ["medio", "alto"]:
            registrar_alerta(user_id, data.get("nivel_riesgo"), data.get("tema"), data.get("razon"))
            
        return data

    except Exception as e:
        logger.error(f"Error en AI Core: {e}")
        return {
            "respuesta": "Lo siento, tuve un pequeño problema técnico. Pero aquí estoy para escucharte.",
            "nivel_riesgo": "bajo",
            "tema": "error",
            "razon": str(e),
            "dependencia": False
        }