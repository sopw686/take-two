"""Post-take coaching: at most three suggestions written from the measured
analysis JSON (never audio). Each must cite a measured number and the mark it
concerns, and must not introduce norms the user did not choose. If everything
met its marks the model says so and suggests nothing.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from marked.marks import format_budget


class CoachSuggestion(BaseModel):
    text: str = Field(description="One or two sentences citing a measured number and naming the mark/line/section.")
    mark: str = Field(default="", description="Which mark or section this is about, e.g. 'KEY line 6', '// in line 2', 'section Methods'.")
    metric: str = Field(default="", description="The measured figure cited, e.g. '22% faster than your median'.")


class CoachOutput(BaseModel):
    all_met: bool
    suggestions: list[CoachSuggestion] = Field(description="At most three. Empty if all marks were met.")


SYSTEM = """You coach a speaker on ONE thing only: how their rehearsal take compared with the marks they themselves set. You receive measurements, not audio. Write at most three suggestions. Each must cite a specific measured number from the data and name the mark or section it concerns. Compare only against the speaker's own marks and their own median rate; never introduce a general norm (no 'ideal pace', no filler-word advice, no 'speak with more energy') unless the data includes a preset the speaker switched on. Use plain, non-judgmental wording: 'diverged from your mark', 'faster than your median', 'ran over budget'. Never grade or score. If every mark was met, say so and return no suggestions. Do not claim to know how the take sounded emotionally."""


def compact_measurements(analysis: dict, history: list[dict] | None = None) -> dict:
    """The subset of the analysis the model needs: marks and their measured outcomes."""
    def line_row(r: dict) -> dict:
        d = {"line": r["index"], "text": r["text"][:90], "status": r["status"], "wpm": r.get("wpm")}
        if r.get("key"):
            k = r["key"]
            d["key"] = {kk: k.get(kk) for kk in ("status", "rate_status", "pause_status", "wpm", "median_wpm",
                                                "wpm_vs_median_pct", "pause_after_s", "pause_after_target_s", "slower_target_pct")}
        return d

    out = {
        "baseline": analysis.get("baseline"),
        "settings": {k: v for k, v in analysis.get("settings", {}).items() if not k.startswith("conventions") or analysis.get("settings", {}).get("conventions_enabled")},
        "sections": [{k: s.get(k) for k in ("name", "budget_s", "duration_s", "delta_s", "status")} for s in analysis.get("sections", [])],
        "lines": [line_row(r) for r in analysis.get("lines", []) if r.get("key") or r.get("status") != "ok"],
        "pauses": [{k: p.get(k) for k in ("line", "kind", "target_s", "measured_s", "status", "before", "after")} for p in analysis.get("pauses", [])],
        "defines": [{k: d.get(k) for k in ("term", "status", "first_spoken_at", "method")} for d in analysis.get("defines", [])],
        "summary": analysis.get("summary"),
    }
    if analysis.get("conventions"):
        c = analysis["conventions"]
        out["conventions_preset_user_switched_on"] = {k: c.get(k) for k in ("overall_wpm", "wpm_band", "wpm_status", "filler_count", "filler_per_100", "filler_target_per_100", "filler_status")}
    if history:
        out["earlier_takes_same_script"] = history
    return out


def history_for(analysis: dict, earlier: list[dict]) -> list[dict]:
    """Per earlier take: the KEY and pause outcomes, so the model can say 'in 3 of 4 takes'."""
    rows = []
    for a in earlier:
        rows.append({
            "take_id": a.get("take_id"), "created_at": a.get("created_at"),
            "keys": [{"line": r["index"], "status": r["key"]["status"], "wpm_vs_median_pct": r["key"].get("wpm_vs_median_pct")}
                     for r in a.get("lines", []) if r.get("key")],
            "pauses": [{"line": p["line"], "kind": p["kind"], "status": p["status"], "measured_s": p.get("measured_s")} for p in a.get("pauses", [])],
            "sections": [{"name": s["name"], "status": s["status"], "delta_s": s.get("delta_s")} for s in a.get("sections", [])],
        })
    return rows


_NUM = re.compile(r"\d")


def validate(out: CoachOutput | None, analysis: dict) -> dict:
    if out is None:
        return {"available": True, "reason": "The model did not return usable suggestions.", "suggestions": [], "all_met": None}
    kept = []
    for s in out.suggestions:
        if len(kept) >= 3:
            break
        if not _NUM.search(s.text + " " + s.metric):
            continue  # must cite a measured number
        kept.append({"text": s.text.strip(), "mark": s.mark.strip(), "metric": s.metric.strip()})
    return {"available": True, "suggestions": kept, "all_met": bool(out.all_met) and not kept}


def all_marks_met(analysis: dict) -> bool:
    for r in analysis.get("lines", []):
        if r.get("key") and r["key"]["status"] not in ("met",):
            return False
    for p in analysis.get("pauses", []):
        if p["status"] not in ("met", "unmeasurable"):
            return False
    for s in analysis.get("sections", []):
        if s["status"] in ("over", "under"):
            return False
    for d in analysis.get("defines", []):
        if d["status"] in ("undefined", "never_spoken"):
            return False
    return True


def describe_budget(seconds: float | None) -> str:
    return format_budget(seconds)


def coach(analysis: dict, llm, earlier: list[dict] | None = None) -> dict:
    if not getattr(llm, "available", False):
        return {"available": False, "reason": "No ANTHROPIC_API_KEY set.", "suggestions": []}
    if all_marks_met(analysis):
        return {"available": True, "suggestions": [], "all_met": True,
                "reason": "Everything met its marks in this take; nothing to suggest."}
    data = compact_measurements(analysis, history_for(analysis, earlier or []))
    user = "Measurements for the latest take (JSON):\n" + json.dumps(data, indent=1) + "\n\nWrite at most three suggestions, or none if all marks were met."
    out = llm.complete_structured(SYSTEM, user, CoachOutput, max_tokens=1500)
    return validate(out, analysis)
