"""Every mark's outcome across all takes, as CSV: statuses and numbers only.

For a user study or a spreadsheet. No labels, topics, script text, transcript or audio
leave in this file, so mark ids are positions, not names: KEY:L6 and /:L3:W4 as in
eval/ (line counted from 1; W = words before the pause), section:S2 for the second
section, DEFINE:L4 for the [DEFINE] on line 4 (DEFINE:L4:2 for a second one on that
line). A drill's rows use the positions of the marks in its full take's script, so they
line up with the parent's rows under drill_of. The script itself is identified only by
script_key, a hash. Example takes, unfinished takes, Improvise takes (which have no
marks) and sections with no lines (nothing to time) are left out.
"""

from __future__ import annotations

import csv
import io

from take_two import takes

COLUMNS = ["take_id", "created_at", "kind", "drill_of", "script_key", "mark_id", "mark", "status", "value", "unit", "target"]


def _num(x: object) -> object:
    return "" if x is None else x


def outcome_rows(a: dict) -> list[dict]:
    base = {"take_id": a.get("take_id"), "created_at": a.get("created_at"), "kind": a.get("kind") or "take",
            "drill_of": a.get("drill_of") or "", "script_key": a.get("script_key") or ""}
    rows: list[dict] = []

    def add(mark_id: str, mark: str, status: str, value: object = None, unit: str = "", target: object = None) -> None:
        rows.append({**base, "mark_id": mark_id, "mark": mark, "status": status, "value": _num(value), "unit": unit,
                     "target": _num(target)})

    drill = a.get("drill") if a.get("kind") == "drill" else None
    lo, so = (drill.get("line_start", 0), drill.get("section", 0)) if drill else (0, 0)
    b = a.get("baseline", {})
    add("median", "median rate", "", b.get("median_wpm"), "wpm")
    for s in a.get("sections", []):
        # A line drill's one section is that line under its section's name, not the section: no row.
        if s["status"] != "no_lines" and not (drill and drill.get("kind") == "line"):
            add(f"section:S{s['index'] + so + 1}", "section", s["status"], s.get("duration_s"), "s", s.get("budget_s"))
    for ln in a.get("lines", []):
        k = ln.get("key")
        if not k:
            continue
        lid = f"KEY:L{ln['index'] + lo + 1}"
        add(lid, "KEY", k["status"])
        add(f"{lid}:rate", "KEY rate", k.get("rate_status", ""), k.get("wpm_vs_median_pct"), "% vs median",
            -k["slower_target_pct"] if k.get("slower_target_pct") is not None else None)
        add(f"{lid}:pause", "KEY pause after", k.get("pause_status", ""), k.get("pause_after_s"), "s", k.get("pause_after_target_s"))
    for p in a.get("pauses", []):
        add(f"{p['kind']}:L{p['line'] + lo + 1}:W{p['word_index']}", p["kind"], p["status"], p.get("measured_s"), "s", p.get("target_s"))
    seen: dict[int, int] = {}
    for d in a.get("defines", []):
        line = d["line"] + lo
        seen[line] = seen.get(line, 0) + 1
        n = seen[line]
        add(f"DEFINE:L{line + 1}" + (f":{n}" if n > 1 else ""), "DEFINE", d["status"])
    return rows


def outcomes_csv() -> str:
    buf = io.StringIO()
    out = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    out.writeheader()
    for t in sorted(takes.list_takes(include_unfinished=False), key=lambda t: t.get("created_at") or ""):
        if t.get("mode") == "improv" or t.get("kind") == "example":
            continue
        a = takes.load_take(t["take_id"])
        if a:
            out.writerows(outcome_rows(a))
    return buf.getvalue()
