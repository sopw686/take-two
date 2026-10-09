"""Turn the synthetic test fixture's ground truth into an evaluation recording.

    uv run python -m eval.make_synthetic

Writes eval/recordings/synthetic-coral/ from tests/fixtures/fixture_truth.json and fixture_script.md:
labels.txt (`line N` from each line's start/end, `pause` from each planted silence), statuses.csv
(the statuses the fixture was built to produce), script.md, audio.ref (pointing at fixture.wav, so
the audio is not committed twice) and info.json (says the voice and the labels are synthetic).
The "human" labels here are the generator's own timings, not a person's.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from take_two.marks import parse_script

from eval.labels import format_labels, format_statuses, mark_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
OUT = Path(__file__).resolve().parent / "recordings" / "synthetic-coral"
AUDIO_REF = "tests/fixtures/fixture.wav"


def key_status(rate: str, pause: str) -> str:
    """The app's overall [KEY] status from its two parts (DECISIONS.md, "[KEY] status has two parts")."""
    if rate == "met" and pause == "met":
        return "met"
    if rate == "diverged" or pause == "missing":
        return "diverged"
    return "near"


def build(truth: dict, script_text: str) -> tuple[str, str]:
    """(labels.txt, statuses.csv) text for the fixture."""
    script = parse_script(script_text)
    by_text = {ln.text: ln for ln in script.lines}
    if len(by_text) != len(script.lines):
        raise ValueError("two script lines have the same text; truth lines cannot be matched by text")

    def line_of(text: str):
        if text not in by_text:
            raise ValueError(f"truth line {text!r} is not a line of the script")
        return by_text[text]

    labels = []
    for t in truth["lines"]:
        ln = line_of(t["text"])
        labels.append((t["start"], t["end"], f"line {ln.index + 1}"))
    labels += [(s["start"], s["end"], "pause") for s in truth["silences"]]

    exp = truth["expected"]
    statuses: list[tuple[str, str]] = []
    for text, k in exp["key_lines"].items():
        ln = line_of(text)
        if not ln.is_key:
            raise ValueError(f"truth says {text!r} is a [KEY] line; the script does not mark it")
        statuses.append((mark_id(("KEY", ln.index)), key_status(k["rate"], k["pause_after"])))
    for p in exp["pauses"]:
        ln = line_of(p["line_text"])
        marks = [m for m in ln.pauses if m.kind == p["kind"]]
        if len(marks) != 1:
            raise ValueError(f"expected one {p['kind']} in line {ln.index + 1}, found {len(marks)}")
        statuses.append((mark_id((p["kind"], ln.index, marks[0].word_index)), p["status"]))
    names = {sec.name for sec in script.sections}
    for s in truth["sections"]:
        if s["name"] not in names:
            raise ValueError(f"truth section {s['name']!r} is not in the script")
        statuses.append((mark_id(("section", s["name"])), s["expected_status"]))
    terms = {d.term.lower() for d in script.defines}
    for d in exp["defines"]:
        if d["term"].lower() not in terms:
            raise ValueError(f"truth term {d['term']!r} has no [DEFINE] in the script")
        status = "never_spoken" if d["defined"] is None else ("defined" if d["defined"] else "undefined")
        statuses.append((mark_id(("DEFINE", d["term"])), status))
    return format_labels(labels), format_statuses(statuses)


INFO = {
    "synthetic": True,
    "speaker": "Windows text-to-speech voice (synthetic), built by tests/fixtures/make_fixture.py",
    "labels": "The generator's own timings and planted statuses from tests/fixtures/fixture_truth.json, "
              "not a human labeller. Pauses are the silences the generator inserted.",
}


def write(out: Path = OUT, fixtures: Path = FIXTURES) -> dict:
    truth = json.loads((fixtures / "fixture_truth.json").read_text(encoding="utf-8"))
    script_text = (fixtures / "fixture_script.md").read_text(encoding="utf-8")
    labels, statuses = build(truth, script_text)
    out.mkdir(parents=True, exist_ok=True)
    (out / "labels.txt").write_text(labels, encoding="utf-8", newline="\n")
    (out / "statuses.csv").write_text(statuses, encoding="utf-8", newline="\n")
    shutil.copyfile(fixtures / "fixture_script.md", out / "script.md")
    (out / "audio.ref").write_text(AUDIO_REF + "\n", encoding="utf-8", newline="\n")
    (out / "info.json").write_text(json.dumps(INFO, indent=1) + "\n", encoding="utf-8", newline="\n")
    return {"labels": labels.count("\n"), "statuses": statuses.count("\n") - 1, "out": out}


if __name__ == "__main__":
    res = write()
    print(f"Wrote {res['labels']} labels and {res['statuses']} statuses to {res['out']}")
