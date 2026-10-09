"""Run the real pipeline on every labelled recording and compare it with the human labels.

    uv run python -m eval.run                       all recordings in eval/recordings/ -> eval/RESULTS.md
    uv run python -m eval.run synthetic-coral       only the named recordings
    uv run python -m eval.run --reuse-transcripts   use each recording's committed transcript.json (no speech-to-text)
    uv run python -m eval.run --save-transcripts    also save each fresh transcript as transcript.json in its recording
    uv run python -m eval.run --list-marks NAME     print a statuses.csv template with every mark id of NAME's script

Each recording goes through take_two.pipeline in a temporary takes folder, so the user's own takes
are neither read nor changed, and is then compared with its labels by eval.metrics. Speech-to-text
runs locally: the harness refuses to start when cloud transcription is configured.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from take_two.config import Settings
from take_two.marks import parse_script

from eval import metrics
from eval.labels import (HumanLabels, HumanStatus, format_statuses, interpret_labels, parse_labels, parse_mark_id,
                         parse_statuses, script_mark_ids)

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
RECORDINGS_DIR = EVAL_DIR / "recordings"
RESULTS = EVAL_DIR / "RESULTS.md"


@dataclass
class Recording:
    name: str
    dir: Path
    audio: Path
    script_text: str
    labels: HumanLabels
    statuses: dict[tuple, HumanStatus] | None
    settings: Settings
    settings_source: str
    info: dict = field(default_factory=dict)


# ---- loading ----------------------------------------------------------------------

def find_audio(rdir: Path) -> Path:
    """audio.<ext> in the folder, else the file named in audio.ref (relative to the repository root)."""
    files = [p for p in sorted(rdir.glob("audio.*")) if p.is_file() and p.name != "audio.ref"]
    if len(files) > 1:
        raise ValueError(f"{rdir.name}: more than one audio file ({', '.join(p.name for p in files)})")
    if files:
        return files[0]
    ref = rdir / "audio.ref"
    if ref.exists():
        rel = _read(ref).strip()
        path = (ROOT / rel).resolve()  # an absolute path in audio.ref stays absolute
        if not rel or not path.is_file():
            raise FileNotFoundError(f"{rdir.name}/audio.ref points at {rel!r}, which is not a file")
        return path
    raise FileNotFoundError(f"{rdir.name}: no audio.<ext> and no audio.ref")


def _read(path: Path) -> str:
    data = path.read_bytes()
    # Windows PowerShell 5.1 writes UTF-16 when output is redirected with `>`; everything else here is UTF-8.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def load_recording(rdir: Path) -> Recording:
    """Read and check one recording folder. Raises ValueError / FileNotFoundError with a readable message."""
    name = rdir.name
    if not (rdir / "script.md").exists() or not (rdir / "labels.txt").exists():
        raise FileNotFoundError(f"{name}: a recording needs script.md and labels.txt")
    script_text = _read(rdir / "script.md")
    script = parse_script(script_text)
    labels = interpret_labels(parse_labels(_read(rdir / "labels.txt"), f"{name}/labels.txt"), f"{name}/labels.txt")
    beyond = sorted(i + 1 for i in labels.lines if i >= len(script.lines))
    if beyond:
        raise ValueError(f"{name}/labels.txt: labels line {beyond[0]}, but script.md has {len(script.lines)} lines "
                         "(lines are counted without blank lines, ## headers and comments)")
    statuses = None
    if (rdir / "statuses.csv").exists():
        statuses = parse_statuses(_read(rdir / "statuses.csv"), f"{name}/statuses.csv")
        known = {parse_mark_id(m) for m in script_mark_ids(script)}
        unknown = [s.mark for k, s in statuses.items() if k not in known]
        if unknown:
            raise ValueError(f"{name}/statuses.csv: {', '.join(unknown)} is not a mark of script.md "
                             f"(`uv run python -m eval.run --list-marks {name}` lists them)")
    settings, source = Settings(), "app defaults"
    if (rdir / "settings.json").exists():
        try:
            settings = Settings.model_validate(json.loads(_read(rdir / "settings.json")))
        except ValueError as exc:
            raise ValueError(f"{name}/settings.json: {exc}") from None
        source = "settings.json"
    info = json.loads(_read(rdir / "info.json")) if (rdir / "info.json").exists() else {}
    return Recording(name=name, dir=rdir, audio=find_audio(rdir), script_text=script_text, labels=labels,
                     statuses=statuses, settings=settings, settings_source=source, info=info)


def recording_names() -> list[str]:
    if not RECORDINGS_DIR.is_dir():
        return []
    return sorted(d.name for d in RECORDINGS_DIR.iterdir() if d.is_dir() and (d / "script.md").exists())


# ---- running ----------------------------------------------------------------------

def analyse(rec: Recording, reuse_transcript: bool = False, save_transcript: bool = False) -> dict:
    """The real pipeline on one recording. config.TAKES_DIR must already point at a scratch folder."""
    from take_two import pipeline, takes

    label = f"eval: {rec.name}"
    if reuse_transcript:
        tr = rec.dir / "transcript.json"
        if not tr.exists():
            raise FileNotFoundError(f"{rec.name}: --reuse-transcripts needs {rec.name}/transcript.json "
                                    "(make one with --save-transcripts)")
        # As pipeline.create_example does: a take whose transcript already exists skips speech-to-text.
        take_id = takes.new_take("script", upload=rec.audio, original_name=rec.audio.name,
                                 settings=rec.settings.model_dump(), label=label, script=rec.script_text)
        shutil.copyfile(tr, takes.take_path(take_id) / "transcript.json")
        return pipeline.process_take(take_id, settings=rec.settings)
    analysis = pipeline.run_take(rec.audio, rec.script_text, rec.settings, label=label, original_name=rec.audio.name)
    if save_transcript:
        shutil.copyfile(takes.take_path(analysis["take_id"]) / "transcript.json", rec.dir / "transcript.json")
    return analysis


def evaluate(rec: Recording, analysis: dict) -> dict:
    """Compare one analysis with its recording's labels."""
    return {
        "name": rec.name, "info": rec.info, "error": None, "settings_source": rec.settings_source,
        "audio": _shown_path(rec.audio), "duration_s": analysis.get("duration_s"), "stt": analysis.get("stt") or {},
        "define_methods": sorted({d.get("method") or "?" for d in analysis.get("defines", [])}),
        "pauses": metrics.pause_errors(analysis, rec.labels.pauses),
        "lines": metrics.line_errors(analysis, rec.labels.lines),
        "agreement": metrics.agreement_rows(analysis, rec.statuses) if rec.statuses is not None else None,
        "warnings": list(rec.labels.warnings),
    }


