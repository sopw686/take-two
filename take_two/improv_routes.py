"""Improvise API: topics, new takes, re-analysis and coaching. Mounted at /api/improv."""

from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError

from take_two import pipeline, takes
from take_two.config import Settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/improv")

MAX_TOPIC = 200
GOAL_RANGE = (10.0, 1800.0)


def _settings(raw: str | None) -> Settings:
    if not raw:
        return Settings()
    try:
        return Settings.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(400, f"bad settings: {exc}") from exc


def _improv_take(take_id: str) -> dict:
    try:
        data = takes.load_take(take_id)
    except ValueError:
        raise HTTPException(400, "bad take id")
    if data is None:
        raise HTTPException(404, "take not found")
    if data.get("mode") != "improv":
        raise HTTPException(400, "not an Improvise take")
    return data


class QuestionsBody(BaseModel):
    script: str


@router.post("/questions")
async def questions(body: QuestionsBody) -> dict:
    """Likely audience questions about the script (model reads the script text only)."""
    from take_two.llm import get_llm, llm_status
    from take_two.marks import parse_script
    from take_two.questions import SYSTEM, QuestionsOutput, build_user_prompt, validate_questions

    llm = get_llm()
    if not llm.available:
        return {"available": False, "reason": llm_status()["reason"], "questions": [], "dropped": []}
    script = parse_script(body.script.replace("\r\n", "\n"))
    if not script.lines:
        return {"available": True, "reason": "The script is empty.", "questions": [], "dropped": []}
    out = await run_in_threadpool(llm.complete_structured, SYSTEM, build_user_prompt(script), QuestionsOutput)
    if out is None:
        return {"available": True, "reason": "The model did not return usable questions. Try again.", "questions": [], "dropped": []}
    kept, dropped = validate_questions(out, script)
    return {"available": True, "questions": kept, "dropped": dropped, "proposed": len(out.questions)}


class FollowupBody(BaseModel):
    script: str = ""  # only to check quotes; the model never sees it


@router.post("/{take_id}/followup")
async def followup(take_id: str, body: FollowupBody | None = None) -> dict:
    """The spoken examiner's one follow-up to this answer (model reads the transcript text and numbers only)."""
    from take_two.examiner import ask_followup
    from take_two.llm import get_llm
    _improv_take(take_id)
    return await run_in_threadpool(ask_followup, take_id, get_llm(), (body.script if body else "") or "")


@router.get("/session/{session_id}")
async def session(session_id: str, skipped: int = 0) -> dict:
    """A spoken-examiner session: its answers and the closing line, written by code from the measurements."""
    from take_two.examiner import closing_line, session_answers
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", session_id):
        raise HTTPException(400, "bad session id")
    answers = await run_in_threadpool(session_answers, session_id)
    rows = [{"take_id": a["take_id"], "label": a.get("label", ""), "question": a.get("topic", ""),
             "followup_of": (a.get("session") or {}).get("followup_of"),
             "pace_status": ((a.get("improv") or {}).get("pace") or {}).get("status")} for a in answers]
    return {"answers": rows, "closing": closing_line(answers, max(0, min(skipped, 6)))}


@router.get("/topics")
async def topics() -> dict:
    from take_two.topics import CATEGORIES, TOPICS
    return {"categories": CATEGORIES, "topics": TOPICS}


def clean_topic(topic: str) -> str:
    topic = " ".join(topic.split())
    if not topic:
        raise HTTPException(400, "topic is empty")
    if len(topic) > MAX_TOPIC:
        raise HTTPException(400, f"topic is longer than {MAX_TOPIC} characters")
    return topic


def check_goal(goal_s: float | None) -> float | None:
    if goal_s is not None and not (GOAL_RANGE[0] <= goal_s <= GOAL_RANGE[1]):
        raise HTTPException(400, f"goal must be between {GOAL_RANGE[0]:.0f} and {GOAL_RANGE[1]:.0f} seconds")
    return goal_s


