"""The noise floor: how far the same measurement moves between takes of the same script.

    uv run python -m eval.retest <take_id> [<take_id> ...]
    uv run python -m eval.retest --same-script <take_id>

Reads finished takes from the takes folder (TAKE_TWO_TAKES_DIR, default takes/) and prints, as
Markdown, the spread of the median wpm and of each pause mark's measured length across them: n,
min, max, max - min and the population standard deviation. A difference between two takes that
is smaller than this spread cannot be told apart from noise. Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import sys
from statistics import pstdev

from eval.labels import mark_id


def spread(values: list[float | None]) -> dict:
    """n, min, max, max - min and population stdev of the measured values (None = not measured, left out)."""
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "missing": len(values), "min": None, "max": None, "range": None, "stdev": None}
    return {"n": len(vals), "missing": len(values) - len(vals), "min": min(vals), "max": max(vals),
            "range": max(vals) - min(vals), "stdev": pstdev(vals)}


def _f(x: float | None, nd: int = 2) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _row(name: str, s: dict, nd: int) -> str:
    # One value has no spread: show it, but leave range and stdev empty rather than a misleading 0.
    rng, sd = (s["range"], s["stdev"]) if s["n"] >= 2 else (None, None)
    miss = f" ({s['missing']} not measured)" if s["missing"] else ""
    return f"| {name} | {s['n']}{miss} | {_f(s['min'], nd)} | {_f(s['max'], nd)} | {_f(rng, nd)} | {_f(sd, nd)} |"


def report(analyses: list[dict]) -> str:
    """Markdown for analyses of one script, oldest first."""
    out = ["# Retest spread (noise floor)", "",
           f"{len(analyses)} take(s) of the same script. Pause marks are matched by their position in the script.", "",
           "| Take | Label | Recorded | Kind | Median wpm |", "|---|---|---|---|---|"]
    for a in analyses:
        out.append(f"| {a.get('take_id')} | {a.get('label') or ''} | {a.get('created_at') or ''} | "
                   f"{a.get('kind', 'take')} | {_f((a.get('baseline') or {}).get('median_wpm'), 1)} |")
    if len(analyses) < 2:
        out += ["", "A spread needs at least two takes."]
    if any(a.get("kind", "take") == "example" for a in analyses):
        out += ["", "One of these is an example take (synthetic voice); its spread says nothing about a real speaker."]

    head = ["| Measure | n | Min | Max | Max − min | Stdev (population) |", "|---|---|---|---|---|---|"]
    out += ["", "## Median rate (wpm)", ""] + head
    out.append(_row("Median wpm", spread([(a.get("baseline") or {}).get("median_wpm") for a in analyses]), 1))

    marks: dict[tuple, list] = {}
    for a in analyses:
        for p in a.get("pauses", []):
            marks.setdefault((p["kind"], p["line"], p["word_index"]), [])
    for a in analyses:
        got = {(p["kind"], p["line"], p["word_index"]): p.get("measured_s") for p in a.get("pauses", [])}
        for k, vals in marks.items():
            vals.append(got.get(k))
    out += ["", "## Pause marks (measured seconds)", ""]
    if marks:
        out += head + [_row(f"`{mark_id(k)}`", spread(v), 2) for k, v in sorted(marks.items(), key=lambda kv: (kv[0][1], kv[0][2]))]
    else:
        out.append("The script has no pause marks.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.retest", description=__doc__.split("\n\n")[0])
    ap.add_argument("take_ids", nargs="*", help="finished takes of one script")
    ap.add_argument("--same-script", metavar="TAKE_ID", help="use every real take that shares this take's script")
    args = ap.parse_args(argv)

    from take_two import takes
    try:
        if args.same_script:
            analyses = takes.takes_with_same_script(args.same_script)
            if not analyses:
                raise ValueError(f"{args.same_script} is not a finished take")
        elif args.take_ids:
            analyses = []
            for tid in args.take_ids:
                a = takes.load_take(tid)
                if a is None:
                    raise ValueError(f"{tid} is not a finished take")
                analyses.append(a)
            analyses.sort(key=lambda a: a.get("created_at") or "")
        else:
            ap.error("give take ids or --same-script TAKE_ID")
        if any(a.get("mode") == "improv" for a in analyses):
            raise ValueError("Improvise takes have no script marks; give script takes")
        keys = {takes.analysis_script_key(a) for a in analyses}
        if len(keys) > 1:
            raise ValueError("these takes do not share one script, so their marks cannot be matched")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(report(analyses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