def _shown_path(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.name  # outside the repository: do not print the user's folder layout into a committed file


def _git_version() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "take_two"], cwd=ROOT, capture_output=True,
                               text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown (git not available)"
    return f"`take_two/` at commit {head}" + (" with uncommitted changes" if dirty else "")


# ---- Markdown ---------------------------------------------------------------------

def _f(x: float | None, nd: int = 2) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.1f} %"


def _stt_text(stt: dict) -> str:
    if not stt:
        return "unknown"
    where = "local" if stt.get("local", True) else "cloud"
    return f"{stt.get('backend') or '?'} `{stt.get('model') or '?'}` on `{stt.get('device') or '?'}` ({where})"


def _stats_table(pauses: list[dict], lines: list[dict]) -> list[str]:
    out = ["| Measure | n | Mean abs. error (s) | Median abs. error (s) | Max abs. error (s) | Mean signed error, app − human (s) |",
           "|---|---|---|---|---|---|"]
    for name, rows, a, s in (("Pause length (`/`, `//`)", pauses, "error_s", "signed_s"),
                             ("Line start", lines, "start_error_s", "start_signed_s"),
                             ("Line end", lines, "end_error_s", "end_signed_s")):
        st = metrics.error_stats(rows, a, s)
        out.append(f"| {name} | {st['n']} | {_f(st['mean'], 3)} | {_f(st['median'], 3)} | {_f(st['max'], 3)} | {_f(st['bias'], 3)} |")
    return out


def _agreement_block(rows: list[dict]) -> list[str]:
    st = metrics.agreement_stats(rows)
    if not st["n"]:
        return ["No mark has both a human and an app status."]
    out = [f"**Status agreement:** {st['agree']} of {st['n']} marks ({_pct(st['pct'])}).", "",
           "| Mark kind | Marks | Agreed | Agreement |", "|---|---|---|---|"]
    for kind in ("KEY", "/", "//", "section", "DEFINE"):
        k = st["by_kind"].get(kind)
        if k:
            out.append(f"| `{kind}` | {k['n']} | {k['agree']} | {_pct(k['pct'])} |")
    app_cols = sorted({a for c in st["confusion"].values() for a in c})
    out += ["", "Confusion (rows: human status, columns: app status):", "",
            "| Human \\ App | " + " | ".join(app_cols) + " |", "|---|" + "---|" * len(app_cols)]
    for h in sorted(st["confusion"]):
        out.append(f"| {h} | " + " | ".join(str(st["confusion"][h].get(a, 0)) for a in app_cols) + " |")
    return out