def parse_question(raw: str | None, topic: str) -> dict | None:
    """The question this take answers ({text, tag, line_index, line_text}), when it came from a script.

    The topic is the question text; tag and line are kept for the report. A typed question
    has no tag or line.
    """
    if not raw:
        return None
    try:
        q = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "bad question")
    if not isinstance(q, dict):
        raise HTTPException(400, "bad question")
    from take_two.questions import TAGS
    tag = q.get("tag") if q.get("tag") in TAGS else None
    li = q.get("line_index")
    line = li if isinstance(li, int) and not isinstance(li, bool) and li >= 0 else None
    line_text = str(q.get("line_text") or "")[:300] if line is not None else ""
    return {"text": topic, "tag": tag, "line_index": line, "line_text": line_text}


def parse_session(raw: str | None) -> dict | None:
    """{id, index, total, followup_of}: which spoken-examiner session an answer belongs to. A session is a
    group of ordinary Improvise takes; this is its only trace, in the take's improv.json."""
    if not raw:
        return None
    try:
        s = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "bad session")
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9-]{1,40}", s["id"]):
        raise HTTPException(400, "bad session")
    num = lambda k, lo, hi: s.get(k) if isinstance(s.get(k), int) and not isinstance(s.get(k), bool) and lo <= s[k] <= hi else None  # noqa: E731
    fu = s.get("followup_of")
    return {"id": s["id"], "index": num("index", 0, 5), "total": num("total", 3, 6),
            "followup_of": fu if isinstance(fu, str) and takes.TAKE_ID_RE.fullmatch(fu) else None}


async def new_improv_take(audio: UploadFile, topic: str, goal_s: float | None, content: bool, settings: str | None,
                          label: str, question: str | None = None, session: str | None = None) -> tuple[str, Settings]:
    """Validate an Improvise take and create its folder (upload, topic, settings) before any processing."""
    st = _settings(settings)
    topic = clean_topic(topic)
    check_goal(goal_s)
    q = parse_question(question, topic)
    sess = parse_session(session)
    data = await audio.read()
    if not data:
        raise HTTPException(400, "the recording is empty")
    take_id = takes.new_take("improv", upload=data, original_name=audio.filename or "take.webm",
                             settings=st.model_dump(), label=label,
                             improv={"topic": topic, "goal_s": goal_s, "content": content, "question": q,
                                     **({"session": sess} if sess else {})})
    return take_id, st


@router.post("")
async def create(audio: UploadFile = File(...), topic: str = Form(...), goal_s: float | None = Form(None),
                 content: bool = Form(False), settings: str | None = Form(None), label: str = Form(""),
                 question: str | None = Form(None)) -> dict:
    from take_two.app import process

    take_id, st = await new_improv_take(audio, topic, goal_s, content, settings, label, question)
    return await process(take_id, st)


class ReanalyzeBody(BaseModel):
    settings: Settings = Settings()
    label: str | None = None


@router.post("/{take_id}/reanalyze")
async def reanalyze(take_id: str, body: ReanalyzeBody) -> dict:
    _improv_take(take_id)
    if takes.is_busy(take_id):
        raise HTTPException(409, "this take is being analyzed right now")
    return await run_in_threadpool(pipeline.reanalyze_improv, take_id, body.settings, body.label)


class CoachBody(BaseModel):
    content: bool | None = None  # None: use the choice made when the take was recorded


@router.post("/{take_id}/coach")
async def coach(take_id: str, body: CoachBody | None = None) -> dict:
    from take_two.improv_coach import coach_improv
    from take_two.llm import get_llm
    from take_two.stt.base import Transcript

    data = _improv_take(take_id)
    content = data.get("content", False) if body is None or body.content is None else body.content
    tdir = takes.take_path(take_id)
    transcript = Transcript.from_dict(takes.load_json(tdir / "transcript.json"))
    history = takes.improv_history(take_id)
    res = await run_in_threadpool(coach_improv, data, transcript, get_llm(), history, content)

    def attach(current: dict) -> dict | None:
        if current.get("settings") != data.get("settings"):
            return None  # re-analyzed under other bands while the model answered; its numbers win
        current.update(res)
        if not content:
            current.pop("content_review", None)
        current["content"] = content
        return current
    def save() -> dict | None:
        with takes.take_lock(take_id):
            meta = takes.load_json(tdir / "improv.json")
            meta["content"] = content
            takes.save_json(tdir / "improv.json", meta)
            return takes.update_analysis(take_id, attach)
    return (await run_in_threadpool(save)) or data
