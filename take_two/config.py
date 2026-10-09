"""Environment configuration and user-adjustable thresholds."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
TAKES_DIR = Path(os.environ.get("TAKE_TWO_TAKES_DIR", ROOT / "takes"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
SAMPLE_SCRIPT = ROOT / "sample_script.md"
EXAMPLES_DIR = ROOT / "examples"

STT_BACKEND = os.environ.get("TAKE_TWO_STT", "local")  # local | openai
STT_MODEL = os.environ.get("TAKE_TWO_STT_MODEL", "small.en")
STT_DEVICE = os.environ.get("TAKE_TWO_STT_DEVICE", "auto")  # auto | cuda | cpu
STT_VAD_FILTER = os.environ.get("TAKE_TWO_STT_VAD_FILTER", "1") not in ("0", "false", "no")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("TAKE_TWO_ANTHROPIC_MODEL", "claude-opus-5-5")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_MODE = os.environ.get("TAKE_TWO_LLM", "auto")  # auto | fake (development stand-in for the suggestion UI)


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
    # Improvise mode: there are no marks to compare against, so these are reference
    # bands the user can edit, not targets the app knows to be right.
    improv_wpm_min: float = Field(130.0, ge=40.0, le=400.0)
    improv_wpm_max: float = Field(170.0, ge=40.0, le=400.0)
    improv_goal_tolerance_pct: float = Field(10.0, ge=0.0, le=100.0)
    improv_filler_per_100: float = Field(2.0, ge=0.0, le=100.0)
    improv_hedge_per_100: float = Field(1.5, ge=0.0, le=100.0)
    improv_hesitation_pause_s: float = Field(1.2, ge=0.3, le=10.0)
    improv_hesitations_per_min: float = Field(2.0, ge=0.0, le=60.0)
    improv_uptalk_st: float = Field(2.0, ge=0.5, le=12.0)
    improv_trail_db: float = Field(6.0, ge=1.0, le=30.0)
    improv_tone_share_pct: float = Field(20.0, ge=0.0, le=100.0)
    improv_clarity_prob: float = Field(0.5, ge=0.05, le=0.95)
    improv_unclear_pct: float = Field(3.0, ge=0.0, le=100.0)
    improv_pitch_range_st: float = Field(5.0, ge=0.5, le=24.0)
    improv_loudness_var_db: float = Field(2.5, ge=0.0, le=20.0)
    improv_pace_var_pct: float = Field(10.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _band_order(self) -> "Settings":
        if self.conventions_wpm_min > self.conventions_wpm_max:
            raise ValueError("conventions_wpm_min must not exceed conventions_wpm_max")
        if self.improv_wpm_min > self.improv_wpm_max:
            raise ValueError("improv_wpm_min must not exceed improv_wpm_max")
        return self
