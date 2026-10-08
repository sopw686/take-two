"""Speech-to-text adapters. All return word-level timestamps."""

from __future__ import annotations

from marked import config
from marked.stt.base import Transcriber, Transcript, Word

_instance: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _instance
    if _instance is None:
        if config.STT_BACKEND == "openai" and config.OPENAI_API_KEY:
            from marked.stt.openai_stt import OpenAITranscriber
            _instance = OpenAITranscriber()
        else:
            from marked.stt.faster_whisper_stt import FasterWhisperTranscriber
            _instance = FasterWhisperTranscriber(
                model=config.STT_MODEL, device=config.STT_DEVICE, vad_filter=config.STT_VAD_FILTER)
    return _instance


def audio_leaves_machine() -> bool:
    return config.STT_BACKEND == "openai" and bool(config.OPENAI_API_KEY)


__all__ = ["Transcriber", "Transcript", "Word", "get_transcriber", "audio_leaves_machine"]
