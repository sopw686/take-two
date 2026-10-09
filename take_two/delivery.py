"""Hear it: a cue plan for one script line, for a synthetic voice to demonstrate.

Two versions of the same line:

- "As I marked it" is derived only from the speaker's marks, read the same way the
  analysis reads them (the same thresholds from Settings), so the demonstration and
  the report can never disagree. A line with no marks is spoken plainly.
- "Coach's version" adds a delivery the speaker did not write: stressed and slowed
  words, a pitch contour at phrase ends, extra pauses, an overall pace. With a model
  it is invented from the line and the chosen register; without one it comes from
  the register's plain heuristics, labelled as such; with neither (no key, no
  register picked) it is off with a reason. The speaker's written marks are never
  removed or shortened, only added to.

A plan is pure data: an ordered list of segments, each with its text, pace (as a
multiple of the reference rate and in words per minute), pitch shift, contour,
loudness, stress, a pronunciation (`say_as`) and the pause after it, plus where the
cue came from (`source`) and whether the report checks it (`checked`). No audio is
made here; the browser voice or an SSML provider speaks the plan.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from take_two.config import Settings
from take_two.marks import Line, Script, normalize_word

# ---- registers: user-picked starting points, never a universal standard ---------------------------------------
# Each is plain data: what landing it means, and the rules the no-key heuristic applies. The amounts (how much
# slower, how long a pause) are the speaker's own, from Settings (coach_slow_pct, coach_pause_s).
REGISTERS: dict[str, dict] = {
    "technical": {
        "label": "Conversational / technical talk", "pace_pct": 0.0,
        "guidance": "Chunk into phrases of roughly 3-5 seconds. Slow down for new or dense information (numbers, "
                    "definitions, the main result). Pause before the point and after it. One or two stressed words "
                    "per sentence at most. A falling end on statements, so a claim sounds finished, not like a question.",
    },
    "celebratory": {
        "label": "Celebratory (toast, tribute)", "pace_pct": -6.0,
        "guidance": "Warmth over speed: slightly slower overall. A pause after the punchline for the room to react. "
                    "Lower and slower for the sincere line near the end. The last line is slowest with a clear falling "
                    "end, then silence.",
    },
    "slam": {
        "label": "Performance poetry / slam", "pace_pct": 0.0,
        "guidance": "The line break is a breath. Build pace and volume toward the turn, with a drop in pace or volume "
                    "just before it. Deliberate contrast, fast and loud against slow and quiet. End lines on a held "
                    "or falling note. The last line gets the longest pause.",
    },
    "pitch": {
        "label": "Pitch / interview", "pace_pct": 0.0,
        "guidance": "Lead with the claim. Slow down on the number and the ask. No trailing off: hold the volume and "
                    "let statements fall.",
    },
}

# Prosody amounts for the voice. Stress and soften are fixed, coarse shapes (a browser voice cannot do finer).
STRESS_DB, STRESS_ST = 4.0, 2.0
SOFTEN_DB, SOFTEN_ST = -3.0, -2.0
BUILD_DB, BUILD_RATE = 4.0, 0.10      # a build ramps up to this much louder / faster by its last word
MAX_COACH_CUES = 6
MAX_STRESS_PER_SENTENCE = 2
MAX_STRESS_WORDS = 2
PACE_RANGE = (-30.0, 15.0)
PAUSE_RANGE = (0.2, 2.5)
REASON_WORDS = 20

CHECKED = "checked in your report"
DEMO_ONLY = "demonstration only, not checked"
SUGGESTION = "coach's suggestion"


# ---- the model's (or the heuristic's) proposal, validated in code --------------------------------------------

class CoachCue(BaseModel):
    kind: Literal["stress", "slow", "soften", "build", "pause", "contour"] = Field(
        description="stress: louder and higher; slow: stretch it; soften: lower and quieter (the sincere line); "
                    "build: rising pace and volume across it; pause: a pause after it; contour: how its end moves.")
    text: str = Field(description="The exact words of the line this applies to, copied verbatim (one to a few words; "
                                  "for pause and contour, the phrase it follows or ends).")
    contour: Literal["rise", "fall", "hold"] | None = Field(default=None, description="For contour only.")
    pause_s: float | None = Field(default=None, description="For pause only: seconds, 0.2 to 2.5.")
    reason: str = Field(description="One plain sentence of at most 20 words: why this helps the line land.")


class CoachOutput(BaseModel):
    pace_pct: float = Field(default=0.0, description="Overall pace of the line relative to the speaker's median, "
                                                     "in percent (negative is slower), -30 to 15.")
    pace_reason: str = Field(default="", description="Why that pace; required when pace_pct is not 0.")
    cues: list[CoachCue] = Field(description="At most six cues, the most important first.")


COACH_SYSTEM = """You are a voice coach. You receive one line of a speech the speaker will say out loud, with the marks the speaker already wrote, and decide how the line could be delivered so it lands: which word or two to stress, which word to slow down, the pitch contour at the end of each phrase (fall on a finished claim, rise on an open question or a suspended thought, hold for a line that continues), where to add a pause, softer and lower for a sincere line, a build in pace and volume toward a turn, and the overall pace relative to the speaker's own median.
Rules: copy the words each cue applies to verbatim from the line. Never remove or shorten a pause or a stress the speaker wrote; you may only add. At most six cues, and at most two stressed words per sentence. Every cue has one plain reason of at most 20 words, grounded in this line. This is one way to say it, not the correct way: do not claim it is correct, proven, or persuasive."""


def coach_user_prompt(script: Script, line: Line, register: str | None, ref_wpm: float, ref_note: str) -> str:
    sec = script.sections[line.section] if script.sections else None
    prev = script.lines[line.index - 1].text if line.index > 0 else ""
    nxt = script.lines[line.index + 1].text if line.index + 1 < len(script.lines) else ""
    reg = REGISTERS.get(register or "")
    parts = [
        f"Register the speaker picked: {reg['label']}. What landing it means there: {reg['guidance']}" if reg
        else "The speaker has not picked a register: decide from the line's content alone.",
        f"Speaker's reference pace: {ref_wpm:.0f} wpm ({ref_note}).",
        f"Section: {sec.name}" if sec and sec.name else "",
        f"Line before: {prev}" if prev else "This is the first line.",
        f"Line after: {nxt}" if nxt else "This is the last line of the speech.",
        "The speaker's marks on this line: " + describe_marks(line),
        f"The line, exactly as spoken: {line.text}",
    ]
    return "\n".join(p for p in parts if p)


def describe_marks(line: Line) -> str:
    out = []
    if line.is_key:
        out.append("[KEY] (slower than their median, then a pause)")
    words = [t.text for t in line.tokens]
    for p in line.pauses:
        before = words[p.word_index - 1] if 0 < p.word_index <= len(words) else "the start"
        out.append(f"{'long' if p.kind == '//' else 'short'} pause after “{before}”")
    for i in line.emphasis:
        out.append(f"stress on “{words[i]}”")
    return "; ".join(out) or "none"


# ---- per-word working model ----------------------------------------------------------------------------------

def _word(text: str) -> dict:
    return {"text": text, "rate": 1.0, "pitch_st": 0.0, "volume_db": 0.0, "stress": False, "slow": False,
            "say_as": None, "ipa": None, "break_s": 0.0, "contour": "none", "sources": [], "checked": False}


def _bare(token_text: str) -> str:
    return token_text.strip(".,;:!?\"'()[]{}…“”‘’").lower()


def _sentence_ends(words: list[str]) -> list[int]:
    return [i for i, w in enumerate(words) if re.search(r"[.!?][\"'”’)]*$", w)]


def _find_span(words: list[str], text: str) -> tuple[int, int] | None:
    """Token range [a, b] whose words are `text`, compared as written but ignoring case and edge punctuation."""
    want = [_bare(w) for w in text.split()]
    if not want or not all(want):
        return None
    have = [_bare(w) for w in words]
    for a in range(len(have) - len(want) + 1):
        if have[a:a + len(want)] == want:
            return a, a + len(want) - 1
    return None


def _reference(settings: Settings, median_wpm: float | None, median_source: str) -> tuple[float, str, bool]:
    if median_wpm:
        return float(median_wpm), f"your median {median_wpm:.0f} wpm from {median_source}", True
    return (settings.hear_baseline_wpm,
            f"no take yet: using a typical {settings.hear_baseline_wpm:.0f} wpm baseline, not your own rate", False)


def _marked_words(script: Script, line: Line, settings: Settings, ref_wpm: float, ref_note: str,
                  measured: bool) -> tuple[list[dict], float, list[dict], list[str]]:
    """(words, lead-in pause, cues, notes) from the speaker's marks only."""
    words = [_word(t.text) for t in line.tokens]
    cues: list[dict] = []
    notes: list[str] = []
    lead = 0.0
    if line.is_key:
        f = 1 - settings.key_slower_pct / 100.0
        for w in words:
            w["rate"] *= f
            w["sources"].append("mark:KEY")
            w["checked"] = True
        where = "your median" if measured else "a typical baseline (no take yet)"
        cues.append({"source": "mark:KEY", "checked": True, "label": CHECKED,
                     "text": f"slower: {settings.key_slower_pct:.0f}% below {where} "
                             f"({ref_wpm:.0f} wpm → {ref_wpm * f:.0f})"})
        if words:
            words[-1]["break_s"] = max(words[-1]["break_s"], settings.key_pause_after_s)
            words[-1]["sources"].append("mark:KEY")
            cues.append({"source": "mark:KEY", "checked": True, "label": CHECKED,
                         "text": f"{settings.key_pause_after_s:g} s pause after the line (your [KEY] pause setting)"})
    for p in line.pauses:
        target = settings.long_pause_s if p.kind == "//" else settings.short_pause_s
        which = "long-pause" if p.kind == "//" else "short-pause"
        if p.word_index == 0 or not words:
            lead = max(lead, target)
            where = "before the first word"
        else:
            w = words[min(p.word_index, len(words)) - 1]
            w["break_s"] = max(w["break_s"], target)
            w["sources"].append(f"mark:{p.kind}")
            w["checked"] = True
            where = f"after “{_bare(w['text'])}”"
        cues.append({"source": f"mark:{p.kind}", "checked": True, "label": CHECKED,
                     "text": f"{target:g} s pause {where} (your {which} setting)"})
    for i in line.emphasis:
        if i >= len(words):
            continue
        w = words[i]
        w.update(stress=True, volume_db=w["volume_db"] + STRESS_DB, pitch_st=w["pitch_st"] + STRESS_ST)
        w["sources"].append("mark:emphasis")
        on = settings.emphasis_enabled
        w["checked"] = w["checked"] or on
        cues.append({"source": "mark:emphasis", "checked": on, "label": CHECKED if on else DEMO_ONLY,
                     "text": f"“{_bare(w['text'])}” stressed: louder and higher"
                             + ("" if on else " (the emphasis check is off in Settings)")})
    _apply_lexicon(script, words, cues)
    if not cues:
        notes.append("No marks on this line: it is spoken plainly.")
    return words, lead, cues, notes


