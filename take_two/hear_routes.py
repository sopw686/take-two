"""Hear it, pronunciations and the clarity list's "I said it fine". Mounted under /api.

Every route takes script text and returns text or a plan; the speaker's recordings are not read
here (the clarity list itself is computed during analysis, from the transcript).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from take_two import clarity, config, delivery, pronounce, takes, tts
from take_two.config import Settings
from take_two.llm import get_llm
from take_two.marks import SAY_RE, parse_script, say_mark

router = APIRouter(prefix="/api")

_coach_cache: dict[str, delivery.CoachOutput | None] = {}


class HearBody(BaseModel):
    script: str | None = None   # None: the script of take_id, as it was recorded
    line_index: int
    version: Literal["marked", "coach"] = "marked"
    settings: Settings | None = None
    take_id: str | None = None


def _settings(script: str, requested: Settings | None) -> Settings:
    try:
        return config.effective_settings(requested or Settings(), script)[0]
    except config.ScriptSettingsError as exc:
        raise HTTPException(400, str(exc)) from exc


def _median(take_id: str | None) -> tuple[float | None, str]:
    """The speaker's measured median: from the take the line came from, else their latest take."""
    if take_id:
        try:
            data = takes.load_take(take_id) or {}
        except ValueError:
            data = {}
        b = data.get("baseline") or {}
        if data.get("kind") == "drill":
            return (data.get("drill") or {}).get("parent_median_wpm"), "the full take this drill came from"
        if data.get("kind", "take") == "take" and b.get("median_wpm"):
            return b["median_wpm"], "this take"
    wpm = takes.latest_median_wpm()
    return wpm, "your latest take"


def _coach_proposal(script, line, settings: Settings, ref: float, note: str) -> tuple[delivery.CoachOutput | None, dict]:
    llm = get_llm()
    provider, use_model = delivery.coach_provider(llm, settings.hear_register)
    if provider["kind"] == "none":
        return None, provider
    if not use_model:
        return delivery.heuristic_coach(script, line, settings.hear_register), provider
    register = settings.hear_register if settings.hear_register != "none" else None
    user = delivery.coach_user_prompt(script, line, register, ref, note)
    key = hashlib.sha256(json.dumps([provider["label"], user, delivery.COACH_SYSTEM]).encode("utf-8")).hexdigest()
    if key not in _coach_cache:
        out = llm.complete_structured(delivery.COACH_SYSTEM, user, delivery.CoachOutput, max_tokens=4000)
        if out is None:
            provider = {**provider, "reason": "The coach's model did not return a usable plan. Try again."}
            return None, provider
        _coach_cache[key] = out
    return _coach_cache[key], provider


@router.post("/hear")
async def hear(body: HearBody) -> dict:
    text = body.script
    if text is None:
        try:
            path = takes.take_path(body.take_id or "") / "script.md"
        except ValueError as exc:
            raise HTTPException(400, "give a script or a take") from exc
        if not path.exists():
            raise HTTPException(404, "that take has no script")
        text = path.read_text(encoding="utf-8")
    settings = _settings(text, body.settings)
    script = parse_script(text)
    if not 0 <= body.line_index < len(script.lines):
        raise HTTPException(400, "no such line in the script")
    median, source = _median(body.take_id)
    if body.version == "marked":
        return delivery.marked_plan(script, body.line_index, settings, median, source)
    line = script.lines[body.line_index]
    ref, note, _ = delivery._reference(settings, median, source)
    proposal, provider = await run_in_threadpool(_coach_proposal, script, line, settings, ref, note)
    return delivery.coach_plan(script, body.line_index, settings, proposal, provider, median, source)


class AcceptBody(BaseModel):
    script: str
    line_index: int
    suggestions: list[dict]


@router.post("/hear/accept")
async def hear_accept(body: AcceptBody) -> dict:
    """Turn accepted coach suggestions that have a mark equivalent (/, //, *word*) into marks in the script."""
    from take_two.suggest import apply_marks
    script = parse_script(body.script)
    if not 0 <= body.line_index < len(script.lines):
        raise HTTPException(400, "no such line in the script")
    rows = delivery.accept_rows(script, body.line_index, body.suggestions)
    return {"text": apply_marks(body.script, rows), "applied": len(rows)}


class ScriptBody(BaseModel):
    script: str


@router.post("/pronounce")
async def pronounce_words(body: ScriptBody) -> dict:
    return await run_in_threadpool(pronounce.propose, parse_script(body.script), get_llm())


class ConfirmBody(BaseModel):
    script: str
    word: str
    respelling: str
    ipa: str | None = None


@router.post("/pronounce/confirm")
async def pronounce_confirm(body: ConfirmBody) -> dict:
    """Write the confirmed pronunciation as a [SAY] mark at the end of the word's first line,
    replacing any earlier [SAY] mark for the same word."""
    resp = " ".join(body.respelling.split())
    if not pronounce.RESPELL_RE.match(resp):
        raise HTTPException(400, "a respelling is letters, hyphens, spaces and apostrophes (e.g. KOH-ral)")
    script = parse_script(body.script)
    key = clarity.word_key(body.word)
    if not key:
        raise HTTPException(400, "no word given")
    lines = body.script.splitlines()
    for ln in script.lines:  # drop earlier marks for this word
        raw = lines[ln.raw_line_no]
        lines[ln.raw_line_no] = SAY_RE.sub(lambda m: "" if clarity.word_key(m.group("word")) == key else m.group(0), raw).rstrip()
    def said(ln) -> str:  # the line's words with possessives dropped, so Maya's finds Maya
        return " " + " ".join(clarity.word_key(re.sub(r"['’]s(?=\W*$)", "", t.text)) for t in ln.tokens) + " "
    target = next((ln for ln in script.lines if f" {key} " in said(ln)), None)
    if target is None:
        raise HTTPException(400, f"“{body.word}” is not in the script")
    lines[target.raw_line_no] = lines[target.raw_line_no].rstrip() + " " + say_mark(body.word, resp, body.ipa)
    return {"text": "\n".join(lines) + ("\n" if body.script.endswith("\n") else "")}


@router.get("/clarity/dismissed")
async def clarity_dismissed() -> dict:
    return {"words": sorted(clarity.load_dismissed())}


class DismissBody(BaseModel):
    word: str
    dismissed: bool = True


@router.post("/clarity/dismissed")
async def clarity_dismiss(body: DismissBody) -> dict:
    return {"words": sorted(clarity.set_dismissed(body.word, body.dismissed))}


@router.get("/tts")
async def tts_status() -> dict:
    return tts.status()


class TtsBody(BaseModel):
    plan: dict
    consent: bool = False


@router.post("/tts")
async def tts_speak(body: TtsBody) -> Response:
    """Speak a plan with the configured server voice. A cloud voice needs the speaker's consent on the request."""
    st = tts.status()
    if not st["available"]:
        raise HTTPException(409, st["reason"])
    if st["sends"] and not body.consent:
        raise HTTPException(403, f"This voice sends {st['sends']}; the request did not carry your consent.")
    try:
        audio, media = await run_in_threadpool(tts.synthesize, body.plan)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(audio, media_type=media, headers={"Cache-Control": "no-store"})

