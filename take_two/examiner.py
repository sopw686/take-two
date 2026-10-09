"""Spoken examiner: follow-up questions and the closing line of a hands-free Q&A session.

The session itself runs in the browser (frontend/src/examiner.ts): the examiner asks
each question aloud, the answer is recorded and analyzed as an ordinary Improvise take
whose topic is the question, and a `session` entry in the take's improv.json groups
the answers. This module holds the two things the server decides.

- One follow-up per question, written by a model that reads only the answer's
  transcript text and its measured numbers (never audio). Code keeps it only if it is
  one short question, grounded in a phrase the speaker actually said, and any phrase
  it quotes is in the answer (or the script). It is stored with the answer, so asking
  again returns the same one: a session cannot run away. Without ANTHROPIC_API_KEY
  there are no follow-ups and no stand-in; TAKE_TWO_LLM=fake stays labelled.
- The closing line, written by code from the measured results: how many answers,
  how many stayed within / close to / outside the pace band, the longest wait before
  an answer began. No model, no score.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from take_two import takes
from take_two.marks import normalize_word

MAX_WORDS = 30
MAX_CHARS = 180
QUOTE_RE = re.compile(r"[\"“”]([^\"“”]+)[\"“”]")


class FollowUp(BaseModel):
    question: str = Field(description="One short follow-up question, answerable from what the speaker just said.")
    builds_on: str = Field(description="The words from the answer this question builds on, copied verbatim.")


class FollowUpOutput(BaseModel):
    followups: list[FollowUp] = Field(description="Exactly one follow-up.")


SYSTEM = """You are an examiner in a spoken Q&A after a talk, a thesis defense, a pitch or an interview. You read the question that was asked, the transcript of the speaker's spoken answer (text only; you never hear it) and a few measured numbers. Ask ONE short follow-up question, the way an examiner would out loud, that the speaker can answer from what they just said: ask what a claim was compared with, what a term they used means, how they know something they asserted, or what follows from it. Copy the words of the answer it builds on verbatim into builds_on. If you quote the speaker in the question, quote them exactly. One question, at most 30 words, no preamble, no praise, no judgement of how the answer sounded or was delivered."""


def build_user_prompt(question: str, transcript_text: str, numbers: dict) -> str:
    nums = "; ".join(f"{k}: {v}" for k, v in numbers.items() if v is not None)
    return f"Question asked: {question}\n\nTranscript of the answer:\n\"\"\"\n{transcript_text}\n\"\"\"\n\nMeasured: {nums}"


def _norm(text: str) -> str:
    return " ".join(n for w in text.split() for n in normalize_word(w))


def _contains(hay: str, needle: str) -> bool:
    n = _norm(needle)
    return bool(n) and f" {n} " in f" {_norm(hay)} "


def validate_followups(out: FollowUpOutput, transcript_text: str, script_text: str = "") -> tuple[dict | None, list[dict]]:
    """(the one kept follow-up or None, dropped reasons). Pure; fully testable."""
    kept: dict | None = None
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for f in out.followups:
        q = " ".join(f.question.split())
        outside = QUOTE_RE.sub("", q)  # punctuation inside a quote does not end the question's own sentence
        quotes = QUOTE_RE.findall(q)
        if kept is not None:
            drop("more than one follow-up for a question")
        elif not q.endswith("?"):
            drop("not a question")
        elif outside.count("?") > 1:
            drop("more than one question")
        elif re.search(r"[.!?]\s+\S", outside[:-1]):
            drop("more than one sentence")
        elif len(q.split()) > MAX_WORDS or len(q) > MAX_CHARS:
            drop(f"longer than {MAX_WORDS} words")
        elif not _contains(transcript_text, f.builds_on):
            drop("not grounded in words from your answer")
        elif any(not (_contains(transcript_text, x) or _contains(script_text, x)) for x in quotes):
            drop("quotes words that are not in your answer or script")
        else:
            kept = {"text": q, "builds_on": " ".join(f.builds_on.split())}
    return kept, [{"reason": k, "count": v} for k, v in dropped.items()]


def answer_numbers(analysis: dict) -> dict:
    """The measured numbers the follow-up model may read: no audio, nothing it could hear."""
    r = analysis.get("improv") or {}
    words = (analysis.get("transcript") or {}).get("words") or []
    return {
        "spoken seconds": (r.get("goal") or {}).get("spoken_s"),
        "words per minute": (r.get("pace") or {}).get("overall_wpm"),
        "seconds before the first word": round(words[0]["start"], 1) if words else None,
    }