def _recording_section(r: dict) -> list[str]:
    out = [f"## {r['name']}", ""]
    info = r["info"]
    if info.get("synthetic"):
        out.append(f"- Speaker: **synthetic voice.** {info.get('speaker', '')}".rstrip())
    elif info.get("speaker"):
        out.append(f"- Speaker: {info['speaker']}")
    if info.get("labels"):
        out.append(f"- Labels: {info['labels']}")
    if r["error"]:
        return out + ["", f"Not evaluated: the pipeline failed ({r['error']}).", ""]
    out += [f"- Audio: `{r['audio']}` ({_f(r['duration_s'], 1)} s)", f"- Speech-to-text: {_stt_text(r['stt'])}",
            f"- Settings: {r['settings_source']}", "", "### Summary", ""]
    out += _stats_table(r["pauses"], r["lines"]["rows"])
    if r["agreement"] is not None:
        out += [""] + _agreement_block(r["agreement"]["rows"])

    out += ["", "### Pause length", ""]
    if r["pauses"]:
        out += ["| Mark | App status | App window (s) | App measured (s) | Human pause (s) | Error (s) |", "|---|---|---|---|---|---|"]
        for p in r["pauses"]:
            hr = p["human_region"]
            human = f"{p['human_s']:.2f} ({hr[0]:.2f}–{hr[1]:.2f})" if hr else "0.00 (none overlaps)"
            out.append(f"| `{p['id']}` | {p['status']} | {p['window'][0]:.2f}–{p['window'][1]:.2f} | {p['app_s']:.2f} | "
                       f"{human} | {p['error_s']:.2f} |")
    else:
        out.append("No pause mark was measured.")

    lines = r["lines"]
    out += ["", "### Line start and end", ""]
    if lines["rows"]:
        out += ["| Line | App start (s) | Human start (s) | Error (s) | App end (s) | Human end (s) | Error (s) |",
                "|---|---|---|---|---|---|---|"]
        for ln in lines["rows"]:
            out.append(f"| {ln['line']} | {ln['app_start']:.3f} | {ln['human_start']:.3f} | {ln['start_error_s']:.3f} | "
                       f"{ln['app_end']:.3f} | {ln['human_end']:.3f} | {ln['end_error_s']:.3f} |")
    else:
        out.append("No labelled line was found by the app.")
    if lines["not_found"]:
        out += ["", "Labelled but not found by the app: line " + ", ".join(map(str, lines["not_found"])) + "."]

    ag = r["agreement"]
    out += ["", "### Status agreement", ""]
    if ag is None:
        out.append("No statuses.csv in this recording.")
    else:
        out += ["| Mark | Human | App | Same |", "|---|---|---|---|"]
        out += [f"| `{a['id']}` | {a['human']} | {a['app']} | {'yes' if a['agree'] else 'no'} |" for a in ag["rows"]]
        if ag["absent"]:
            out += ["", "Human statuses for marks the app did not report: " + ", ".join(f"`{m}`" for m in ag["absent"]) + "."]
        if ag["unlabelled"]:
            out += ["", f"{ag['unlabelled']} app mark(s) have no human status and are not counted."]
    if r["warnings"]:
        out += ["", "Label warnings:", ""] + [f"- {w}" for w in r["warnings"]]
    return out + [""]


def _synthetic_note(results: list[dict]) -> str:
    synth = [r["name"] for r in results if r["info"].get("synthetic")]
    if not synth:
        return ""
    if len(synth) == len(results) == 1:
        return (f"> **Synthetic voice only.** The only recording so far, `{synth[0]}`, is a text-to-speech voice with "
                "planted pauses and rate changes, and its labels are the generator's own timings, not a person's. "
                "These numbers show that the pipeline and the harness agree with a known construction. "
                "They say nothing about how the app does on real speakers.")
    if len(synth) == len(results):
        return ("> **Synthetic voices only.** Every recording here is text-to-speech with generator labels. "
                "These numbers say nothing about how the app does on real speakers.")
    return (f"> **{len(synth)} of {len(results)} recordings are synthetic** ({', '.join(synth)}). The aggregate mixes "
            "them with real speakers; read the per-recording tables for real speakers alone.")


