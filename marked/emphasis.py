"""Experimental *word* emphasis check.

Compares a marked word's loudness (RMS dB) and pitch (median F0) with the
median of the other words in its line. Uses Praat via parselmouth when
installed, else librosa, else loudness only from numpy. Labelled experimental
in the UI; sensitive to microphone distance and to timestamp drift.
"""

from __future__ import annotations

import logging
from statistics import median

import numpy as np

from marked.audio import rms_db
from marked.marks import Script

log = logging.getLogger(__name__)
EMPH_DB = 3.0      # at least this much louder than the line's median
EMPH_F0_PCT = 10.0  # or at least this much higher in pitch


def _f0_track(audio: np.ndarray, sr: int):
    """Return (times, f0_hz) with NaN for unvoiced, or None if no pitch backend."""
    try:
        import parselmouth

        snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=sr)
        pitch = snd.to_pitch(time_step=0.01, pitch_floor=70, pitch_ceiling=400)
        f0 = pitch.selected_array["frequency"]
        f0 = np.where(f0 == 0, np.nan, f0)
        return pitch.xs(), f0
    except Exception as exc:
        log.info("parselmouth unavailable (%s); trying librosa pyin", exc)
    try:
        import librosa

        f0, _, _ = librosa.pyin(audio, fmin=70, fmax=400, sr=sr, frame_length=1024, hop_length=160)
        times = librosa.times_like(f0, sr=sr, hop_length=160)
        return times, f0
    except Exception as exc:
        log.info("librosa pyin unavailable (%s); pitch disabled", exc)
        return None


def _median_f0(track, start: float, end: float) -> float | None:
    if track is None:
        return None
    times, f0 = track
    sel = f0[(times >= start) & (times <= end)]
    sel = sel[~np.isnan(sel)]
    return float(np.median(sel)) if sel.size else None


def emphasis_report(script: Script, analysis: dict, audio: np.ndarray, sr: int) -> list[dict]:
    rows: list[dict] = []
    marked = [(ln, wi) for ln in script.lines for wi in ln.emphasis]
    if not marked:
        return rows
    track = _f0_track(audio, sr)
    for ln, wi in marked:
        row = analysis["lines"][ln.index]
        words = row.get("words", [])
        base = {"line": ln.index, "word_index": wi, "word": ln.tokens[wi].text if wi < len(ln.tokens) else "",
                "start": None, "end": None, "word_db": None, "line_median_db": None, "delta_db": None,
                "word_f0": None, "line_median_f0": None, "status": "unmeasurable"}
        if row.get("status") != "ok" or wi >= len(words) or words[wi]["start"] is None:
            rows.append(base)
            continue
        w = words[wi]
        others = [x for i, x in enumerate(words) if i != wi and x["start"] is not None and x["end"] > x["start"]]
        w_db = rms_db(audio, sr, w["start"], w["end"])
        o_db = [d for d in (rms_db(audio, sr, x["start"], x["end"]) for x in others) if d is not None]
        w_f0 = _median_f0(track, w["start"], w["end"])
        o_f0 = [f for f in (_median_f0(track, x["start"], x["end"]) for x in others) if f is not None]
        base.update({"start": w["start"], "end": w["end"], "word_db": round(w_db, 1) if w_db is not None else None,
                     "word_f0": round(w_f0, 1) if w_f0 else None})
        if w_db is None or not o_db:
            rows.append(base)
            continue
        med_db = median(o_db)
        delta = w_db - med_db
        base["line_median_db"] = round(med_db, 1)
        base["delta_db"] = round(delta, 1)
        louder = delta >= EMPH_DB
        higher = False
        if w_f0 and o_f0:
            med_f0 = median(o_f0)
            base["line_median_f0"] = round(med_f0, 1)
            higher = (w_f0 - med_f0) / med_f0 * 100.0 >= EMPH_F0_PCT
        base["status"] = "met" if (louder or higher) else ("near" if delta >= EMPH_DB / 2 else "diverged")
        rows.append(base)
    return rows
