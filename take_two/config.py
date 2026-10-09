"""Environment configuration and user-adjustable thresholds."""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

ROOT = Path(__file__).resolve().parent.parent
TAKES_DIR = Path(os.environ.get("TAKE_TWO_TAKES_DIR", ROOT / "takes"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
SAMPLE_SCRIPT = ROOT / "sample_script.md"
EXAMPLES_DIR = ROOT / "examples"
# Scripts offered under "Start from an example" on the Script tab: (id, label, file). The toast and the poem were written for the demo.
SCRIPT_EXAMPLES: list[tuple[str, str, Path]] = [
    ("talk", "Science talk: coral reefs (placeholder)", SAMPLE_SCRIPT),
    ("toast", "Wedding toast (written for the demo)", EXAMPLES_DIR / "scripts" / "toast.md"),
    ("slam", "Slam poem (written for the demo)", EXAMPLES_DIR / "scripts" / "slam_poem.md"),
    ("demo", "The demo speech: a talk about Take Two", ROOT / "demo_speech.md"),
]

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
    # Alignment: a misheard word matches its script word at this character similarity (1.0 = exact only),
    # and a line too reworded to align is still timed when this much of it was spoken between found neighbours.
    fuzzy_match_ratio: float = Field(0.8, ge=0.6, le=1.0)
    fuzzy_min_chars: int = Field(4, ge=3, le=10)
    paraphrase_min_words_pct: float = Field(30.0, ge=0.0, le=100.0)
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
    # Hear it: a synthetic voice demonstrates a line. The baseline is used only before you have a take of
    # your own (and is labelled as such); a register is off until you pick one; the coach's amounts are yours.
    hear_baseline_wpm: float = Field(150.0, ge=80.0, le=250.0)
    hear_register: Literal["none", "technical", "celebratory", "slam", "pitch"] = "none"
    coach_slow_pct: float = Field(25.0, ge=5.0, le=60.0)
    coach_pause_s: float = Field(0.6, ge=0.1, le=3.0)
    # Words that may not have been clear: recognizer confidence below clarity_prob, or heard as another word.
    # A low-confidence word that matched the script exactly is skipped when clarity_context_words words on
    # each side also matched exactly with high confidence (0 turns the skip off).
    clarity_prob: float = Field(0.5, ge=0.05, le=0.95)
    clarity_context_words: int = Field(2, ge=0, le=5)

    @model_validator(mode="after")
    def _band_order(self) -> "Settings":
        if self.conventions_wpm_min > self.conventions_wpm_max:
            raise ValueError("conventions_wpm_min must not exceed conventions_wpm_max")
        if self.improv_wpm_min > self.improv_wpm_max:
            raise ValueError("improv_wpm_min must not exceed improv_wpm_max")
        return self


# ---- settings carried in the script ------------------------------------------------------------
# An optional first line such as  <!-- take-two: short_pause_s=0.8 key_slower_pct=15 -->  sets thresholds
# for takes of that script, over the Settings dialog. The parser already blanks comments, so line
# numbers do not move. "marked:" is accepted too (the app's earlier name).

_SETTINGS_START = re.compile(r"\s*<!--\s*(?:take-two|taketwo|marked)\s*:", re.IGNORECASE)
_SETTINGS_LINE = re.compile(r"\s*<!--\s*(?:take-two|taketwo|marked)\s*:(?P<body>(?:(?!-->).)*)-->\s*", re.IGNORECASE)


class ScriptSettingsError(ValueError):
    """The script's settings line names an unknown setting or an invalid value."""


def settings_line(text: str) -> str | None:
    """The script's first non-blank line, if it is a settings comment."""
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if _SETTINGS_LINE.fullmatch(first):
        return first
    if _SETTINGS_START.match(first):
        if "-->" in first:
            raise ScriptSettingsError("nothing may follow --> on the script's settings line; start the script on the next line")
        raise ScriptSettingsError("the script's settings line must close with --> on the same line")
    return None


def script_overrides(text: str) -> dict:
    """{setting: value} from the script's settings line ({} without one). Raises ScriptSettingsError."""
    line = settings_line(text)
    if line is None:
        return {}
    m = _SETTINGS_LINE.fullmatch(line)
    assert m is not None
    raw: dict[str, str] = {}
    for pair in m.group("body").split():
        if "=" not in pair:
            raise ScriptSettingsError(f"“{pair}” in the script's settings line is not name=value")
        key, value = pair.split("=", 1)
        if key in raw:
            raise ScriptSettingsError(f"“{key}” is set twice in the script's settings line")
        if key not in Settings.model_fields:
            close = difflib.get_close_matches(key, list(Settings.model_fields), n=1)
            raise ScriptSettingsError(f"unknown setting “{key}” in the script's settings line"
                                      + (f" (the nearest name is {close[0]})" if close else " (the README lists every setting)"))
        raw[key] = value
    out = {}
    for key, value in raw.items():
        field = Settings.model_fields[key]
        try:  # each value against its own type and bounds; how values combine is checked with the dialog's settings
            kind = Annotated[field.annotation, *field.metadata] if field.metadata else field.annotation
            out[key] = TypeAdapter(kind).validate_python(value)
        except ValidationError as exc:
            raise ScriptSettingsError(f"the script's settings line sets {key} to “{value}”: "
                                      f"{exc.errors()[0].get('msg', 'not a valid value')}") from exc
    return out


def effective_settings(requested: Settings, script_text: str) -> tuple[Settings, dict]:
    """(settings to analyze with, the values that came from the script). Script > request > defaults."""
    over = script_overrides(script_text)
    if not over:
        return requested, {}
    try:
        return Settings.model_validate({**requested.model_dump(), **over}), over
    except ValidationError as exc:  # e.g. a pace band the script and the dialog together turn upside down
        msg = str(exc.errors()[0].get("msg", "")).removeprefix("Value error, ")
        raise ScriptSettingsError(f"the script's settings line conflicts with your other settings: {msg}") from exc
