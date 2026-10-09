"""Suggested marks for people who don't want to mark from scratch.

Rule: code measures, the model only interprets. The model reads the script
text and proposes a FEW marks with one-line reasons. Code then validates every
proposal against the script, enforces caps (LLMs over-mark), computes section
budgets itself, and the UI shows proposals as ghost marks the user accepts or
rejects. Nothing is applied silently. Without an API key the feature is off;
there is deliberately no heuristic substitute.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from marked import takes
from marked.llm import get_llm
from marked.marks import (DEFINE_RE, KEY_RE, PAUSE_RE, Script, format_budget, is_section_header,
                          normalize_word, parse_script)

router = APIRouter(prefix="/api/suggest")

GOALS: dict[str, str] = {
    "clear": "clear and informative: the audience should follow every step. Prefer [DEFINE] marks for terms a general "
             "audience is unlikely to know and section budgets that give methods and results their fair share.",
    "persuasive": "persuasive / land the main finding: one central claim must land. Prefer a pause before and a long "
                  "pause after the central claim, and a single [KEY] on it.",
    "somber": "somber: measured and grave. Prefer slower [KEY] lines and more long pauses (//), fewer short ones.",
    "warm": "warm / celebratory: generous and quick. Prefer fewer, shorter pauses; at most one [KEY]; avoid heavy marking.",
}
GOAL_LABELS = {"clear": "Clear and informative", "persuasive": "Persuasive / land the main finding",
               "somber": "Somber", "warm": "Warm / celebratory"}

MAX_KEY_TOTAL = 3
MAX_KEY_PER_SECTION = 1
WORDS_PER_PAUSE = 40
MAX_DEFINE = 4
DEFAULT_WPM = 140.0


class ProposedMark(BaseModel):
    type: Literal["key", "pause", "long_pause", "define", "section"]
    line_index: int = Field(description="0-based index of the script line the mark belongs to.")
    word_index: int | None = Field(default=None, description="For pauses: the pause goes BEFORE this word (0-based) of the line; use the line's word count to put it at the end.")
    term: str | None = Field(default=None, description="For define: the term, exactly as it appears in the line.")
    name: str | None = Field(default=None, description="For section: a short section name. The section starts at line_index.")
    reason: str = Field(description="At most 20 words, written so a novice learns why this mark helps.")


class Proposal(BaseModel):
    marks: list[ProposedMark] = Field(description="Ordered from most to least important. Prefer few marks.")


SYSTEM = """You help a speaker mark up the script of a science talk with delivery intentions. The marks:
- key: a key line, delivered slower than the speaker's own median, followed by a pause. Use for the one sentence a section exists to deliver.
- pause: a deliberate short pause (about 0.7 s) before a word. long_pause: a long pause (about 1.5 s), typically after a result sentence or before a turn in the argument.
- define: a technical term the speaker must explain aloud at or before first use. Only for terms a general scientific audience would not know; never common words.
- section: start a section at a line, with a short name (Introduction, Methods, Results, ...). Only propose sections if the script has none. Do not propose budgets; the app computes them.

