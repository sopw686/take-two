"""End-to-end on the synthetic fixture with real local speech-to-text.

Ground truth comes from tests/fixtures/fixture_truth.json (written by
make_fixture.py). Tolerances are documented there and in TESTING.md.
Run with:  uv run pytest -m slow
"""

import json
from pathlib import Path

import pytest

from take_two import pipeline
from take_two.config import Settings

HERE = Path(__file__).resolve().parent / "fixtures"
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def result(tmp_path_factory, monkeypatch_module):
    from take_two import config
    monkeypatch_module.setattr(config, "TAKES_DIR", tmp_path_factory.mktemp("takes"))
    script = (HERE / "fixture_script.md").read_text(encoding="utf-8")
    return pipeline.run_take(HERE / "fixture.wav", script, Settings(), label="fixture", original_name="fixture.wav")


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def truth():
    return json.loads((HERE / "fixture_truth.json").read_text(encoding="utf-8"))


def test_every_line_found_and_timed(result, truth):
    tol = truth["expected"]["tolerances"]["line_s"]
    for row, t in zip(result["lines"], truth["lines"]):
        assert row["status"] == "ok", row["text"]
        assert abs(row["start"] - t["start"]) <= tol, (row["text"], row["start"], t["start"])
        assert abs(row["end"] - t["end"]) <= tol, (row["text"], row["end"], t["end"])


def test_section_durations_and_budget_status(result, truth):
    tol = truth["expected"]["tolerances"]["section_s"]
    for row, t in zip(result["sections"], truth["sections"]):
        assert row["name"] == t["name"]
        assert abs(row["duration_s"] - t["spoken_duration"]) <= tol, (row["name"], row["duration_s"], t["spoken_duration"])
        assert row["status"] == t["expected_status"], (row["name"], row)


def test_pause_marks_measured_within_tolerance(result, truth):
    tol = truth["expected"]["tolerances"]["pause_s"]
    by_line = {r["text"]: r["index"] for r in result["lines"]}
    for exp in truth["expected"]["pauses"]:
        li = by_line[exp["line_text"]]
        row = next(p for p in result["pauses"] if p["line"] == li and p["kind"] == exp["kind"])
        assert row["status"] == exp["status"], row
        if "measured_s" in exp:
            assert abs(row["measured_s"] - exp["measured_s"]) <= tol, row


def test_key_lines_rate_and_pause(result, truth):
    by_text = {r["text"]: r for r in result["lines"]}
    for text, exp in truth["expected"]["key_lines"].items():
        k = by_text[text]["key"]
        assert k["rate_status"] == exp["rate"], (text, k)
        assert k["pause_status"] == exp["pause_after"], (text, k)


def test_numbers_trace_to_timestamps(result):
    for p in result["pauses"]:
        if p["status"] != "unmeasurable":
            assert p["window"] and p["at_time"] is not None
    for r in result["lines"]:
        if r.get("key") and r["key"]["status"] != "not_found":
            assert r["key"]["pause_window"]