def _apply_lexicon(script: Script, words: list[dict], cues: list[dict]) -> None:
    lex = script.lexicon
    if not lex:
        return
    for i, w in enumerate(words):
        key = " ".join(normalize_word(re.sub(r"['’]s(?=\W*$)", "", w["text"])))  # Maya's uses Maya's mark
        m = lex.get(key) or lex.get(" ".join(normalize_word(w["text"])))
        if m is None or w["say_as"]:
            continue
        w["say_as"], w["ipa"] = m.respelling, m.ipa
        w["sources"].append("mark:SAY")
        cues.append({"source": "mark:SAY", "checked": False, "label": DEMO_ONLY,
                     "text": f"“{_bare(w['text'])}” said as {m.respelling}" + (f" /{m.ipa}/" if m.ipa else "")
                             + " (your [SAY] mark; the report does not check pronunciation)"})


# ---- segments --------------------------------------------------------------------------------------------------

def _segments(words: list[dict], ref_wpm: float) -> list[dict]:
    """Group words into segments: a new one wherever the voice must change or stop."""
    segs: list[dict] = []
    cur: list[dict] = []

    def close() -> None:
        if not cur:
            return
        last = cur[-1]
        shape = cur[0]
        sources = list(dict.fromkeys(s for w in cur for s in w["sources"]))
        segs.append({
            "text": " ".join(w["text"] for w in cur),
            "say_as": shape["say_as"], "ipa": shape["ipa"],
            "rate": round(shape["rate"], 3), "wpm": round(ref_wpm * shape["rate"], 1),
            "pitch_st": round(shape["pitch_st"], 2), "volume_db": round(shape["volume_db"], 2),
            "contour": last["contour"], "stress": shape["stress"], "slow_word": shape["slow"] and len(cur) == 1,
            "pause_after_s": round(last["break_s"], 2),
            "source": sources[0] if sources else "plain", "sources": sources,
            "checked": any(w["checked"] for w in cur),
        })
        cur.clear()

    def shape(w: dict) -> tuple:
        return (round(w["rate"], 3), round(w["pitch_st"], 2), round(w["volume_db"], 2), w["stress"], w["slow"],
                w["say_as"])

    for w in words:
        if cur and (shape(w) != shape(cur[-1]) or w["say_as"] or cur[-1]["say_as"]):
            close()
        cur.append(w)
        if w["break_s"] > 0 or w["contour"] != "none":
            close()
    close()
    return segs