Restraint matters more than coverage. Over-marking recreates generic speech-coach advice, which is exactly what this tool avoids. Prefer few marks: at most one key per section and three in total, no more than about one pause per 40 words, and only a handful of define marks. Order marks from most to least important. Every reason must be one plain sentence of at most 20 words that teaches a novice why this spot matters, grounded in the script's content.
Marks can check pace and pauses. They cannot make a take sound sad or moving; do not claim they will."""


def _lines_for_model(script: Script) -> str:
    return "\n".join(f"{ln.index}: {ln.text}" for ln in script.lines)


def build_user_prompt(script: Script, goal: str, notes: str, target_seconds: int | None) -> str:
    words = sum(ln.word_count for ln in script.lines)
    existing = []
    if any(s.name for s in script.sections):
        existing.append("The script already has sections: " + ", ".join(s.name or "untitled" for s in script.sections) + ". Do not propose sections.")
    if any(ln.is_key for ln in script.lines):
        existing.append("Some lines are already marked key; do not propose those again.")
    parts = [
        f"Goal: {GOALS.get(goal, GOALS['clear'])}",
        f"The script has {len(script.lines)} lines and {words} words." + (f" Target length: {format_budget(target_seconds)}." if target_seconds else ""),
        ("Speaker's notes: " + notes.strip()) if notes.strip() else "",
        " ".join(existing),
        "Script (line index: text):\n" + _lines_for_model(script),
    ]
    return "\n\n".join(p for p in parts if p)


def _term_in_text(term: str, text: str) -> bool:
    t = " ".join(n for w in term.split() for n in normalize_word(w))
    hay = " ".join(n for w in text.split() for n in normalize_word(w))
    return bool(t) and f" {t} " in f" {hay} "


def validate_and_cap(script: Script, proposal: Proposal, rate_wpm: float, rate_source: str,
                     target_seconds: int | None) -> tuple[list[dict], list[dict]]:
    """Return (accepted suggestions, dropped reasons). Pure; fully testable."""
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    n = len(script.lines)
    has_sections = any(s.name for s in script.sections)
    out: list[dict] = []
    seen: set[tuple] = set()

    # Section proposals first: they define the boundaries used for the KEY cap.
    section_lines: list[tuple[int, str]] = []
    for m in proposal.marks:
        if m.type != "section":
            continue
        if has_sections:
            drop("section proposed but the script already has sections")
            continue
        if not (0 <= m.line_index < n):
            drop("section line index out of range")
            continue
        if any(li == m.line_index for li, _ in section_lines):
            drop("duplicate section")
            continue
        section_lines.append((m.line_index, (m.name or "Section").strip()[:40]))
    section_lines.sort()
    if section_lines and section_lines[0][0] != 0:
        section_lines.insert(0, (0, "Opening"))

    def section_of(line_index: int) -> int:
        if has_sections:
            return script.lines[line_index].section
        sec = 0
        for i, (li, _) in enumerate(section_lines):
            if line_index >= li:
                sec = i
        return sec

    total_words = sum(ln.word_count for ln in script.lines)
    if section_lines:
        bounds = [li for li, _ in section_lines] + [n]
        for i, (li, name) in enumerate(section_lines):
            words = sum(script.lines[k].word_count for k in range(li, bounds[i + 1]))
            if target_seconds and total_words:
                budget = target_seconds * words / total_words
                src = "proportional to word count within your target length"
            else:
                budget = words / rate_wpm * 60.0
                src = rate_source
            budget = max(5.0, round(budget / 5.0) * 5.0)
            reason = next((m.reason for m in proposal.marks if m.type == "section" and m.line_index == li), "")
            out.append(_row(script, "section", li, None, None, name, budget, reason or f"Starts a section here; the budget is {src}.",
                            budget_estimated=rate_source.startswith("estimate") and not target_seconds, budget_source=src))

    key_total = 0
    key_per_sec: dict[int, int] = {}
    pause_count = 0
    pause_cap = max(1, math.ceil(total_words / WORDS_PER_PAUSE))
    define_count = 0
    for m in proposal.marks:
        if m.type == "section":
            continue
        if not (0 <= m.line_index < n):
            drop("line index out of range")
            continue
        ln = script.lines[m.line_index]
        reason = (m.reason or "").strip()
        if len(reason.split()) > 20:
            reason = " ".join(reason.split()[:20]).rstrip(",;:") + "…"
        if m.type == "key":
            if ln.is_key:
                drop("line already marked key")
                continue
            sec = section_of(m.line_index)
            if key_total >= MAX_KEY_TOTAL:
                drop("more than three key lines")
                continue
            if key_per_sec.get(sec, 0) >= MAX_KEY_PER_SECTION:
                drop("more than one key line in a section")
                continue
            if ("key", m.line_index) in seen:
                drop("duplicate key")
                continue
            seen.add(("key", m.line_index))
            key_total += 1
            key_per_sec[sec] = key_per_sec.get(sec, 0) + 1
            out.append(_row(script, "key", m.line_index, None, None, None, None, reason))
        elif m.type in ("pause", "long_pause"):
            wi = m.word_index
            if wi is None or not (0 <= wi <= ln.word_count):
                drop("pause word index out of range")
                continue
            if any(p.word_index == wi for p in ln.pauses):
                drop("pause already marked at that spot")
                continue
            if ("pause", m.line_index, wi) in seen:
                drop("duplicate pause")
                continue
            if pause_count >= pause_cap:
                drop(f"more than one pause per {WORDS_PER_PAUSE} words")
                continue
            seen.add(("pause", m.line_index, wi))
            pause_count += 1
            out.append(_row(script, m.type, m.line_index, wi, None, None, None, reason))
        elif m.type == "define":
            term = (m.term or "").strip().strip(".,;:")
            if not term or not _term_in_text(term, ln.text):
                if term and _term_in_text(term, " ".join(l.text for l in script.lines)):
                    # Present in the script but on another line: move it to its first line.
                    first = next(l.index for l in script.lines if _term_in_text(term, l.text))
                    m.line_index = first
                else:
                    drop("define term not found in the script")
                    continue
            if any(d.term.lower() == term.lower() for d in script.defines):
                drop("term already has a define mark")
                continue
            if ("define", term.lower()) in seen:
                drop("duplicate define")
                continue
            if define_count >= MAX_DEFINE:
                drop("more than four define marks")
                continue
            seen.add(("define", term.lower()))
            define_count += 1
            out.append(_row(script, "define", m.line_index, None, term, None, None, reason))
    for i, row in enumerate(out):
        row["id"] = i
    return out, [{"reason": k, "count": v} for k, v in dropped.items()]


def _row(script: Script, type_: str, line_index: int, word_index: int | None, term: str | None, name: str | None,
         budget_s: float | None, reason: str, **extra) -> dict:
    ln = script.lines[line_index]
    row = {"id": 0, "type": type_, "line_index": line_index, "raw_line_no": ln.raw_line_no, "word_index": word_index,
           "term": term, "name": name, "budget_s": budget_s, "budget_label": format_budget(budget_s) if budget_s else None,
           "reason": reason, **extra}
    row["preview"] = apply_to_line(ln.raw, [row]) if type_ != "section" else f"## {name} [{format_budget(budget_s)}]"
    return row


# ---- applying accepted suggestions to the raw text ---------------------------------

def line_components(raw: str) -> tuple[bool, list[str], dict[int, str], list[str]]:
    """(is_key, raw words incl. *emphasis*, pauses {word_index: kind}, define terms)."""
    is_key = bool(KEY_RE.match(raw))
    s = KEY_RE.sub("", raw, count=1) if is_key else raw
    terms = [m.group("term").strip() for m in DEFINE_RE.finditer(s)]
    s = DEFINE_RE.sub(" ", s)
    words: list[str] = []
    pauses: dict[int, str] = {}
    for piece in s.split():
        pm = PAUSE_RE.match(piece)
        if pm:
            k = pm.group("kind")
            pauses[len(words)] = "//" if "//" in (k, pauses.get(len(words), "")) else "/"
            continue
        words.append(piece)
    return is_key, words, pauses, terms


def rebuild_line(is_key: bool, words: list[str], pauses: dict[int, str], terms: list[str]) -> str:
    parts: list[str] = []
    for i, w in enumerate(words):
        if i in pauses:
            parts.append(pauses[i])
        parts.append(w)
    if len(words) in pauses:
        parts.append(pauses[len(words)])
    body = " ".join(parts)
    defs = " ".join(f"[DEFINE: {t}]" for t in terms)
    line = ("[KEY] " if is_key else "") + (defs + " " if defs else "") + body
    return line.strip()


def apply_to_line(raw: str, accepted: list[dict]) -> str:
    is_key, words, pauses, terms = line_components(raw)
    for a in accepted:
        if a["type"] == "key":
            is_key = True
        elif a["type"] in ("pause", "long_pause"):
            wi = int(a["word_index"] or 0)
            wi = max(0, min(wi, len(words)))
            kind = "//" if a["type"] == "long_pause" else "/"
            if pauses.get(wi) != "//":
                pauses[wi] = kind
        elif a["type"] == "define" and a.get("term"):
            if a["term"].lower() not in [t.lower() for t in terms]:
                terms.append(a["term"])
    return rebuild_line(is_key, words, pauses, terms)


def apply_marks(script_text: str, accepted: list[dict]) -> str:
    raw_lines = script_text.splitlines()
    by_line: dict[int, list[dict]] = {}
    sections: list[dict] = []
    for a in accepted:
        if a["type"] == "section":
            sections.append(a)
        else:
            by_line.setdefault(int(a["raw_line_no"]), []).append(a)
    for no, items in by_line.items():
        if 0 <= no < len(raw_lines) and raw_lines[no].strip() and not is_section_header(raw_lines[no]):
            raw_lines[no] = apply_to_line(raw_lines[no], items)
    for a in sorted(sections, key=lambda s: int(s["raw_line_no"]), reverse=True):
        no = int(a["raw_line_no"])
        header = f"## {a.get('name') or 'Section'} [{format_budget(a.get('budget_s'))}]"
        raw_lines.insert(no, header)
        if no > 0 and raw_lines[no - 1].strip():
            raw_lines.insert(no, "")
    return "\n".join(raw_lines) + ("\n" if script_text.endswith("\n") else "")


# ---- HTTP ---------------------------------------------------------------------------

class SuggestBody(BaseModel):
    script: str
    goal: str = "clear"
    notes: str = ""
    target_seconds: int | None = None


class ApplyBody(BaseModel):
    script: str
    accepted: list[dict]


def _rate() -> tuple[float, str]:
    wpm = takes.latest_median_wpm()
    if wpm:
        return float(wpm), f"your median {wpm:.0f} wpm from your latest take"
    return DEFAULT_WPM, "estimate at 140 wpm (no take yet)"


@router.get("")
async def suggest_status() -> dict:
    from marked.llm import llm_status
    st = llm_status()
    return {"available": st["available"], "reason": st["reason"], "goals": GOAL_LABELS}


@router.post("")
async def suggest(body: SuggestBody) -> dict:
    llm = get_llm()
    script = parse_script(body.script)
    lines = [{"index": ln.index, "raw_line_no": ln.raw_line_no, "text": ln.text} for ln in script.lines]
    if not llm.available:
        from marked.llm import llm_status
        return {"available": False, "reason": llm_status()["reason"], "suggestions": [], "dropped": [],
                "rate_wpm": 0, "rate_source": "", "lines": lines}
    if not script.lines:
        return {"available": True, "reason": "The script is empty.", "suggestions": [], "dropped": [], "rate_wpm": 0,
                "rate_source": "", "lines": lines}
    rate, source = _rate()
    from fastapi.concurrency import run_in_threadpool
    proposal = await run_in_threadpool(llm.complete_structured, SYSTEM,
                                       build_user_prompt(script, body.goal, body.notes, body.target_seconds), Proposal)
    if proposal is None:
        return {"available": True, "reason": "The model did not return a usable proposal. Try again.", "suggestions": [],
                "dropped": [], "rate_wpm": rate, "rate_source": source, "lines": lines}
    accepted, dropped = validate_and_cap(script, proposal, rate, source, body.target_seconds)
    return {"available": True, "suggestions": accepted, "dropped": dropped, "rate_wpm": rate, "rate_source": source,
            "lines": lines, "proposed": len(proposal.marks)}


@router.post("/apply")
async def apply(body: ApplyBody) -> dict:
    return {"text": apply_marks(body.script, body.accepted)}
