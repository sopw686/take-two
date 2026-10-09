"""LLM coaching for Improvise takes.

Delivery coaching gets the measured numbers (never audio) and must cite one in
every suggestion; code drops the rest and caps at three. Content review is
opt-in per take: the model reads the transcript text and judges the hook,
staying on topic, suspense and the ending, quoting the speaker's own words.
Code finds every quote in the transcript and attaches timestamps; an item whose
quote cannot be found is dropped rather than shown.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from marked.define import _find_seq, _Flat
from marked.marks import normalize_word
from marked.stt.base import Transcript


class ImprovSuggestion(BaseModel):
    text: str = Field(description="One or two sentences: what to change and how to practise it, citing a measured number.")
    focus: str = Field(default="", description="One of: pace, fillers, hesitation, confidence, clarity, engagement, time.")
    metric: str = Field(default="", description="The measured figure cited, e.g. '4.2 fillers per 100 words'.")


class ImprovCoachOutput(BaseModel):
    suggestions: list[ImprovSuggestion] = Field(description="At most three, most useful first.")


class ContentItem(BaseModel):
    verdict: str = Field(description="One of: strong, present, weak, missing.")
    note: str = Field(description="One sentence, at most 30 words, specific to this speech.")
    evidence_quote: str = Field(default="", description="Exact words copied from the transcript. Empty only if verdict is missing.")


class ContentReview(BaseModel):
    hook: ContentItem = Field(description="Do the first one or two sentences make a listener want to keep listening?")
    on_topic: ContentItem = Field(description="Does the speech stay on the given topic?")
    suspense: ContentItem = Field(description="Is there an open question, tease, contrast or build-up that pays off later?")
    ending: ContentItem = Field(description="Does it end on a clear closing line rather than trailing away?")
    rewrite_opening: str = Field(description="One alternative opening sentence for this same speech, more gripping, at most 30 words.")


SYSTEM_DELIVERY = """You are a speaking coach for unscripted, improvised speech. You receive measurements of one take (never audio): pace, filler words, hesitations, hedging phrases, statements that ended with rising pitch (uptalk) or faded out, words the recognizer could not catch clearly, and vocal variety (pitch range, loudness variation, pace variation, pauses between sentences, opening energy). Each measure has a reference band the speaker can edit, and a status: met, near or diverged.

