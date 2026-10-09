"""Focus for the next take: at most three marks to work on, written by code from the measurements.

Marks that diverged in two or more takes of the same script come first (most takes first),
then this take's largest divergences. Every item names the mark and cites the measured number
behind it. No model is involved, so this works without a key. Wording follows the rest of the
report: "diverged from your mark", "faster/slower than your median"; never a grade.
"""

from __future__ import annotations

from take_two.coaching import all_marks_met
from take_two.compare import DIVERGED, _key_marks
from take_two.marks import format_budget

MAX_ITEMS = 3
# Statuses that are not met but not a full divergence either.
CLOSE = {"near", "short"}


def _short(text: str, n: int = 40) -> str:
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _fmt_s(seconds: float) -> str:
    return format_budget(seconds) if seconds >= 60 else f"{seconds:.1f} s"


def _candidates(a: dict) -> list[dict]:
    """Marks of this take that did not meet their target, with the text and a 0..1 size of the gap."""
    out: list[dict] = []
    for r in a.get("lines", []):
        k = r.get("key")
        if not k or k["status"] not in ("diverged", "near"):
            continue
        label = f"KEY line {r['index'] + 1} (“{_short(r['text'])}”)"
        parts, gaps = [], []
        pct = k.get("wpm_vs_median_pct")
        if k["rate_status"] in ("diverged", "near") and pct is not None:
            parts.append(f"{abs(pct):.0f}% {'faster' if pct > 0 else 'slower'} than your median of {k['median_wpm']:.0f} wpm; "
                         f"your mark asks for at least {k['slower_target_pct']:.0f}% slower")
            gaps.append((pct + k["slower_target_pct"]) / 100.0)
        p, target = k.get("pause_after_s"), k.get("pause_after_target_s")
        if k["pause_status"] in ("short", "missing") and p is not None and target:
            parts.append(f"{p:.1f} s of silence after it against your {target:.1f} s mark")
            gaps.append((target - p) / target)
        if not parts:
            continue  # nothing measured to cite (e.g. no median in this take)
        out.append({"key": ("KEY", r["index"]), "kind": "KEY", "mark": label, "status": k["status"],
                    "text": f"{label}: " + "; ".join(parts) + ".", "gap": _clamp(max(gaps)), "order": (r["index"], 0)})
    for p in a.get("pauses", []):
        if p["status"] not in ("short", "missing") or p.get("measured_s") is None:
            continue
        label = f"The {p['kind']} in line {p['line'] + 1}"
        around = f" (between “{p.get('before') or ''}” and “{p.get('after') or ''}”)" if p.get("before") else ""
        out.append({"key": (p["kind"], p["line"], p["word_index"]), "kind": p["kind"], "mark": label, "status": p["status"],
                    "text": f"{label}{around}: {p['measured_s']:.2f} s of silence against your {p['target_s']:.1f} s mark.",
                    "gap": _clamp((p["target_s"] - p["measured_s"]) / p["target_s"]), "order": (p["line"], 1 + p["word_index"])})
    for s in a.get("sections", []):
        if s["status"] not in ("over", "under") or s.get("delta_s") is None or not s.get("budget_s"):
            continue
        d = s["delta_s"]
        text = f"Section {s['name']} ran {format_budget(abs(d))} {'over' if d > 0 else 'under'} its {s['budget_label']} budget."
        cut = s.get("cut") or {}
        if d > 0 and cut.get("words"):
            text += f" That is about {cut['words']} words at your {cut['wpm']:.0f} wpm."
        out.append({"key": ("section", s["name"]), "kind": "section", "mark": f"Section {s['name']}", "status": s["status"],
                    "text": text, "gap": _clamp(abs(d) / s["budget_s"]), "order": (s["line_start"], -1)})
    for d in a.get("defines", []):
        if d["status"] not in ("undefined", "never_spoken"):
            continue
        label = f"DEFINE: {d['term']}"
        if d["status"] == "undefined":
            text = (f"{label} (line {d['line'] + 1}): first said at {_fmt_s(d['first_spoken_at'])} with no definition "
                    f"found at or before it ({d.get('method', 'heuristic')} check).")
        else:
            text = f"{label} (line {d['line'] + 1}): not said anywhere in this {_fmt_s(a.get('duration_s') or 0)} take."
        out.append({"key": ("DEFINE", d["term"].lower()), "kind": "DEFINE", "mark": label, "status": d["status"],
                    "text": text, "gap": 0.5, "order": (d["line"], 2)})
    return out


def focus(analysis: dict, earlier: list[dict] | None = None) -> dict:
    """{all_met, items: [{mark, kind, status, text, repeat, takes}], note}. earlier: older takes of the same script."""
    group = list(earlier or []) + [analysis]
    counts: dict[tuple, int] = {}
    for a in group:
        for key, m in _key_marks(a).items():
            if m["status"] in DIVERGED.get(m["kind"], ()):
                counts[key] = counts.get(key, 0) + 1
    cands = _candidates(analysis)
    for c in cands:
        c["repeat"] = counts.get(c["key"], 0)
    cands.sort(key=lambda c: (0 if c["repeat"] >= 2 else 1, -c["repeat"], 1 if c["status"] in CLOSE else 0,
                              -c["gap"], c["order"]))
    items = [{"mark": c["mark"], "kind": c["kind"], "status": c["status"], "text": c["text"],
              "repeat": c["repeat"], "takes": len(group)} for c in cands[:MAX_ITEMS]]
    if items:
        return {"all_met": False, "items": items, "note": None}
    if all_marks_met(analysis):
        return {"all_met": True, "items": [], "note": "Everything met its mark in this take."}
    return {"all_met": False, "items": [],
            "note": "Nothing that was measured diverged from its mark; some marks could not be measured in this take."}
