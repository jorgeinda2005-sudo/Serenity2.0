import json
import re
import requests
from config import logger
from database import guardar_mensaje, obtener_historial, registrar_alerta

# Dirección de tu cerebro local
OLLAMA_URL = "http://localhost:11434/api/chat"

def extraer_json(texto):
    """Mantiene tu lógica original de limpieza."""
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    return match.group(0) if match else texto

async def obtener_respuesta_ia(user_id, mensaje_usuario):
    """Cambio exclusivo de MLL a Llama 3.1 local."""
    historial_previo = obtener_historial(user_id, limite=10)
    
    system_prompt = (
        "Eres Serenity, un acompañante emocional para estudiantes de la UNACAR. "
        "Responde SIEMPRE en formato JSON con esta estructura exacta: "
        '{"respuesta": "tu mensaje empático", "nivel_riesgo": "bajo/medio/alto", '
        '"tema": "tema detectado", "razon": "por qué ese riesgo", "dependencia": boolean}'
    )

    # Cuerpo de la petición para Ollama manteniendo tus parámetros
    payload = {
        "model": "llama3.1", 
        "messages": [
            {"role": "system", "content": system_prompt},
            *historial_previo,
            {"role": "user", "content": mensaje_usuario}
        ],
        "stream": False,
        "format": "json"
    }

    try:
        # Petición al motor que corre en tu 4060
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        
        resultado = response.json()
        contenido = resultado['message']['content']
        data = json.loads(extraer_json(contenido))
        
        guardar_mensaje(user_id, "user", mensaje_usuario)
        guardar_mensaje(user_id, "assistant", data["respuesta"])
        
        if data["nivel_riesgo"] in ["medio", "alto"]:
            registrar_alerta(user_id, data["nivel_riesgo"], data["tema"], data["razon"])
            
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