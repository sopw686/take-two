"""Opt-in "conference conventions" preset.

Off by default. When the user switches it on, two conventional measures are
computed against bands the user can edit: overall words per minute, and filler
words per 100 words. Nothing here is shown unless the user asked for it.
"""

from __future__ import annotations

import re

from marked.config import Settings
from marked.marks import normalize_word
from marked.stt.base import Transcript, Word

FILLERS_1 = {"um", "uh", "umm", "uhh", "erm", "er", "hmm", "mm", "like"}
FILLERS_2 = {("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")}


def conventions_report(transcript: Transcript, analysis: dict, settings: Settings) -> dict:
    words = transcript.words
    lines = [r for r in analysis.get("lines", []) if r.get("status") == "ok"]
    start = min((r["start"] for r in lines), default=None)
    end = max((r["end"] for r in lines), default=None)
    spoken_words = [w for w in words if start is not None and end is not None and start <= w.start <= end]
    n = len(spoken_words)
    overall = (n / ((end - start) / 60.0)) if n and end and start is not None and end > start else None
    lo, hi = settings.conventions_wpm_min, settings.conventions_wpm_max
    if overall is None:
        wpm_status = "unknown"
    elif lo <= overall <= hi:
        wpm_status = "met"
    elif abs(overall - (lo if overall < lo else hi)) <= 0.1 * (hi - lo):
        wpm_status = "near"
    else:
        wpm_status = "diverged"

    fillers = find_fillers(spoken_words)
    per100 = (len(fillers) / n * 100.0) if n else None
    target = settings.conventions_filler_per_100
    if per100 is None:
        f_status = "unknown"
    elif per100 <= target:
        f_status = "met"
    elif per100 <= target * 1.5:
        f_status = "near"
    else:
        f_status = "diverged"
    return {
        "enabled": True,
        "words": n,
        "overall_wpm": round(overall, 1) if overall else None,
        "wpm_band": [lo, hi],
        "wpm_status": wpm_status,
        "span": [start, end],
        "filler_count": len(fillers),
        "filler_per_100": round(per100, 2) if per100 is not None else None,
        "filler_target_per_100": target,
        "filler_status": f_status,
        "fillers": fillers,
        "note": "Whisper often drops um/uh; the filler count is a lower bound.",
    }


def find_fillers(words: list[Word], pairs: set[tuple[str, str]] = FILLERS_2) -> list[dict]:
    """Filler words and two-word filler phrases, with times and word indexes (i..j inclusive)."""
    fillers: list[dict] = []
    norm = [(normalize_word(w.text), w) for w in words]
    i = 0
    while i < len(norm):
        toks, w = norm[i]
        t = toks[0] if toks else ""
        nxt = norm[i + 1][0][0] if i + 1 < len(norm) and norm[i + 1][0] else ""
        if (t, nxt) in pairs:
            fillers.append({"text": f"{w.text} {norm[i + 1][1].text}", "start": w.start, "end": norm[i + 1][1].end,
                            "i": i, "j": i + 1})
            i += 2
            continue
        if t in FILLERS_1 and _is_filler_like(t, w.text):
            fillers.append({"text": w.text, "start": w.start, "end": w.end, "i": i, "j": i})
        i += 1
    return fillers


def _is_filler_like(norm: str, raw: str) -> bool:
    # "like" is only a filler when Whisper wrote it with a surrounding comma, which is
    # the usual transcription of a hesitation ("..., like, ..."). Otherwise it is a verb.
    if norm == "like":
        return bool(re.search(r"[,]", raw))
    return True
