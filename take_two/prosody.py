"""Pitch and loudness measurements shared by the emphasis check and Improvise.

Pitch uses Praat via parselmouth when installed, else librosa's pyin, else
nothing (callers report pitch measures as unmeasurable). All functions take
timestamps in seconds and return None when there is too little voiced audio
to say anything.
"""

from __future__ import annotations

import logging

import numpy as np

from take_two.audio import rms_db

log = logging.getLogger(__name__)


def f0_track_with_backend(audio: np.ndarray, sr: int):
    """Return ((times, f0_hz) with NaN for unvoiced, backend name), or (None, None)."""
    try:
        import parselmouth

        snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=sr)
        pitch = snd.to_pitch(time_step=0.01, pitch_floor=70, pitch_ceiling=400)
        f0 = pitch.selected_array["frequency"]
        f0 = np.where(f0 == 0, np.nan, f0)
        return (pitch.xs(), f0), "praat"
    except Exception as exc:
        log.info("parselmouth unavailable (%s); trying librosa pyin", exc)
    try:
        import librosa

        f0, _, _ = librosa.pyin(audio, fmin=70, fmax=400, sr=sr, frame_length=1024, hop_length=160)
        times = librosa.times_like(f0, sr=sr, hop_length=160)
        return (times, f0), "librosa-pyin"
    except Exception as exc:
        log.info("librosa pyin unavailable (%s); pitch disabled", exc)
        return None, None


def f0_track(audio: np.ndarray, sr: int):
    return f0_track_with_backend(audio, sr)[0]


def voiced(track, start: float, end: float) -> np.ndarray:
    if track is None:
        return np.zeros(0)
    times, f0 = track
    sel = f0[(times >= start) & (times <= end)]
    return sel[~np.isnan(sel)]


def median_f0(track, start: float, end: float) -> float | None:
    sel = voiced(track, start, end)
    return float(np.median(sel)) if sel.size else None


def semitones(a: float, b: float) -> float:
    return float(12.0 * np.log2(a / b))


def pitch_range_st(track, start: float, end: float, min_frames: int = 20) -> float | None:
    """Spread of voiced pitch (10th to 90th percentile) in semitones. Small = monotone."""
    sel = voiced(track, start, end)
    if sel.size < min_frames:
        return None
    lo, hi = np.percentile(sel, [10, 90])
    return semitones(hi, lo) if lo > 0 else None


def final_rise_st(track, start: float, end: float, min_frames: int = 6) -> float | None:
    """Pitch of the last 40 % of a word's voiced frames against its first 60 %, in semitones.

    Positive means the word ends higher than it started: the rising contour of
    a question, or of "uptalk" when it lands on a statement.
    """
    sel = voiced(track, start, end)
    if sel.size < min_frames:
        return None
    cut = int(round(sel.size * 0.6))
    head, tail = sel[:cut], sel[cut:]
    if not head.size or not tail.size:
        return None
    return semitones(float(np.median(tail)), float(np.median(head)))


def word_db(audio: np.ndarray, sr: int, start: float, end: float) -> float | None:
    return rms_db(audio, sr, start, end)


def contour(track, start: float, end: float, max_points: int = 400) -> list[list[float | None]]:
    """Down-sampled [t, median f0 or None] pairs for drawing a pitch strip."""
    if track is None or end <= start:
        return []
    step = max(0.25, (end - start) / max_points)
    out: list[list[float | None]] = []
    t = start
    while t < end:
        m = median_f0(track, t, t + step)
        out.append([round(t, 2), round(m, 1) if m else None])
        t += step
    return out