def _plan(version: str, line: Line, words: list[dict], lead: float, ref_wpm: float, ref_note: str, cues: list[dict],
          notes: list[str], provider: dict, register: str | None = None, **extra) -> dict:
    return {"version": version, "line_index": line.index, "text": line.text, "is_key": line.is_key,
            "reference_wpm": round(ref_wpm, 1), "reference_source": ref_note, "lead_pause_s": round(lead, 2),
            "segments": _segments(words, ref_wpm), "cues": cues, "notes": notes, "provider": provider,
            "register": register, "available": True, "reason": None, **extra}


def marked_plan(script: Script, line_index: int, settings: Settings, median_wpm: float | None = None,
                median_source: str = "your latest take") -> dict:
    """"As I marked it": only what the speaker wrote, measured the way the report measures it."""
    line = script.lines[line_index]
    ref_wpm, ref_note, measured = _reference(settings, median_wpm, median_source)
    words, lead, cues, notes = _marked_words(script, line, settings, ref_wpm, ref_note, measured)
    return _plan("marked", line, words, lead, ref_wpm, ref_note, cues, notes,
                 {"kind": "marks", "label": "your marks"})


# ---- validation of the coach's proposal -------------------------------------------------------------------------

def _clip_reason(reason: str) -> str:
    words = " ".join(reason.split()).split()
    return " ".join(words[:REASON_WORDS]).rstrip(",;:") + ("…" if len(words) > REASON_WORDS else "")