def ask_followup(take_id: str, llm, script_text: str = "") -> dict:
    """The stored follow-up for this answer, or a new one from the model (at most one per question).
    The script is used only to check quotes; the model never sees it."""
    tdir = takes.take_path(take_id)
    with takes.take_lock(take_id):
        meta = takes.load_json(tdir / "improv.json")
    session = meta.get("session") or {}
    if session.get("followup_of"):
        return {"available": True, "followup": None, "reason": "One follow-up per question: this answer was the follow-up."}
    if "followup" in meta:
        return {"available": True, "followup": meta["followup"], "reason": None, "stored": True}
    if not getattr(llm, "available", False):
        return {"available": False, "followup": None,
                "reason": "Without an ANTHROPIC_API_KEY there are no follow-ups: the examiner goes on to the next question."}
    analysis = takes.load_take(take_id) or {}
    text = (analysis.get("transcript") or {}).get("text", "").strip()
    if not text:
        return {"available": True, "followup": None, "reason": "The answer had no words to follow up on."}
    out = llm.complete_structured(SYSTEM, build_user_prompt(meta.get("topic", ""), text, answer_numbers(analysis)),
                                  FollowUpOutput, max_tokens=2000)
    if out is None:
        return {"available": True, "followup": None, "reason": "The model did not return a usable follow-up."}
    kept, dropped = validate_followups(out, text, script_text)
    fake = "fake" in getattr(llm, "name", "")
    if kept:
        kept["provider"] = llm.name if fake else f"{llm.name} ({getattr(llm, 'model', '')})"
    with takes.take_lock(take_id):
        meta = takes.load_json(tdir / "improv.json")
        if "followup" not in meta:  # another request may have stored one meanwhile; the first wins
            meta["followup"] = kept
            takes.save_json(tdir / "improv.json", meta)
        kept = meta["followup"]
    return {"available": True, "followup": kept, "dropped": dropped,
            "reason": None if kept else "The model's follow-up could not be checked against your answer, so it was dropped."}


# ---- the session and its closing line ---------------------------------------------------------------------------

def session_answers(session_id: str) -> list[dict]:
    """The analyzed answers of one session, in the order they were recorded."""
    out = []
    for t in takes.list_takes(include_unfinished=False):
        if t.get("mode") != "improv":
            continue
        data = takes.load_take(t["take_id"]) or {}
        s = data.get("session") or {}
        if s.get("id") == session_id:
            out.append(data)
    return sorted(out, key=lambda a: a.get("created_at") or "")


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def closing_line(answers: list[dict], skipped: int = 0) -> str:
    """Built from measured numbers only; within / close to / outside YOUR band, never a grade."""
    main = [a for a in answers if not (a.get("session") or {}).get("followup_of")]
    follow = [a for a in answers if (a.get("session") or {}).get("followup_of")]
    if not answers:
        return "No answers were recorded in this session." + (f" You skipped {_plural(skipped, 'question')}." if skipped else "")
    parts = [f"You answered {_plural(len(main), 'question')}"
             + (f" and {_plural(len(follow), 'follow-up')}" if follow else "") + "."]
    status = [((a.get("improv") or {}).get("pace") or {}).get("status") for a in answers]
    within, close, outside = status.count("met"), status.count("near"), status.count("diverged")
    measured = within + close + outside
    if measured:
        bits = [f"{within} stayed within your pace band"] if within else []
        if close:
            bits.append(f"{close} {'was' if close == 1 else 'were'} close to it")
        if outside:
            bits.append(f"{outside} {'was' if outside == 1 else 'were'} outside it")
        if not within:
            bits.insert(0, "none stayed within your pace band")
        parts.append(", ".join(bits)[:1].upper() + ", ".join(bits)[1:] + ".")
    waits = [(a.get("transcript") or {}).get("words") or [] for a in answers]
    firsts = [w[0]["start"] for w in waits if w]
    if firsts:
        parts.append(f"The longest hesitation before an answer was {max(firsts):.0f} second{'' if round(max(firsts)) == 1 else 's'}.")
    if skipped:
        parts.append(f"You skipped {_plural(skipped, 'question')}.")
    return " ".join(parts)
