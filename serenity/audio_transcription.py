import asyncio
import os
from pathlib import Path

from groq import Groq

from .config import GROQ_API_KEY, TMP_DIR, logger


MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "8"))
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024
MAX_AUDIO_SECONDS = int(os.getenv("MAX_AUDIO_SECONDS", "300"))
TRANSCRIPTION_MODEL = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo")


class AudioTranscriptionError(Exception):
    def __init__(self, user_message, log_message=None):
        super().__init__(log_message or user_message)
        self.user_message = user_message


def _audio_payload(message):
    audio = message.voice or message.audio
    if not audio:
        raise AudioTranscriptionError("No encontre un audio valido para transcribir.")
    return audio


def _validar_audio(audio):
    file_size = getattr(audio, "file_size", None)
    duration = getattr(audio, "duration", None)

    if file_size and file_size > MAX_AUDIO_BYTES:
        raise AudioTranscriptionError(
            f"El audio pesa mas de {MAX_AUDIO_MB} MB. Enviame uno mas corto, por favor."
        )

    if duration and duration > MAX_AUDIO_SECONDS:
        minutos = MAX_AUDIO_SECONDS // 60
        raise AudioTranscriptionError(
            f"El audio dura mas de {minutos} minutos. Enviame uno mas corto, por favor."
        )


def _ruta_temporal(user_id, file_id, mime_type):
    extension = ".ogg"
    if mime_type:
        if "mpeg" in mime_type or "mp3" in mime_type:
            extension = ".mp3"
        elif "wav" in mime_type:
            extension = ".wav"
        elif "mp4" in mime_type or "m4a" in mime_type:
            extension = ".m4a"

    safe_file_id = "".join(ch for ch in file_id if ch.isalnum() or ch in ("_", "-"))
    return Path(TMP_DIR) / f"{user_id}_{safe_file_id}{extension}"


def _transcribir_con_groq(ruta_audio):
    if not GROQ_API_KEY:
        raise AudioTranscriptionError(
            "La transcripcion de audio no esta configurada en el servidor.",
            "GROQ_API_KEY no configurada.",
        )

    client = Groq(api_key=GROQ_API_KEY)
    with open(ruta_audio, "rb") as audio_file:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(ruta_audio), audio_file.read()),
            model=TRANSCRIPTION_MODEL,
            response_format="text",
        )

    texto = str(result or "").strip()
    if not texto:
        raise AudioTranscriptionError("No pude detectar texto claro en el audio.")
    return texto


async def transcribir_audio_telegram(message, user_id):
    """
    Descarga un audio de Telegram, lo transcribe con Groq Whisper y borra el
    archivo temporal. Pensado para Render Starter: usa limites pequenos y no
    bloquea el event loop mientras espera a Groq.
    """
    audio = _audio_payload(message)
    _validar_audio(audio)

    telegram_file = await audio.get_file()
    ruta_audio = _ruta_temporal(
        user_id=user_id,
        file_id=telegram_file.file_id,
        mime_type=getattr(audio, "mime_type", ""),
    )

    try:
        await telegram_file.download_to_drive(str(ruta_audio))

        if ruta_audio.stat().st_size > MAX_AUDIO_BYTES:
            raise AudioTranscriptionError(
                f"El audio pesa mas de {MAX_AUDIO_MB} MB. Enviame uno mas corto, por favor."
            )

        return await asyncio.to_thread(_transcribir_con_groq, str(ruta_audio))
    except AudioTranscriptionError:
        raise
    except Exception as exc:
        logger.error(f"Error transcribiendo audio con Groq: {exc}")
        raise AudioTranscriptionError(
            "Tuve problemas escuchando el audio. Podrias escribirlo, por favor?",
            str(exc),
        ) from exc
    finally:
        try:
            if ruta_audio.exists():
                ruta_audio.unlink()
        except Exception as exc:
            logger.warning(f"No se pudo borrar audio temporal {ruta_audio}: {exc}")