def validate_coach(line: Line, out: CoachOutput, settings: Settings) -> tuple[list[dict], float, str, list[dict]]:
    """(valid cues with token spans, pace_pct, pace reason, dropped reasons). Pure; fully testable.

    A cue survives only if its words are a verbatim span of the line, it has a reason, its values are in range
    (clamped), it does not remove or shorten a mark the speaker wrote, and the caps are not exceeded.
    """
    words = [t.text for t in line.tokens]
    ends = _sentence_ends(words) or [len(words) - 1]
    sentence_of = lambda i: next((k for k, e in enumerate(ends) if i <= e), len(ends) - 1)  # noqa: E731
    user_breaks: dict[int, float] = {}
    for p in line.pauses:
        if p.word_index > 0:
            t = settings.long_pause_s if p.kind == "//" else settings.short_pause_s
            at = min(p.word_index, len(words)) - 1
            user_breaks[at] = max(user_breaks.get(at, 0.0), t)
    if line.is_key and words:
        user_breaks[len(words) - 1] = max(user_breaks.get(len(words) - 1, 0.0), settings.key_pause_after_s)
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    kept: list[dict] = []
    stress_per_sentence: dict[int, int] = {}
    seen: set[tuple] = set()
    for c in out.cues:
        reason = _clip_reason(c.reason or "")
        span = _find_span(words, c.text or "")
        if not reason:
            drop("no reason given")
        elif span is None:
            drop("words not found verbatim in the line")
        elif len(kept) >= MAX_COACH_CUES:
            drop(f"more than {MAX_COACH_CUES} cues")
        elif (c.kind, span) in seen:
            drop("duplicate cue")
        else:
            a, b = span
            cue = {"kind": c.kind, "start": a, "end": b, "text": " ".join(words[a:b + 1]), "reason": reason}
            if c.kind == "stress":
                if b - a + 1 > MAX_STRESS_WORDS:
                    drop(f"stress on more than {MAX_STRESS_WORDS} words")
                    continue
                if all(i in line.emphasis for i in range(a, b + 1)):
                    drop("already stressed by your mark")
                    continue
                s = sentence_of(a)
                if stress_per_sentence.get(s, 0) >= MAX_STRESS_PER_SENTENCE:
                    drop(f"more than {MAX_STRESS_PER_SENTENCE} stressed words in a sentence")
                    continue
                stress_per_sentence[s] = stress_per_sentence.get(s, 0) + 1
            elif c.kind == "contour":
                if c.contour not in ("rise", "fall", "hold"):
                    drop("contour without rise, fall or hold")
                    continue
                cue["contour"] = c.contour
            elif c.kind == "pause":
                want = settings.coach_pause_s if c.pause_s is None else min(max(c.pause_s, PAUSE_RANGE[0]), PAUSE_RANGE[1])
                mine = user_breaks.get(b)
                if mine is not None and want <= mine:
                    drop("a pause you wrote is already at least as long")
                    continue
                cue["pause_s"] = round(want, 2)
            seen.add((c.kind, span))
            kept.append(cue)
    pace = min(max(out.pace_pct or 0.0, PACE_RANGE[0]), PACE_RANGE[1])
    pace_reason = _clip_reason(out.pace_reason or "")
    if pace and not pace_reason:
        drop("pace change without a reason")
        pace = 0.0
    return kept, pace, pace_reason, [{"reason": k, "count": v} for k, v in dropped.items()]