def render(results: list[dict], *, reused: bool, today: str | None = None, version: str | None = None) -> str:
    ok = [r for r in results if not r["error"]]
    out = ["# Evaluation results", "",
           f"Written by `uv run python -m eval.run` on {today or date.today().isoformat()}. Every number below was "
           "computed by that run; re-run the command instead of editing this file.", ""]
    note = _synthetic_note(results)
    if note:
        out += [note, ""]
    stts = sorted({_stt_text(r["stt"]) for r in ok})
    methods = sorted({m for r in ok for m in r["define_methods"]})
    sources = sorted({r["settings_source"] for r in ok})
    failed = [r["name"] for r in results if r["error"]]
    out += ["| Run | |", "|---|---|",
            f"| Recordings | {len(ok)} evaluated" + (f", {len(failed)} failed ({', '.join(failed)})" if failed else "")
            + f": {', '.join(r['name'] for r in ok) or 'none'} |",
            f"| Speech-to-text | {'; '.join(stts) or '–'} |",
            "| Transcripts | " + ("reused from each recording's transcript.json (speech-to-text not run)" if reused
                                  else "fresh speech-to-text run") + " |",
            f"| `[DEFINE]` check | {', '.join(methods) or 'no [DEFINE] marks'} |",
            f"| Settings | {', '.join(sources) or '–'} |",
            f"| Pipeline | {version or _git_version()} |", ""]

    out += ["## Aggregate", "", f"Micro-averaged: every mark and line of the {len(ok)} evaluated recording(s) pooled.", ""]
    out += _stats_table([p for r in ok for p in r["pauses"]], [ln for r in ok for ln in r["lines"]["rows"]])
    ag_rows = [a for r in ok if r["agreement"] for a in r["agreement"]["rows"]]
    out += [""] + (_agreement_block(ag_rows) if any(r["agreement"] is not None for r in ok)
                   else ["No recording has a statuses.csv."]) + [""]

    for r in results:
        out += _recording_section(r)

    out += ["## How the numbers are computed", "",
            "- **Pause length.** Each `/` or `//` the app measured is matched to the human `pause` region that overlaps "
            "the app's window (end of the word before the mark to the start of the word after it, as stored in the "
            "analysis). If several overlap, the largest overlap wins, then the longest region. With no overlapping "
            "region the human value is 0 s. Error = |app measured − human duration|.",
            "- **Line start and end.** |app − human| for lines the app found and the human labelled `line N`.",
            "- **Status agreement.** The app's status equals the human's status in statuses.csv, for marks that have both.",
            "- **Aggregate.** Rows from all recordings pooled before averaging (micro-average).",
            "- Signed errors are app − human: positive means the app measured later or longer.", ""]
    return "\n".join(out)


# ---- command line -----------------------------------------------------------------

def list_marks(name: str) -> tuple[str, str]:
    """(statuses.csv template, the script's lines numbered as the labels count them)."""
    path = Path(name)
    if not path.is_file():
        path = RECORDINGS_DIR / name / "script.md"
    script = parse_script(_read(path))
    numbered = "".join(f"line {ln.index + 1}: {'[KEY] ' if ln.is_key else ''}{ln.text}\n" for ln in script.lines)
    return format_statuses([(m, "") for m in script_mark_ids(script)]), numbered


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="recording folders under eval/recordings/ (default: all)")
    ap.add_argument("--reuse-transcripts", action="store_true",
                    help="use each recording's transcript.json instead of running speech-to-text")
    ap.add_argument("--save-transcripts", action="store_true",
                    help="save each fresh transcript as transcript.json in its recording folder")
    ap.add_argument("--out", type=Path, default=RESULTS, help="where to write the results (default: eval/RESULTS.md)")
    ap.add_argument("--list-marks", metavar="NAME", help="print a statuses.csv template for a recording's script")
    args = ap.parse_args(argv)

    if args.list_marks:
        template, numbered = list_marks(args.list_marks)
        sys.stderr.write(numbered)  # for the person labelling; stdout stays a clean CSV to redirect into a file
        sys.stdout.write(template)
        return 0
    names = args.names or recording_names()
    if not names:
        print(f"No recordings in {RECORDINGS_DIR}. See eval/README.md.", file=sys.stderr)
        return 2
    try:
        recordings = [load_recording(RECORDINGS_DIR / n) for n in names]
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from take_two import config, stt
    if not args.reuse_transcripts and stt.audio_leaves_machine():
        print("error: cloud speech-to-text is configured (TAKE_TWO_STT=openai). The evaluation runs local "
              "speech-to-text only; unset TAKE_TWO_STT and run again.", file=sys.stderr)
        return 2

    results = []
    saved_dir = config.TAKES_DIR
    config.TAKES_DIR = Path(tempfile.mkdtemp(prefix="take-two-eval-"))
    try:
        for rec in recordings:
            print(f"{rec.name}: running the pipeline on {_shown_path(rec.audio)} ...", flush=True)
            try:
                analysis = analyse(rec, args.reuse_transcripts, args.save_transcripts)
            except Exception as exc:  # report the failure and go on with the other recordings
                results.append({"name": rec.name, "info": rec.info, "error": str(exc) or type(exc).__name__})
                print(f"{rec.name}: failed: {exc}", file=sys.stderr)
                continue
            results.append(evaluate(rec, analysis))
    finally:
        shutil.rmtree(config.TAKES_DIR, ignore_errors=True)
        config.TAKES_DIR = saved_dir

    args.out.write_text(render(results, reused=args.reuse_transcripts), encoding="utf-8", newline="\n")
    print(f"Wrote {args.out}")
    return 1 if any(r["error"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
