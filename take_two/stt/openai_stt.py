"""Optional cloud adapter: OpenAI Whisper API with word-level timestamps.

Only used when TAKE_TWO_STT=openai and OPENAI_API_KEY is set. The UI says so.
Not exercised in automated tests (no key in CI); see TESTING.md.
"""

from __future__ import annotations

import io

import numpy as np
import soundfile as sf

from take_two import config
from take_two.stt.base import Transcript, Word


class OpenAITranscriber:
    name = "openai-whisper-api"

    def __init__(self, model: str = "whisper-1"):
        self.model_name = model
        self.device = "cloud"

    def describe(self) -> dict:
        return {"backend": self.name, "model": self.model_name, "device": "cloud", "loaded": True, "local": False}

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, initial_prompt: str | None = None) -> Transcript:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        buf.name = "take.wav"
        resp = client.audio.transcriptions.create(
            model=self.model_name,
            file=buf,
            response_format="verbose_json",
            timestamp_granularities=["word"],
            prompt=initial_prompt or None,
        )
        words = [Word(text=w.word.strip(), start=float(w.start), end=float(w.end)) for w in (resp.words or [])]
        return Transcript(words=words, text=resp.text or "", backend=self.name, model=self.model_name,
                          device="cloud", duration_s=len(audio) / sample_rate)
