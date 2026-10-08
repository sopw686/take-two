"""Environment configuration and user-adjustable thresholds."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
TAKES_DIR = Path(os.environ.get("MARKED_TAKES_DIR", ROOT / "takes"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
SAMPLE_SCRIPT = ROOT / "sample_script.md"

STT_BACKEND = os.environ.get("MARKED_STT", "local")  # local | openai
STT_MODEL = os.environ.get("MARKED_STT_MODEL", "small.en")
STT_DEVICE = os.environ.get("MARKED_STT_DEVICE", "auto")  # auto | cuda | cpu
STT_VAD_FILTER = os.environ.get("MARKED_STT_VAD_FILTER", "1") not in ("0", "false", "no")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("MARKED_ANTHROPIC_MODEL", "claude-opus-5-5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODE = os.environ.get("MARKED_LLM", "auto")  # auto | fake (development stand-in for the suggestion UI)


class Settings(BaseModel):
    """Thresholds the user can adjust. Every default here is a starting point,
    not a norm: the user sets the targets."""

    short_pause_s: float = Field(0.7, ge=0.1, le=5.0)
    long_pause_s: float = Field(1.5, ge=0.1, le=10.0)
    pause_near_ratio: float = Field(0.4, ge=0.0, le=1.0)
    key_slower_pct: float = Field(10.0, ge=0.0, le=80.0)
    key_pause_after_s: float = Field(0.7, ge=0.0, le=10.0)
    line_min_coverage: float = Field(0.5, ge=0.1, le=1.0)
    baseline_min_words: int = Field(4, ge=1, le=20)
    section_tolerance_pct: float = Field(10.0, ge=0.0, le=100.0)
    min_silence_s: float = Field(0.15, ge=0.05, le=1.0)
    conventions_enabled: bool = False
    conventions_wpm_min: float = Field(130.0, ge=40.0, le=400.0)
    conventions_wpm_max: float = Field(170.0, ge=40.0, le=400.0)
    conventions_filler_per_100: float = Field(3.0, ge=0.0, le=100.0)
    emphasis_enabled: bool = False
