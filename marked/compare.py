"""Take history: compare takes of the same script mark by mark."""

from __future__ import annotations

from collections import Counter


def _key_marks(a: dict) -> dict[tuple, dict]:
    out = {}
    for r in a.get("lines", []):
        if r.get("key"):
            out[("KEY", r["index"])] = {"kind": "KEY", "line": r["index"], "text": r["text"], "status": r["key"]["status"],
                                        "value": r["key"].get("wpm_vs_median_pct")}
    for p in a.get("pauses", []):
        out[(p["kind"], p["line"], p["word_index"])] = {"kind": p["kind"], "line": p["line"], "word_index": p["word_index"],
                                                       "status": p["status"], "value": p.get("measured_s"),
                                                       "text": f"{p.get('before') or ''} {p['kind']} {p.get('after') or ''}".strip()}
    for s in a.get("sections", []):
        out[("section", s["name"])] = {"kind": "section", "name": s["name"], "status": s["status"], "value": s.get("delta_s"),
                                       "text": s["name"]}
    for d in a.get("defines", []):
        out[("DEFINE", d["term"].lower())] = {"kind": "DEFINE", "term": d["term"], "status": d["status"], "value": None, "text": d["term"]}
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
        base = {kk: vv for kk, vv in present[-1].items() if kk not in ("status", "value")}
        marks.append({**base, "takes": len(present), "statuses": statuses, "values": [r["value"] for r in present],
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
            bad = c.get("diverged", 0) + c.get("missing", 0) + c.get("short", 0)
            if bad >= 2:
                if m["kind"] == "KEY":
                    rushed = any(v is not None and v > 0 for v in m["values"])
                    summary.append(f"You {'rushed' if rushed else 'diverged on'} {label} in {bad} of {n} takes.")
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