# ---- the register heuristics (no key) ---------------------------------------------------------------------------

_NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                 "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                 "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
                 "billion", "percent", "half", "double", "twice"}
_ASK_WORDS = {"ask", "asking", "raise", "raising", "invest", "investment", "fund", "funding", "join", "hire", "need"}
_STOP = {"the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "is", "are", "was", "were",
         "it", "its", "this", "that", "these", "those", "we", "you", "i", "he", "she", "they", "be", "been", "by", "as",
         "from", "so", "not", "no", "our", "your", "my", "me", "us", "them", "their", "there", "here", "than", "then",
         "what", "which", "who", "when", "where", "how", "do", "did", "does", "have", "has", "had", "will", "would",
         "can", "could", "just", "only", "very", "too", "also", "still", "all", "every", "out", "up", "about", "into"}


def _is_number(w: str) -> bool:
    b = _bare(w)
    return bool(re.search(r"\d", b)) or b in _NUMBER_WORDS


def _content(w: str) -> bool:
    b = _bare(w)
    return len(b) >= 4 and b not in _STOP


def heuristic_coach(script: Script, line: Line, register: str) -> CoachOutput:
    """The register's plain rules applied to the line's words and punctuation. No model; labelled heuristic."""
    words = [t.text for t in line.tokens]
    if not words:
        return CoachOutput(cues=[])
    reg = REGISTERS[register]
    ends = _sentence_ends(words)
    if not ends or ends[-1] != len(words) - 1:
        ends.append(len(words) - 1)
    last_line = line.index == len(script.lines) - 1
    cues: list[CoachCue] = []
    starts = [0] + [e + 1 for e in ends[:-1]]

    def contour_for(e: int) -> Literal["rise", "fall", "hold"]:
        return "rise" if words[e].rstrip("\"'”’)").endswith("?") else "fall"

    if register == "technical":
        for s, e in zip(starts, ends):
            nums = [i for i in range(s, e + 1) if _is_number(words[i])]
            if nums:
                a = nums[0]
                b = a
                while b + 1 <= e and _is_number(words[b + 1]):
                    b += 1
                cues.append(CoachCue(kind="slow", text=" ".join(words[a:b + 1]),
                                     reason="Slow down on the number so the room can take it in."))
            focus = next((i for i in range(e, s - 1, -1) if _content(words[i]) and not _is_number(words[i])), None)
            if focus is not None:
                cues.append(CoachCue(kind="stress", text=words[focus],
                                     reason="New information tends to come at the end of a sentence; lean on it."))
            cues.append(CoachCue(kind="contour", text=words[e], contour=contour_for(e),
                                 reason="A falling end makes a claim sound finished, not like a question."
                                 if contour_for(e) == "fall" else "A rising end marks a real question."))
            if e != len(words) - 1:
                cues.append(CoachCue(kind="pause", text=words[e], reason="A beat between sentences lets each one land."))
        for i, w in enumerate(words[:-1]):
            if w.endswith(":"):
                cues.append(CoachCue(kind="pause", text=w, reason="Pause before the point so it arrives on its own."))
    elif register == "celebratory":
        for s, e in zip(starts, ends):
            if e != len(words) - 1:
                cues.append(CoachCue(kind="pause", text=words[e], reason="Leave room for the room to react."))
        if line.is_key:
            span = words[max(0, len(words) - 3):]
            cues.append(CoachCue(kind="soften", text=" ".join(span),
                                 reason="Lower and quieter for the sincere line, so it sounds meant."))
        if last_line:
            cues.append(CoachCue(kind="slow", text=" ".join(words[max(0, len(words) - 3):]),
                                 reason="The last line is the slowest one."))
            cues.append(CoachCue(kind="pause", text=words[-1], pause_s=1.5,
                                 reason="Then silence: let the glasses go up before anyone speaks."))
        cues.append(CoachCue(kind="contour", text=words[-1], contour=contour_for(len(words) - 1),
                             reason="A clear falling end tells the room the line is complete."))
    elif register == "slam":
        breaks = sorted({p.word_index for p in line.pauses if 0 < p.word_index < len(words)})
        phrases = list(zip([0] + breaks, [b - 1 for b in breaks] + [len(words) - 1]))
        ends_long = any(p.kind == "//" and p.word_index >= len(words) for p in line.pauses)
        if len(phrases) >= 3:
            a, b = phrases[0][0], phrases[-2][1]
            span = words[a:b + 1]
            if len(span) <= 12:
                cues.append(CoachCue(kind="build", text=" ".join(span),
                                     reason="Build pace and volume across the line toward its last phrase."))
        if ends_long or line.is_key:
            a, b = phrases[-1]
            cues.append(CoachCue(kind="soften", text=" ".join(words[a:b + 1]),
                                 reason="Drop the pace and volume just before the turn, for contrast."))
        cues.append(CoachCue(kind="contour", text=words[-1], contour="hold" if not last_line else "fall",
                             reason="End the line on a held note; the poem is not finished yet."
                             if not last_line else "The last line ends on a fall."))
        if last_line:
            cues.append(CoachCue(kind="pause", text=words[-1], pause_s=2.0, reason="The last line gets the longest silence."))
    elif register == "pitch":
        for s, e in zip(starts, ends):
            nums = [i for i in range(s, e + 1) if _is_number(words[i])]
            if nums:
                a = nums[0]
                b = a
                while b + 1 <= e and _is_number(words[b + 1]):
                    b += 1
                cues.append(CoachCue(kind="slow", text=" ".join(words[a:b + 1]), reason="Slow down on the number so it is heard."))
            ask = next((i for i in range(s, e + 1) if _bare(words[i]) in _ASK_WORDS), None)
            if ask is not None:
                cues.append(CoachCue(kind="stress", text=words[ask], reason="The ask is the point of the pitch; land it."))
            cues.append(CoachCue(kind="contour", text=words[e], contour="fall",
                                 reason="No trailing off: a falling end sounds certain."))
    return CoachOutput(pace_pct=reg["pace_pct"], pace_reason="Warmth over speed: a little slower overall."
                       if reg["pace_pct"] else "", cues=cues[:MAX_COACH_CUES])


