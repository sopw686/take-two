"""Opt-in "conference conventions" preset. Off by default; only computed when the
user switches it on. Stub until milestone 6."""

from __future__ import annotations

from marked.config import Settings
from marked.stt.base import Transcript


def conventions_report(transcript: Transcript, analysis: dict, settings: Settings) -> dict:
    return {"enabled": True, "status": "not_implemented"}