Write at most three suggestions, most useful first, focusing on measures that diverged. Each must cite a specific number from the data and give one concrete way to practise it. Aim for confident, engaging delivery in the style of good online video speakers: a strong opening, varied pitch and pace, deliberate pauses before key points, and statements that land with a falling pitch. Use plain, encouraging wording. Never invent a measure that is not in the data, never give an overall grade or score, and do not claim to know how the take sounded beyond the numbers. If earlier takes are included, mention a trend only when the numbers show one."""

SYSTEM_CONTENT = """You review the transcript of an improvised speech on a given topic. Judge four things: the hook (do the first sentences make people want to keep listening?), whether it stays on topic, suspense (an open question, a tease, a contrast or a build-up that pays off), and the ending (a clear closing line, not trailing off). For each, give a verdict (strong, present, weak or missing), one specific sentence of feedback, and quote the exact transcript words your judgement rests on, copied verbatim. Leave the quote empty only when something is missing entirely. Then write one alternative opening sentence for the same speech that would hook a listener the way good short-form video speakers do. Filler words in the transcript are part of the recording; do not comment on them here."""

_NUM = re.compile(r"\d")
MAX_OPENING_WORDS = 30


def compact(analysis: dict, history: list[dict] | None = None) -> dict:
    r = analysis["improv"]
    e = r["engagement"]
    t = r["tone"]
    out = {
        "topic": analysis.get("topic"),
        "goal": r["goal"],
        "pace": {k: r["pace"][k] for k in ("overall_wpm", "band", "status")},
        "fillers": {k: r["fillers"][k] for k in ("count", "per_100", "target_per_100", "status")}
                   | {"examples": [f["text"] for f in r["fillers"]["items"][:5]]},
        "hesitation": {"long_pauses": len(r["hesitation"]["pauses"]), "restarts": len(r["hesitation"]["restarts"])}
                      | {k: r["hesitation"][k] for k in ("per_min", "target_per_min", "threshold_s", "status")},
        "hedges": {k: r["hedges"][k] for k in ("count", "per_100", "target_per_100", "status")}
                  | {"examples": [h["phrase"] for h in r["hedges"]["items"][:5]]},
        "uptalk": {"rising_statements": len(t["uptalk"]), "statements_measured": t["uptalk_measured"],
                   "share_pct": t["uptalk_share_pct"], "status": t["uptalk_status"]},
        "trailing_off": {"faded_sentences": len(t["trail_off"]), "sentences_measured": t["trail_measured"],
                         "share_pct": t["trail_share_pct"], "status": t["trail_status"]},
        "clarity_proxy": {k: r["clarity"][k] for k in ("unclear_pct", "target_pct", "status")}
                         | {"examples": [u["text"] for u in r["clarity"]["unclear"][:5]]},
        "engagement": {k: e[k] for k in ("pitch_range_st", "pitch_floor_st", "pitch_status", "loudness_var_db",
                                         "loudness_target_db", "loudness_status", "pace_var_pct", "pace_var_target_pct",
                                         "pace_var_status", "purposeful_per_min", "opening")},
    }
    if history:
        out["earlier_improvise_takes"] = history
    return out


def validate_delivery(out: ImprovCoachOutput | None) -> dict:
    if out is None:
        return {"available": True, "reason": "The model did not return usable suggestions.", "suggestions": []}
    kept = []
    for s in out.suggestions:
        if len(kept) >= 3:
            break
        if not _NUM.search(s.text + " " + s.metric):
            continue
        kept.append({"text": s.text.strip(), "focus": s.focus.strip(), "metric": s.metric.strip()})
    return {"available": True, "suggestions": kept}


def locate_quote(flat: _Flat, quote: str) -> dict | None:
    qn = normalize_word(quote)
    pos = _find_seq(flat.norm, qn) if qn else -1
    return flat.quote(pos, pos + len(qn)) if pos >= 0 else None


def validate_content(out: ContentReview | None, transcript: Transcript) -> dict:
    if out is None:
        return {"available": True, "reason": "The model did not return a usable review.", "items": []}
    flat = _Flat(transcript)
    items, dropped = [], []
    for key, label in (("hook", "Hook"), ("on_topic", "On topic"), ("suspense", "Suspense"), ("ending", "Ending")):
        it: ContentItem = getattr(out, key)
        verdict = it.verdict.strip().lower()
        ev = locate_quote(flat, it.evidence_quote) if it.evidence_quote.strip() else None
        if ev is None and verdict != "missing":
            dropped.append(label)  # a judgement we cannot tie to the speaker's words is not shown
            continue
        items.append({"key": key, "label": label, "verdict": verdict, "note": it.note.strip(), "evidence": ev})
    words = out.rewrite_opening.split()
    opening = " ".join(words[:MAX_OPENING_WORDS]) + ("…" if len(words) > MAX_OPENING_WORDS else "")
    return {"available": True, "items": items, "dropped": dropped, "rewrite_opening": opening}


def coach_improv(analysis: dict, transcript: Transcript, llm, history: list[dict] | None = None,
                 content: bool = False) -> dict:
    """{coaching: {...}, content_review?: {...}}"""
    if not getattr(llm, "available", False):
        reason = "No ANTHROPIC_API_KEY set."
        res = {"coaching": {"available": False, "reason": reason, "suggestions": []}}
        if content:
            res["content_review"] = {"available": False, "reason": reason, "items": []}
        return res
    data = compact(analysis, history)
    user = ("Measurements for this improvised take (JSON):\n" + json.dumps(data, indent=1) +
            "\n\nWrite at most three suggestions.")
    res = {"coaching": validate_delivery(llm.complete_structured(SYSTEM_DELIVERY, user, ImprovCoachOutput))}
    if content:
        if not transcript.words:
            res["content_review"] = {"available": True, "reason": "No speech was recognized.", "items": []}
        else:
            cu = (f"Topic: {analysis.get('topic') or '(none given)'}\n"
                  f"Time goal: {analysis.get('goal_s') or 'none'} seconds\n\n"
                  f"Transcript:\n\"\"\"\n{transcript.text.strip()}\n\"\"\"")
            res["content_review"] = validate_content(llm.complete_structured(SYSTEM_CONTENT, cu, ContentReview), transcript)
    return res