# ---- the coach's version ----------------------------------------------------------------------------------------

def _accept_as(cue: dict, settings: Settings) -> dict | None:
    """The mark a coach cue becomes when accepted into the script, or None if it has no mark equivalent."""
    if cue["kind"] == "stress":
        return {"type": "emphasis", "word_indexes": list(range(cue["start"], cue["end"] + 1))}
    if cue["kind"] == "pause":
        long = cue["pause_s"] >= settings.long_pause_s
        return {"type": "long_pause" if long else "pause", "word_index": cue["end"] + 1}
    return None


def coach_plan(script: Script, line_index: int, settings: Settings, proposal: CoachOutput | None, provider: dict,
               median_wpm: float | None = None, median_source: str = "your latest take") -> dict:
    """The speaker's marks, then the coach's cues on top. `proposal` comes from the model, the fake, or
    heuristic_coach; provider says which, and the plan carries that label everywhere it is shown."""
    line = script.lines[line_index]
    ref_wpm, ref_note, measured = _reference(settings, median_wpm, median_source)
    words, lead, cues, notes = _marked_words(script, line, settings, ref_wpm, ref_note, measured)
    notes = [n for n in notes if not n.startswith("No marks")]
    if proposal is None:
        return _plan("coach", line, words, lead, ref_wpm, ref_note, cues, notes, provider,
                     settings.hear_register if settings.hear_register != "none" else None,
                     available=False, reason=provider.get("reason") or "The coach did not return a usable plan.",
                     dropped=[], suggestions=[])
    kept, pace, pace_reason, dropped = validate_coach(line, proposal, settings)
    tag = f"register:{settings.hear_register}" if provider["kind"] == "heuristic" else "coach"
    suggestions: list[dict] = []
    if pace:
        if line.is_key:
            notes.append(f"The coach suggested {pace:+.0f}% pace; your [KEY] rate wins on this line.")
        else:
            for w in words:
                w["rate"] *= 1 + pace / 100.0
                w["sources"].append(tag)
            suggestions.append({"id": len(suggestions), "kind": "pace", "text": "", "source": tag, "checked": False,
                                "label": f"{SUGGESTION}; {DEMO_ONLY}", "reason": pace_reason,
                                "cue": f"overall pace {pace:+.0f}% ({ref_wpm:.0f} → {ref_wpm * (1 + pace / 100):.0f} wpm)"})
    for c in kept:
        span = words[c["start"]:c["end"] + 1]
        n = len(span)
        if c["kind"] == "stress":
            for w in span:
                w.update(stress=True, volume_db=w["volume_db"] + STRESS_DB, pitch_st=w["pitch_st"] + STRESS_ST)
            what = f"“{_bare(c['text'])}” stressed: louder and higher"
        elif c["kind"] == "slow":
            for w in span:
                w["rate"] *= 1 - settings.coach_slow_pct / 100.0
                w["slow"] = True
            what = f"“{_bare(c['text'])}” slower ({settings.coach_slow_pct:.0f}% below the line's pace)"
        elif c["kind"] == "soften":
            for w in span:
                w.update(volume_db=w["volume_db"] + SOFTEN_DB, pitch_st=w["pitch_st"] + SOFTEN_ST)
                w["rate"] *= 1 - settings.coach_slow_pct / 200.0
            what = f"“{_bare(c['text'])}” lower, quieter and a little slower"
        elif c["kind"] == "build":
            for k, w in enumerate(span):
                f = (k + 1) / n
                w["volume_db"] += BUILD_DB * f
                w["rate"] *= 1 + BUILD_RATE * f
            what = f"build pace and volume across “{_bare(c['text'])}”"
        elif c["kind"] == "contour":
            span[-1]["contour"] = c["contour"]
            what = {"rise": "rising", "fall": "falling", "hold": "held"}[c["contour"]] + f" end on “{_bare(span[-1]['text'])}”"
        else:  # pause
            span[-1]["break_s"] = max(span[-1]["break_s"], c["pause_s"])
            what = f"{c['pause_s']:g} s pause after “{_bare(span[-1]['text'])}”"
        for w in span:
            w["sources"].append(tag)
        mark = _accept_as(c, settings)
        if mark and mark["type"] == "emphasis":
            label = f"{SUGGESTION}; becomes *word* if you accept it, then checked in your report when the emphasis check is on"
        elif mark:
            label = f"{SUGGESTION}; becomes a {'//' if mark['type'] == 'long_pause' else '/'} mark if you accept it, then {CHECKED}"
        else:
            label = f"{SUGGESTION}; {DEMO_ONLY}"
        suggestions.append({"id": len(suggestions), "kind": c["kind"], "text": c["text"], "source": tag,
                            "checked": False, "label": label, "reason": c["reason"], "cue": what, "accept": mark})
    if not kept and not pace:
        notes.append("The coach added nothing to this line.")
    return _plan("coach", line, words, lead, ref_wpm, ref_note, cues, notes, provider,
                 settings.hear_register if settings.hear_register != "none" else None,
                 dropped=dropped, suggestions=suggestions)


