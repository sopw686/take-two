"""Improvise API: topics, new takes, re-analysis and coaching. Mounted at /api/improv."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ValidationError

from marked import pipeline, takes
from marked.config import Settings

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


@router.get("/topics")
async def topics() -> dict:
    from marked.topics import CATEGORIES, TOPICS
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


@router.post("")
async def create(audio: UploadFile = File(...), topic: str = Form(...), goal_s: float | None = Form(None),
                 content: bool = Form(False), settings: str | None = Form(None), label: str = Form("")) -> dict:
    from marked.app import process

    st = _settings(settings)
    topic = clean_topic(topic)
    check_goal(goal_s)
    data = await audio.read()
    if not data:
        raise HTTPException(400, "the recording is empty")
    take_id = takes.new_take("improv", upload=data, original_name=audio.filename or "take.webm",
                             settings=st.model_dump(), label=label,
                             improv={"topic": topic, "goal_s": goal_s, "content": content})
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
    from marked.improv_coach import coach_improv
    from marked.llm import get_llm
    from marked.stt.base import Transcript

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
