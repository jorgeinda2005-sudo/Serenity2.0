"""Conector de texto para Messenger Platform."""

import hashlib
import hmac
import os

import httpx

from .config import logger
from .database import obtener_o_crear_usuario_canal, reclamar_evento_canal


def validar_firma_meta(raw_body, signature):
    app_secret = os.getenv("MESSENGER_APP_SECRET", "")
    if not app_secret or not signature or not signature.startswith("sha256="):
        return False
    esperado = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperado, signature)


def enviar_texto(psid, texto):
    token = os.getenv("MESSENGER_PAGE_ACCESS_TOKEN", "")
    page_id = os.getenv("MESSENGER_PAGE_ID", "")
    version = os.getenv("MESSENGER_GRAPH_API_VERSION", "")
    if not token or not page_id or not version:
        raise RuntimeError(
            "Configura MESSENGER_PAGE_ACCESS_TOKEN, MESSENGER_PAGE_ID y "
            "MESSENGER_GRAPH_API_VERSION."
        )

    response = httpx.post(
        f"https://graph.facebook.com/{version}/{page_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "recipient": {"id": str(psid)},
            "messaging_type": "RESPONSE",
            "message": {"text": texto[:2000]},
        },
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


async def procesar_webhook(payload):
    """Procesa eventos entrantes de texto; los ecos y duplicados se ignoran."""
    if payload.get("object") != "page":
        return

    from .ai_core import obtener_respuesta_ia

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender = event.get("sender") or {}
            psid = sender.get("id")
            text = (message.get("text") or "").strip()
            message_id = message.get("mid")

            if not psid or not text or message.get("is_echo"):
                continue
            if message_id and not reclamar_evento_canal("messenger", message_id):
                continue

            try:
                internal_id = obtener_o_crear_usuario_canal("messenger", psid)
                if text.lower() in {"hola", "iniciar", "start", "/start"}:
                    reply = (
                        "Hola, soy Serenity, un espacio de acompañamiento emocional de la UNACAR. "
                        "Puedes contarme cómo te sientes. Los mensajes se guardan para mantener "
                        "el contexto; si se detecta riesgo, la alerta puede ser revisada por el "
                        "equipo de la USP. Evita compartir datos que no quieras incluir. "
                        "Este canal no sustituye atención profesional. Si estás en peligro "
                        "inmediato, llama a emergencias de tu localidad o busca ahora a una "
                        "persona de confianza."
                    )
                elif text.lower() in {"menu", "/menu"}:
                    reply = (
                        "Puedes escribirme cómo te sientes o qué está pasando. "
                        "Este canal permite mensajes de texto por ahora."
                    )
                else:
                    result = await obtener_respuesta_ia(internal_id, text)
                    reply = result.get("respuesta") or (
                        "Tuve un problema procesando el mensaje. Inténtalo de nuevo en un momento."
                    )
                    if result.get("nivel_riesgo") == "alto":
                        reply += (
                            "\n\nSi estás en peligro inmediato o podrías hacerte daño, "
                            "llama a emergencias de tu localidad y busca a alguien que pueda "
                            "acompañarte ahora."
                        )
                enviar_texto(psid, reply)
            except Exception:
                logger.exception("Error procesando mensaje de Messenger")
                # Evita revelar detalles internos y permite que la persona vuelva a intentarlo.
                try:
                    enviar_texto(
                        psid,
                        "Tuve un problema técnico al recibir tu mensaje. "
                        "Por favor, inténtalo de nuevo en un momento.",
                    )
                except Exception:
                    logger.exception("No se pudo responder al usuario de Messenger")
