"""Audio decoding and silence detection.

Silence regions come from Silero VAD (bundled with faster-whisper, runs on
onnxruntime, no torch). An RMS-energy detector is the fallback if VAD cannot
run. Pause measurements in the analysis use these regions, not Whisper's word
gaps, which smear across silences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)
SR = 16000


@dataclass
class Silence:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2


def load_audio(path: str | Path, sample_rate: int = SR) -> np.ndarray:
    """Decode any container the browser or a user might upload (webm/opus, ogg, wav, m4a, mp3)."""
    import av  # PyAV bundles FFmpeg; no system ffmpeg needed

    resampler = av.AudioResampler(format="s16", layout="mono", rate=sample_rate)
    chunks: list[np.ndarray] = []
    with av.open(str(path), mode="r") as container:
        stream = next(s for s in container.streams if s.type == "audio")
        stream.thread_type = "AUTO"
        for frame in container.decode(stream):
            frame.pts = None
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    pcm = np.concatenate(chunks).astype(np.float32)
    return pcm / 32768.0


def save_wav(path: str | Path, audio: np.ndarray, sample_rate: int = SR) -> None:
    sf.write(str(path), audio, sample_rate, subtype="PCM_16")


def silence_regions(audio: np.ndarray, sample_rate: int = SR, min_silence_s: float = 0.15) -> tuple[list[Silence], str]:
    """Return (silences, method). Silences shorter than min_silence_s are dropped."""
    duration = len(audio) / sample_rate
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        opts = VadOptions(threshold=0.5, min_speech_duration_ms=80,
                          min_silence_duration_ms=int(min_silence_s * 1000), speech_pad_ms=30)
        speech = get_speech_timestamps(audio, opts, sampling_rate=sample_rate)
        regions = [(s["start"] / sample_rate, s["end"] / sample_rate) for s in speech]
        method = "silero-vad"
    except Exception as exc:
        log.warning("Silero VAD unavailable (%s); using RMS energy fallback", exc)
        regions = rms_speech_regions(audio, sample_rate)
        method = "rms-energy"
    silences: list[Silence] = []
    cursor = 0.0
    for s, e in regions:
        if s - cursor >= min_silence_s:
            silences.append(Silence(round(cursor, 3), round(s, 3)))
        cursor = max(cursor, e)
    if duration - cursor >= min_silence_s:
        silences.append(Silence(round(cursor, 3), round(duration, 3)))
    return silences, method


def rms_speech_regions(audio: np.ndarray, sample_rate: int = SR, frame_ms: int = 20,
                       floor_db: float = -45.0, margin_db: float = 10.0) -> list[tuple[float, float]]:
    """Energy-based speech regions: frames louder than max(floor, noise floor + margin)."""
    n = int(sample_rate * frame_ms / 1000)
    if len(audio) < n:
        return []
    frames = len(audio) // n
    x = audio[: frames * n].reshape(frames, n)
    rms = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    noise = np.percentile(db, 10)
    thresh = max(floor_db, noise + margin_db)
    speech = db > thresh
    regions: list[tuple[float, float]] = []
    start = None
    for i, v in enumerate(speech):
        t = i * frame_ms / 1000
        if v and start is None:
            start = t
        elif not v and start is not None:
            regions.append((start, t))
            start = None
    if start is not None:
        regions.append((start, frames * frame_ms / 1000))
    return regions


def longest_silence_between(silences: list[Silence], t0: float, t1: float) -> float:
    """Longest silence whose midpoint lies in [t0, t1]. 0.0 if none."""
    if t1 < t0:
        t0, t1 = t1, t0
    best = 0.0
    for s in silences:
        if t0 <= s.mid <= t1:
            best = max(best, s.duration)
    return best


def rms_db(audio: np.ndarray, sample_rate: int, start: float, end: float) -> float | None:
    a, b = int(max(0, start) * sample_rate), int(min(len(audio) / sample_rate, end) * sample_rate)
    if b - a < 16:
        return None
    seg = audio[a:b]
    return float(20 * np.log10(np.sqrt(np.mean(seg * seg)) + 1e-9))
