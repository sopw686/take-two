"""Take history: compare takes of the same script mark by mark."""

from __future__ import annotations

from collections import Counter

# Statuses that count as missing a mark, by kind, for counting repeats across takes. Shared with focus.py,
# which ranks the "close" ones ("short", "under") after full divergences.
DIVERGED = {"KEY": {"diverged"}, "/": {"short", "missing"}, "//": {"short", "missing"},
            "section": {"over", "under"}, "DEFINE": {"undefined", "never_spoken"}}


def _key_marks(a: dict) -> dict[tuple, dict]:
    """Marks of one take keyed by their position in the script, with the moment to play for each (at, until)."""
    out = {}
    lines = {r["index"]: r for r in a.get("lines", [])}
    for r in a.get("lines", []):
        if r.get("key"):
            out[("KEY", r["index"])] = {"kind": "KEY", "line": r["index"], "text": r["text"], "status": r["key"]["status"],
                                        "value": r["key"].get("wpm_vs_median_pct"), "at": r.get("start"), "until": r.get("end")}
    for p in a.get("pauses", []):
        w = p.get("window") or [None, None]
        out[(p["kind"], p["line"], p["word_index"])] = {"kind": p["kind"], "line": p["line"], "word_index": p["word_index"],
                                                       "status": p["status"], "value": p.get("measured_s"),
                                                       "text": f"{p.get('before') or ''} {p['kind']} {p.get('after') or ''}".strip(),
                                                       "at": w[0], "until": w[1]}
    for s in a.get("sections", []):
        first = lines.get(s.get("line_start"), {})
        out[("section", s["name"])] = {"kind": "section", "name": s["name"], "status": s["status"], "value": s.get("delta_s"),
                                       "text": s["name"], "at": s.get("start"), "until": first.get("end")}
    for d in a.get("defines", []):
        ev = d.get("evidence") or {}
        out[("DEFINE", d["term"].lower())] = {"kind": "DEFINE", "term": d["term"], "status": d["status"], "value": None, "text": d["term"],
                                              "at": ev.get("start", d.get("first_spoken_at")), "until": ev.get("end")}
    return out


def compare_takes(analyses: list[dict]) -> dict:
    """analyses ordered oldest -> newest. Marks are matched by position in the script."""
    per_take = [_key_marks(a) for a in analyses]
    keys: list[tuple] = []
    for m in per_take:
        for k in m:
            if k not in keys:
                keys.append(k)
    marks = []
    for k in keys:
        rows = [m.get(k) for m in per_take]
        present = [r for r in rows if r]
        statuses = [r["status"] for r in present]
        base = {kk: vv for kk, vv in present[-1].items() if kk not in ("status", "value", "at", "until")}
        # Per-take lists line up with the takes (None where a take does not have the mark), so the table can index them.
        marks.append({**base, "takes": len(present), "statuses": [r["status"] if r else None for r in rows],
                      "values": [r["value"] if r else None for r in rows],
                      "times": [[r.get("at"), r.get("until")] if r else None for r in rows],
                      "met": sum(1 for s in statuses if s == "met"), "latest": statuses[-1] if statuses else None})
    summary: list[str] = []
    for m in marks:
        n = m["takes"]
        if n < 2:
            continue
        c = Counter(m["statuses"])
        if m["kind"] == "KEY":
            t = m["text"]
            label = f"key line {m['line'] + 1} (“{t[:40]}…”)" if len(t) > 40 else f"key line {m['line'] + 1} (“{t}”)"
        elif m["kind"] in ("/", "//"):
            label = f"the {m['kind']} in line {m['line'] + 1}"
        elif m["kind"] == "section":
            label = f"section {m['name']}"
        else:
            label = f"“{m['term']}”"
        if m["kind"] in ("KEY", "/", "//"):
            bad = sum(n for s, n in c.items() if s in DIVERGED[m["kind"]])
            if bad >= 2:
                if m["kind"] == "KEY":
                    # "Rushed" only for takes that diverged AND ran faster than the median; other divergences
                    # (e.g. a missing pause after the line) are reported as such.
                    rushed = sum(1 for s, v in zip(m["statuses"], m["values"]) if s == "diverged" and v is not None and v > 0)
                    other = bad
                    if rushed >= 2:
                        summary.append(f"You rushed {label} in {rushed} of {n} takes.")
                        other = bad - rushed
                    if other >= 2:
                        summary.append(f"You diverged on {label} in {other} of {n} takes.")
                else:
                    summary.append(f"{label[0].upper() + label[1:]} came up short in {bad} of {n} takes.")
            elif m["met"] == n:
                summary.append(f"{label[0].upper() + label[1:]} met your mark in all {n} takes.")
        elif m["kind"] == "section":
            over = c.get("over", 0)
            if over >= 2:
                summary.append(f"{label[0].upper() + label[1:]} ran over budget in {over} of {n} takes.")
        elif m["kind"] == "DEFINE":
            miss = c.get("undefined", 0) + c.get("never_spoken", 0)
            if miss >= 2:
                summary.append(f"{label} went undefined in {miss} of {n} takes.")
    return {"takes": len(analyses), "take_ids": [a.get("take_id") for a in analyses], "marks": marks, "summary": summary}