def coach_provider(llm, register: str) -> tuple[dict, bool]:
    """(provider description, use the model?). Without a model the register's heuristics, labelled as such;
    without either, unavailable with a reason. The fake stays a labelled stand-in."""
    if getattr(llm, "available", False):
        fake = "fake" in getattr(llm, "name", "")
        return ({"kind": "fake" if fake else "model",
                 "label": llm.name if fake else f"{llm.name} ({getattr(llm, 'model', '')}): the coach's model"}, True)
    if register != "none":
        return ({"kind": "heuristic",
                 "label": f"heuristic: the {REGISTERS[register]['label']} register's rules, not a model"}, False)
    return ({"kind": "none", "label": "unavailable",
             "reason": "Without an ANTHROPIC_API_KEY the coach's version comes from a register's rules. "
                       "Pick a register in Settings → Hear it to hear one."}, False)


def accept_rows(script: Script, line_index: int, suggestions: list[dict]) -> list[dict]:
    """Accepted coach suggestions as rows for suggest.apply_marks (pauses and *word* only)."""
    line = script.lines[line_index]
    rows: list[dict] = []
    for s in suggestions:
        mark = s.get("accept")
        if not mark:
            continue
        if mark["type"] == "emphasis":
            for wi in mark["word_indexes"]:
                if 0 <= wi < len(line.tokens):
                    rows.append({"type": "emphasis", "word_index": wi, "raw_line_no": line.raw_line_no})
        elif 0 <= mark["word_index"] <= len(line.tokens):
            rows.append({"type": mark["type"], "word_index": mark["word_index"], "raw_line_no": line.raw_line_no})
    return rows
