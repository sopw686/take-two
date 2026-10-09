from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float = 1.0


@dataclass
class Transcript:
    words: list[Word]
    text: str
    backend: str
    model: str
    device: str = ""
    duration_s: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "words": [{"i": i, **asdict(w)} for i, w in enumerate(self.words)],
            "backend": self.backend,
            "model": self.model,
            "device": self.device,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            words=[Word(text=w["text"], start=float(w["start"]), end=float(w["end"]), prob=float(w.get("prob", 1.0)))
                   for w in d.get("words", [])],
            text=d.get("text", ""),
            backend=d.get("backend", ""),
            model=d.get("model", ""),
            device=d.get("device", ""),
            duration_s=float(d.get("duration_s", 0.0)),
        )


class Transcriber(Protocol):
    name: str

    def describe(self) -> dict: ...

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, initial_prompt: str | None = None) -> Transcript: ...
