"""Compare one analysis JSON with human labels. Pure functions on dicts: no audio, no speech-to-text.

Pause length: every `/` or `//` the app measured is matched to the human `pause` region that
overlaps the app's measurement window (the stored `window`: end of the word before the mark to the
start of the word after it). If several overlap, the one with the largest overlap wins, then the
longest. A mark with no overlapping human pause is compared against 0 s: the human heard none.

Line times: |app - human| for the start and the end of every line the app found and the human
labelled. Status agreement: the app's status and the human's status for every mark that has both.
Aggregates are micro-averaged: rows from all recordings are pooled before the statistics.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean, median

from take_two.compare import _key_marks

from eval.labels import HumanStatus, canonical, mark_id


def app_marks(analysis: dict) -> dict[tuple, dict]:
    """The app's marks keyed for matching against parse_mark_id, with their id and status."""
    out = {}
    for k, v in _key_marks(analysis).items():
        shown = (k[0], v["term"]) if k[0] == "DEFINE" else k  # the term as written, not the lowered key
        out[canonical(k)] = {"id": mark_id(shown), "kind": v["kind"], "status": v["status"]}
    return out


def pause_errors(analysis: dict, human_pauses: list[tuple[float, float]]) -> list[dict]:
    rows: list[dict] = []
    for p in analysis.get("pauses", []):
        w = p.get("window")
        if p.get("measured_s") is None or not w or w[0] is None or w[1] is None:
            continue
        w0, w1 = min(w), max(w)
        best: tuple[float, float, float, float] | None = None
        for h0, h1 in human_pauses:
            if h0 <= w1 and h1 >= w0:
                cand = (min(w1, h1) - max(w0, h0), h1 - h0, h0, h1)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        human = best[1] if best else 0.0
        app = float(p["measured_s"])
        rows.append({"id": mark_id((p["kind"], p["line"], p["word_index"])), "kind": p["kind"], "status": p["status"],
                     "window": [w0, w1], "app_s": app, "human_s": human,
                     "human_region": [best[2], best[3]] if best else None,
                     "error_s": abs(app - human), "signed_s": app - human})
    return rows


def line_errors(analysis: dict, human_lines: dict[int, tuple[float, float]]) -> dict:
    """{rows, not_found: labelled lines the app did not time, unknown: labelled lines the script does not have}."""
    rows: list[dict] = []
    not_found: list[int] = []
    known = set()
    for r in analysis.get("lines", []):
        known.add(r["index"])
        h = human_lines.get(r["index"])
        if h is None:
            continue
        if r.get("start") is None or r.get("end") is None:
            not_found.append(r["index"] + 1)
            continue
        rows.append({"line": r["index"] + 1, "status": r["status"],
                     "app_start": r["start"], "human_start": h[0],
                     "start_error_s": abs(r["start"] - h[0]), "start_signed_s": r["start"] - h[0],
                     "app_end": r["end"], "human_end": h[1],
                     "end_error_s": abs(r["end"] - h[1]), "end_signed_s": r["end"] - h[1]})
    unknown = sorted(i + 1 for i in human_lines if i not in known)
    return {"rows": rows, "not_found": not_found, "unknown": unknown}


def error_stats(rows: list[dict], abs_key: str, signed_key: str) -> dict:
    """n, mean / median / max absolute error and mean signed error (app - human); None when n is 0."""
    errs = [r[abs_key] for r in rows]
    if not errs:
        return {"n": 0, "mean": None, "median": None, "max": None, "bias": None}
    return {"n": len(errs), "mean": mean(errs), "median": median(errs), "max": max(errs),
            "bias": mean(r[signed_key] for r in rows)}


def agreement_rows(analysis: dict, human: dict[tuple, HumanStatus]) -> dict:
    """{rows: marks with both statuses, absent: human ids the app has no mark for, unlabelled: app marks without a human status}."""
    app = app_marks(analysis)
    rows, absent = [], []
    for key, hs in human.items():
        a = app.get(key)
        if a is None:
            absent.append(hs.mark)
            continue
        rows.append({"id": a["id"], "kind": a["kind"], "human": hs.status, "app": a["status"],
                     "agree": hs.status == a["status"]})
    return {"rows": rows, "absent": absent, "unlabelled": sum(1 for k in app if k not in human)}


def agreement_stats(rows: list[dict]) -> dict:
    """Agreement count and percentage, a confusion table {human: {app: count}} and the same per mark kind."""
    confusion: dict[str, Counter] = {}
    by_kind: dict[str, dict] = {}
    for r in rows:
        confusion.setdefault(r["human"], Counter())[r["app"]] += 1
        k = by_kind.setdefault(r["kind"], {"n": 0, "agree": 0})
        k["n"] += 1
        k["agree"] += int(r["agree"])
    agree = sum(1 for r in rows if r["agree"])
    for k in by_kind.values():
        k["pct"] = 100.0 * k["agree"] / k["n"]
    return {"n": len(rows), "agree": agree, "pct": 100.0 * agree / len(rows) if rows else None,
            "confusion": {h: dict(c) for h, c in confusion.items()}, "by_kind": by_kind}
