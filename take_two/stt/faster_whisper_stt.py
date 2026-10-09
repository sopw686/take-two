"""Local speech-to-text via faster-whisper (CTranslate2) with word timestamps.

Audio never leaves the machine on this path.
"""

from __future__ import annotations

import logging
import os
import sys
import sysconfig
import threading
from pathlib import Path

import numpy as np

from take_two.stt.base import Transcript, Word

log = logging.getLogger(__name__)
_CUDA_DLLS_ADDED = False


def _add_cuda_dll_dirs() -> None:
    """Make pip-installed cuBLAS/cuDNN visible to CTranslate2 on Windows.

    Both os.add_dll_directory and a PATH prepend are needed: CTranslate2 loads
    cuBLAS lazily on the first matmul via a plain LoadLibrary that only searches
    PATH. With only add_dll_directory the model loads, then the first transcription
    fails (or hangs inside a generator). Pattern borrowed from a sibling project
    where it was measured.
    """
    global _CUDA_DLLS_ADDED
    if _CUDA_DLLS_ADDED or sys.platform != "win32":
        return
    roots = {Path(sysconfig.get_paths()["purelib"]), Path(sysconfig.get_paths()["platlib"])}
    for root in roots:
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_runtime/bin"):
            path = root / sub
            if not path.is_dir():
                continue
            try:
                os.add_dll_directory(str(path))
            except OSError:
                pass
            current = os.environ.get("PATH", "")
            if str(path) not in current:
                os.environ["PATH"] = str(path) + os.pathsep + current
    _CUDA_DLLS_ADDED = True


def cuda_available() -> bool:
    _add_cuda_dll_dirs()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str = "small.en", device: str = "auto", vad_filter: bool = True):
        self.model_name = model
        self.requested_device = device
        self.device = device
        self.compute_type = "float16"
        self.vad_filter = vad_filter
        self._model = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()  # startup warm-up and the first take can race to load

    def _resolve(self) -> None:
        dev = self.requested_device
        if dev == "auto":
            dev = "cuda" if cuda_available() else "cpu"
        self.device = dev
        self.compute_type = "float16" if dev == "cuda" else "int8"

    def load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            _add_cuda_dll_dirs()
            from faster_whisper import WhisperModel

            self._resolve()
            try:
                model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
                if self.device == "cuda":
                    # Force the lazy cuBLAS load now so a broken CUDA setup fails here, not mid-request.
                    segs, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language="en", beam_size=1,
                                               vad_filter=False)
                    list(segs)
            except Exception as exc:  # GPU init failure: fall back to CPU rather than refuse to run
                if self.device != "cpu":
                    log.warning("CUDA unavailable for faster-whisper (%s); falling back to CPU int8", exc)
                    self.device, self.compute_type = "cpu", "int8"
                    model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
                else:
                    raise
            self._model = model

    def describe(self) -> dict:
        return {"backend": self.name, "model": self.model_name, "device": self.device,
                "compute_type": self.compute_type, "loaded": self._model is not None, "local": True}

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000, initial_prompt: str | None = None) -> Transcript:
        self.load()
        assert self._model is not None
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language="en",
                beam_size=5,
                word_timestamps=True,
                vad_filter=self.vad_filter,
                vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200} if self.vad_filter else None,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
            )
            words: list[Word] = []
            texts: list[str] = []
            for seg in segments:
                texts.append(seg.text.strip())
                for w in seg.words or []:
                    words.append(Word(text=w.word.strip(), start=float(w.start), end=float(w.end),
                                      prob=float(w.probability)))
        return Transcript(words=words, text=" ".join(t for t in texts if t), backend=self.name,
                          model=self.model_name, device=f"{self.device}/{self.compute_type}",
                          duration_s=len(audio) / sample_rate)
