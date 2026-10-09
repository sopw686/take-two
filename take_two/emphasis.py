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

from take_two.audio import rms_db
from take_two.marks import Script
from take_two.prosody import f0_track, median_f0

log = logging.getLogger(__name__)
EMPH_DB = 3.0      # at least this much louder than the line's median
EMPH_F0_PCT = 10.0  # or at least this much higher in pitch


def emphasis_report(script: Script, analysis: dict, audio: np.ndarray, sr: int) -> list[dict]:
    rows: list[dict] = []
    marked = [(ln, wi) for ln in script.lines for wi in ln.emphasis]
    if not marked:
        return rows
    track = f0_track(audio, sr)
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
        w_f0 = median_f0(track, w["start"], w["end"])
        o_f0 = [f for f in (median_f0(track, x["start"], x["end"]) for x in others) if f is not None]
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
