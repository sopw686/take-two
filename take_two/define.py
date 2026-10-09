"""[DEFINE: term] checks.

Code finds where the term was first spoken (timestamps) and, by default, looks
for definitional phrasing in a window around that point (heuristic, labelled
as such in the UI). With an LLM configured, the model reads the transcript
TEXT only and returns a judgement plus an exact quote; code then verifies the
quote exists in the transcript and attaches timestamps to it. An unverifiable
quote falls back to the heuristic. The model never hears audio.

The model's raw judgements are cached in the take folder, keyed by the terms,
the transcript text, the provider/model and the prompt, so re-analysis (every
Settings change) does not pay for another call. Validation re-runs on every
read: the cache only saves the call, never the checks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from take_two.marks import Script, normalize_word
from take_two.stt.base import Transcript

log = logging.getLogger(__name__)

# Definitional cue phrases, as normalized word sequences.
PATTERNS: list[list[str]] = [
    ["which", "is"], ["which", "are"], ["which", "means"], ["which", "we"], ["meaning"],
    ["is", "a"], ["is", "an"], ["is", "the"], ["are", "the"], ["are", "a"],
    ["refers", "to"], ["called"], ["that", "is"], ["thats"], ["in", "other", "words"],
    ["defined", "as"], ["we", "define"], ["i", "define"], ["stands", "for"], ["known", "as"],
    ["we", "call", "this"], ["we", "call", "that"], ["this", "is", "what", "we", "call"],
    ["i", "mean"], ["namely"], ["for", "example"], ["that", "means"], ["this", "means"],
    ["it", "measures"], ["is", "how"], ["is", "when"], ["is", "where"],
]
BEFORE_WINDOW = 25   # words before the first use in which a definition still counts
AFTER_WINDOW = 14    # words after the first use that still count as "at" first use
LATER_WINDOW = 60    # beyond AFTER_WINDOW, a cue up to here is reported as "defined later"


def _same(a: str, b: str) -> bool:
    """Loose word equality: exact, or shared 5-letter stem with a short suffix difference."""
    if a == b:
        return True
    return len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5] and abs(len(a) - len(b)) <= 3


def _find_seq(hay: list[str], needle: list[str], start: int = 0, loose: bool = False) -> int:
    n = len(needle)
    for i in range(start, len(hay) - n + 1):
        ok = True
        for k in range(n):
            if not (_same(hay[i + k], needle[k]) if loose else hay[i + k] == needle[k]):
                ok = False
                break
        if ok:
            return i
    return -1


class _Flat:
    def __init__(self, transcript: Transcript):
        self.norm: list[str] = []
        self.widx: list[int] = []
        for i, w in enumerate(transcript.words):
            for n in normalize_word(w.text):
                self.norm.append(n)
                self.widx.append(i)
        self.words = transcript.words

    def time(self, k: int) -> tuple[float, float]:
        w = self.words[self.widx[k]]
        return w.start, w.end

    def quote(self, a: int, b: int) -> dict:
        """Original words covering normalized indexes [a, b)."""
        a = max(0, a)
        b = min(len(self.norm), b)
        if b <= a:
            return {"quote": "", "start": None, "end": None}
        wa, wb = self.widx[a], self.widx[b - 1]
        return {"quote": " ".join(w.text for w in self.words[wa:wb + 1]),
                "start": round(self.words[wa].start, 3), "end": round(self.words[wb].end, 3)}


def heuristic_check(term: str, flat: _Flat) -> dict:
    needle = normalize_word(term)
    if not needle or not flat.norm:
        return {"status": "never_spoken", "defined": None, "first_spoken_at": None, "evidence": None,
                "method": "heuristic", "note": "term has no comparable words" if not needle else "empty transcript"}
    occ = _find_seq(flat.norm, needle, loose=True)
    if occ < 0:
        return {"status": "never_spoken", "defined": None, "first_spoken_at": None, "evidence": None,
                "method": "heuristic", "note": "The term was never spoken in this take."}
    occ_end = occ + len(needle)
    first_at = round(flat.time(occ)[0], 3)

    def search(lo: int, hi: int) -> tuple[int, list[str]] | None:
        best: tuple[int, list[str]] | None = None
        for pat in PATTERNS:
            i = _find_seq(flat.norm[max(0, lo):hi], pat)
            if i >= 0:
                pos = max(0, lo) + i
                if best is None or pos < best[0]:
                    best = (pos, pat)
        return best

    hit = search(occ_end, occ_end + AFTER_WINDOW)               # "X, which is ..."
    if hit is None:
        hit = search(occ - BEFORE_WINDOW, occ)                   # "a method called X" / "we define X as"
    if hit is not None:
        pos, pat = hit
        a, b = min(pos, occ) - 1, max(pos + len(pat), occ_end) + 10
        return {"status": "defined", "defined": True, "first_spoken_at": first_at, "method": "heuristic",
                "cue": " ".join(pat), "evidence": flat.quote(a, b)}
    later = search(occ_end + AFTER_WINDOW, occ_end + LATER_WINDOW)
    row = {"status": "undefined", "defined": False, "first_spoken_at": first_at, "method": "heuristic",
           "evidence": flat.quote(occ - 6, occ_end + 8)}
    if later is not None:
        pos, pat = later
        q = flat.quote(pos - 4, pos + len(pat) + 10)
        row["note"] = f"A possible explanation came later ({q['quote'][:80]}…) at {q['start']} s, after the term was already used."
        row["later_evidence"] = q
    else:
        row["note"] = "No definitional phrase (such as “which is”, “called”, “refers to”) was found near the first use."
    return row


class DefineJudgement(BaseModel):
    term: str
    spoken: bool = Field(description="Whether the term (or a close form of it) is said anywhere in the transcript.")
    defined_at_or_before_first_use: bool = Field(
        description="True only if the speaker explains the term's meaning at, or before, the first time they say it.")
    evidence_quote: str = Field(default="", description="Exact words from the transcript that explain the term. Empty if none.")
    explanation: str = Field(default="", description="One sentence, at most 25 words.")


class DefineJudgements(BaseModel):
    judgements: list[DefineJudgement]


SYSTEM = (
    "You read the transcript of a rehearsed speech (a talk, a toast, a pitch, a poem). For each listed term, decide whether the speaker "
    "explained its meaning ALOUD at or before the first time they said it. A term may be a technical word, an "
    "in-joke the audience would not share, or a reference they may not know. Explaining means giving a meaning a "
    "general audience could follow: a definition, a paraphrase, or an example that makes the meaning clear. "
    "Merely using the term, or explaining it only much later, does not count. Quote the exact transcript words "
    "that do the explaining; copy them verbatim. Be strict and brief."
)


PROMPT_VERSION = hashlib.sha1(SYSTEM.encode("utf-8")).hexdigest()[:8]
CACHE_FILE = "defines_llm.json"


def cache_key(terms: list[str], transcript: Transcript, llm) -> str:
    payload = {"terms": sorted({t.strip().lower() for t in terms}), "text": transcript.text,
               "provider": getattr(llm, "name", ""), "model": getattr(llm, "model", ""), "prompt": PROMPT_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _ask_llm(terms: list[str], transcript: Transcript, llm, cache_dir: Path | None) -> DefineJudgements | None:
    key = cache_key(terms, transcript, llm) if cache_dir is not None else None
    if cache_dir is not None:
        try:
            cached = json.loads((cache_dir / CACHE_FILE).read_text(encoding="utf-8"))
            if cached.get("key") == key:
                return DefineJudgements.model_validate(cached["judgements"])
        except (OSError, ValueError, KeyError, ValidationError):
            pass
    user = ("Transcript:\n\"\"\"\n" + transcript.text + "\n\"\"\"\n\nTerms: " + "; ".join(terms) +
            "\n\nReturn one judgement per term, in the same order.")
    out = llm.complete_structured(SYSTEM, user, DefineJudgements, max_tokens=16000)
    if out is not None and cache_dir is not None:  # a failed call is not cached, so the next re-analysis tries again
        from take_two.takes import save_json
        save_json(cache_dir / CACHE_FILE, {"key": key, "judgements": out.model_dump()})
    return out


def llm_check(terms: list[str], transcript: Transcript, flat: _Flat, llm, cache_dir: Path | None = None) -> dict[str, dict]:
    out = _ask_llm(terms, transcript, llm, cache_dir)
    results: dict[str, dict] = {}
    if out is None:
        return results
    for j in out.judgements:
        term = j.term.strip()
        needle = normalize_word(term)
        occ = _find_seq(flat.norm, needle, loose=True) if needle else -1
        if occ < 0:
            # Code decides whether the term was spoken; the model's `spoken` flag is not trusted over the timestamps.
            results[term.lower()] = {"status": "never_spoken", "defined": None, "first_spoken_at": None,
                                     "evidence": None, "method": "llm", "note": j.explanation or "Never spoken."}
            continue
        first_at = round(flat.time(occ)[0], 3)
        ev = None
        if j.evidence_quote.strip():
            qn = normalize_word(j.evidence_quote)
            pos = _find_seq(flat.norm, qn) if qn else -1
            # The quote must start at or near first use; a later explanation does not count.
            if 0 <= pos <= occ + len(needle) + AFTER_WINDOW:
                ev = flat.quote(pos, pos + len(qn))
        if j.defined_at_or_before_first_use and ev is None:
            # The model claimed a definition but we cannot find its quote: do not trust it.
            results[term.lower()] = {"_fallback": True}
            continue
        results[term.lower()] = {
            "status": "defined" if j.defined_at_or_before_first_use else "undefined",
            "defined": bool(j.defined_at_or_before_first_use), "first_spoken_at": first_at,
            "evidence": ev if ev else flat.quote(occ - 6, occ + len(needle) + 8),
            "method": "llm", "note": j.explanation,
        }
    return results


def check_defines(script: Script, transcript: Transcript, llm=None, cache_dir: Path | None = None) -> list[dict]:
    if not script.defines:
        return []
    flat = _Flat(transcript)
    rows: list[dict] = []
    llm_results: dict[str, dict] = {}
    if llm is not None and getattr(llm, "available", False):
        try:
            llm_results = llm_check([d.term for d in script.defines], transcript, flat, llm, cache_dir)
        except Exception as exc:  # never let a cloud failure break the report
            log.warning("LLM define check failed: %s", exc)
            llm_results = {}
    for d in script.defines:
        base = {"term": d.term, "line": d.line, "section": d.section}
        res = llm_results.get(d.term.lower())
        if res is None or res.get("_fallback"):
            h = heuristic_check(d.term, flat)
            if res is not None:
                h["note"] = "The model's quote could not be found at or near the first use; showing the heuristic result instead. " + h.get("note", "")
            rows.append({**base, **h})
        else:
            rows.append({**base, **res})
    return rows


def define_summary(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        if r["status"] == "never_spoken":
            out.append(f"“{r['term']}” was never spoken.")
        elif r["status"] == "undefined":
            out.append(f"“{r['term']}” was not defined before its first use.")
    return out
