"""Evaluation harness: label and status files, mark ids, the metrics, the synthetic recording, retest.

No speech-to-text and no audio decoding: analyses come from hand-built transcripts or are written by hand.
"""

import json
from pathlib import Path

import pytest

from eval import labels as ev
from eval import make_synthetic, metrics, retest
from eval import run as ev_run
from take_two import config
from take_two.analysis import analyze
from take_two.config import Settings
from take_two.define import check_defines
from take_two.llm.base import NullLLM
from take_two.marks import parse_script
from tests.helpers import make_transcript, silences_from_gaps

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


# ---- labels.txt ----------------------------------------------------------------------------

def test_labels_parse_tabs_trailing_newline_and_point_labels():
    labs = ev.parse_labels("0.000000\t2.464000\tline 1\n2.464000\t2.964000\tpause\n5.500000\t5.500000\tpause\n")
    assert [(l.start, l.end, l.text) for l in labs] == [(0.0, 2.464, "line 1"), (2.464, 2.964, "pause"), (5.5, 5.5, "pause")]
    assert [l.line_no for l in labs] == [1, 2, 3]


def test_labels_skip_spectral_and_blank_lines_and_accept_decimal_commas():
    # Audacity writes "\<TAB>low<TAB>high" after a label made with a spectral selection; some locales use a decimal comma.
    labs = ev.parse_labels("1,5\t2,25\tline 2\n\\\t100.000000\t8000.000000\n\r\n3.0\t3.4\tpause")
    assert [(l.start, l.end, l.text) for l in labs] == [(1.5, 2.25, "line 2"), (3.0, 3.4, "pause")]


def test_labels_reject_bad_numbers_and_reversed_regions():
    with pytest.raises(ValueError, match="line 2"):
        ev.parse_labels("0\t1\tline 1\nabc\t2\tpause\n")
    with pytest.raises(ValueError, match="before it starts"):
        ev.parse_labels("3\t2\tpause\n")


def test_interpret_labels_lines_pauses_and_warnings():
    h = ev.interpret_labels(ev.parse_labels(
        "0\t2\tLine 1\n2.5\t4\tline  2\n2\t2.5\tpause\n4\t4\tpause\n4\t5\tbreath\n"))
    assert h.lines == {0: (0.0, 2.0), 1: (2.5, 4.0)}  # 1-based labels, 0-based script lines
    assert h.pauses == [(2.0, 2.5)]
    assert len(h.warnings) == 2
    assert any("point label" in w for w in h.warnings) and any("breath" in w for w in h.warnings)


def test_interpret_labels_rejects_a_line_labelled_twice_or_line_zero():
    with pytest.raises(ValueError, match="twice"):
        ev.interpret_labels(ev.parse_labels("0\t1\tline 1\n1\t2\tline 1\n"))
    with pytest.raises(ValueError, match="from 1"):
        ev.interpret_labels(ev.parse_labels("0\t1\tline 0\n"))


# ---- statuses.csv and mark ids -------------------------------------------------------------

def test_statuses_parse_header_comments_quotes_and_case():
    st = ev.parse_statuses('mark,status\n# judged by ear\nKEY:L6,Diverged\n/:L3:W4,missing\n'
                           '"DEFINE:heat, stress",never spoken\nsection:methods, over \n')
    assert st[("KEY", 5)].status == "diverged"
    assert st[("/", 2, 4)].status == "missing"
    assert st[("DEFINE", "heat, stress")].status == "never_spoken"
    assert st[("section", "methods")] == ev.HumanStatus(mark="section:methods", status="over")


@pytest.mark.parametrize("text, msg", [
    ("KEY:L6,over\n", "not a status of a KEY mark"),
    ("//:L6:W8,near\n", "not a status of a // mark"),
    ("/:L3,met\n", "not a mark id"),
    ("KEY:L0,met\n", "not a mark id"),
    ("section:,met\n", "not a mark id"),
    ("KEY:L6,met\nkey:l6,near\n", "already has a status"),
    ("KEY:L6\n", "expected mark,status"),
])
def test_statuses_reject_bad_rows(text, msg):
    with pytest.raises(ValueError, match=msg):
        ev.parse_statuses(text)


def _analysis(script_text: str, spoken: str) -> tuple:
    script = parse_script(script_text)
    tr = make_transcript(spoken)
    a = analyze(script, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    a["defines"] = check_defines(script, tr, NullLLM())  # as pipeline.reanalyze adds them
    return script, a


def test_mark_ids_match_the_apps_marks_on_the_fixture_script():
    text = (FIXTURES / "fixture_script.md").read_text(encoding="utf-8")
    script, a = _analysis(text, " ".join(ln.text for ln in parse_script(text).lines))
    ids = ev.script_mark_ids(script)
    assert set(ids) == {"section:Opening", "section:Methods", "section:Results", "/:L3:W4",
                        "DEFINE:degree heating weeks", "KEY:L6", "//:L6:W8", "KEY:L8", "/:L8:W5"}
    app = metrics.app_marks(a)
    assert {m["id"] for m in app.values()} == set(ids)
    assert {ev.parse_mark_id(i) for i in ids} == set(app)  # every id finds the app's mark it names


def test_mark_ids_for_an_untitled_section_and_a_term_written_twice():
    text = "Entropy [DEFINE: Entropy] is disorder / we said.\n[KEY] Entropy grows [DEFINE: entropy] over time. //\n"
    script, a = _analysis(text, "entropy is disorder we said entropy grows over time")
    ids = ev.script_mark_ids(script)
    assert ids == ["section:Untitled", "/:L1:W3", "DEFINE:Entropy", "KEY:L2", "//:L2:W4"]
    assert {ev.parse_mark_id(i) for i in ids} == set(metrics.app_marks(a))
    assert ev.parse_mark_id("define:  ENTROPY ") == ("DEFINE", "entropy")


def test_mark_id_round_trip():
    for key in [("KEY", 5), ("/", 2, 4), ("//", 5, 8), ("section", "Methods"), ("DEFINE", "degree heating weeks")]:
        assert ev.parse_mark_id(ev.mark_id(key)) == ev.canonical(key)


# ---- metrics -------------------------------------------------------------------------------

def _pause(line, wi, kind, measured, window, status="met"):
    return {"line": line, "word_index": wi, "kind": kind, "measured_s": measured, "window": window, "status": status}


def test_pause_error_against_the_overlapping_human_pause():
    rows = metrics.pause_errors({"pauses": [_pause(5, 8, "//", 1.57, [22.0, 23.87])]}, [(2.4, 2.9), (22.217, 23.817)])
    r = rows[0]
    assert r["id"] == "//:L6:W8"
    assert r["human_s"] == pytest.approx(1.6) and r["human_region"] == [22.217, 23.817]
    assert r["error_s"] == pytest.approx(0.03) and r["signed_s"] == pytest.approx(-0.03)


def test_pause_without_an_overlapping_human_pause_counts_as_zero():
    rows = metrics.pause_errors({"pauses": [_pause(2, 4, "/", 0.12, [8.27, 8.27], "missing")]}, [(6.7, 7.2), (10.2, 10.7)])
    assert rows[0]["human_s"] == 0.0 and rows[0]["human_region"] is None
    assert rows[0]["error_s"] == pytest.approx(0.12)


def test_pause_error_picks_the_largest_overlap_and_skips_unmeasured_marks():
    a = {"pauses": [_pause(0, 2, "/", 0.5, [1.0, 2.0]), _pause(1, 0, "/", 0.4, [5.0, 5.0]),
                    _pause(2, 1, "/", None, None, "unmeasurable")]}
    rows = metrics.pause_errors(a, [(0.5, 1.2), (1.3, 1.9), (4.8, 5.3)])
    assert [r["id"] for r in rows] == ["/:L1:W2", "/:L2:W0"]
    assert rows[0]["human_region"] == [1.3, 1.9]  # overlaps 0.6 s, the other only 0.2 s
    assert rows[1]["human_s"] == pytest.approx(0.5)  # a zero-length window inside a pause still finds it


def test_line_errors_for_found_and_labelled_lines_only():
    a = {"lines": [{"index": 0, "status": "ok", "start": 0.1, "end": 2.0},
                   {"index": 1, "status": "not_found", "start": None, "end": None},
                   {"index": 2, "status": "ok", "start": 5.0, "end": 7.5},
                   {"index": 3, "status": "ok", "start": 8.0, "end": 9.0}]}
    res = metrics.line_errors(a, {0: (0.0, 2.2), 1: (2.5, 4.0), 3: (8.3, 9.0), 7: (12.0, 13.0)})
    assert [r["line"] for r in res["rows"]] == [1, 4]
    r = res["rows"][0]
    assert r["start_error_s"] == pytest.approx(0.1) and r["start_signed_s"] == pytest.approx(0.1)
    assert r["end_error_s"] == pytest.approx(0.2) and r["end_signed_s"] == pytest.approx(-0.2)
    assert res["not_found"] == [2] and res["unknown"] == [8]
    st = metrics.error_stats(res["rows"], "start_error_s", "start_signed_s")
    assert st["n"] == 2 and st["mean"] == pytest.approx(0.2) and st["max"] == pytest.approx(0.3)
    assert st["median"] == pytest.approx(0.2) and st["bias"] == pytest.approx(-0.1)
    assert metrics.error_stats([], "start_error_s", "start_signed_s") == {
        "n": 0, "mean": None, "median": None, "max": None, "bias": None}


def test_status_agreement_and_confusion():
    a = {"lines": [{"index": 5, "text": "x", "key": {"status": "diverged", "wpm_vs_median_pct": 19.0}},
                   {"index": 7, "text": "y", "key": {"status": "near"}}],
         "pauses": [_pause(2, 4, "/", 0.0, [8.0, 8.0], "missing"), _pause(5, 8, "//", 1.57, [22.0, 23.9])],
         "sections": [{"name": "Methods", "status": "over", "delta_s": 6.4}],
         "defines": [{"term": "degree heating weeks", "status": "defined"}]}
    human = ev.parse_statuses("KEY:L6,diverged\nKEY:L8,met\n/:L3:W4,short\nsection:methods,over\n"
                              "DEFINE:Degree Heating Weeks,defined\nKEY:L9,met\n")
    res = metrics.agreement_rows(a, human)
    assert res["absent"] == ["KEY:L9"] and res["unlabelled"] == 1  # the // has no human status
    st = metrics.agreement_stats(res["rows"])
    assert st["n"] == 5 and st["agree"] == 3 and st["pct"] == pytest.approx(60.0)
    assert st["confusion"] == {"diverged": {"diverged": 1}, "met": {"near": 1}, "short": {"missing": 1},
                               "over": {"over": 1}, "defined": {"defined": 1}}
    assert st["by_kind"]["KEY"] == {"n": 2, "agree": 1, "pct": 50.0}
    assert metrics.agreement_stats([])["pct"] is None


# ---- the synthetic recording ---------------------------------------------------------------

EXPECTED_SYNTHETIC = {"KEY:L6": "diverged", "KEY:L8": "met", "/:L3:W4": "missing", "//:L6:W8": "met",
                      "/:L8:W5": "short", "section:Opening": "met", "section:Methods": "over",
                      "section:Results": "met", "DEFINE:degree heating weeks": "defined"}


def test_make_synthetic_turns_the_fixture_truth_into_labels_and_statuses(tmp_path):
    truth = json.loads((FIXTURES / "fixture_truth.json").read_text(encoding="utf-8"))
    res = make_synthetic.write(tmp_path)
    assert res["labels"] == 19 and res["statuses"] == 9
    labs = ev.parse_labels((tmp_path / "labels.txt").read_text(encoding="utf-8"))
    assert sum(1 for l in labs if l.text.startswith("line ")) == len(truth["lines"]) == 9
    assert sum(1 for l in labs if l.text == "pause") == len(truth["silences"]) == 10
    h = ev.interpret_labels(labs)
    assert not h.warnings
    assert h.lines[5] == (20.1, 22.217) and (22.217, 23.817) in h.pauses
    st = ev.parse_statuses((tmp_path / "statuses.csv").read_text(encoding="utf-8"))
    assert {s.mark: s.status for s in st.values()} == EXPECTED_SYNTHETIC
    assert (tmp_path / "audio.ref").read_text(encoding="utf-8").strip() == "tests/fixtures/fixture.wav"
    assert (tmp_path / "script.md").read_bytes() == (FIXTURES / "fixture_script.md").read_bytes()
    assert json.loads((tmp_path / "info.json").read_text(encoding="utf-8"))["synthetic"] is True


@pytest.mark.parametrize("rate, pause, overall", [("met", "met", "met"), ("diverged", "met", "diverged"),
                                                  ("met", "missing", "diverged"), ("near", "met", "near"),
                                                  ("met", "short", "near")])
def test_synthetic_key_status_follows_the_apps_rule(rate, pause, overall):
    assert make_synthetic.key_status(rate, pause) == overall


def test_committed_synthetic_recording_is_up_to_date(tmp_path):
    make_synthetic.write(tmp_path)
    committed = ev_run.RECORDINGS_DIR / "synthetic-coral"
    for name in ("labels.txt", "statuses.csv", "script.md", "audio.ref", "info.json"):
        assert (tmp_path / name).read_bytes() == (committed / name).read_bytes(), name


def test_load_committed_synthetic_recording():
    rec = ev_run.load_recording(ev_run.RECORDINGS_DIR / "synthetic-coral")
    assert rec.audio == (FIXTURES / "fixture.wav").resolve()
    assert len(rec.labels.lines) == 9 and len(rec.labels.pauses) == 10 and len(rec.statuses) == 9
    assert rec.info["synthetic"] is True and rec.settings == Settings() and rec.settings_source == "app defaults"


# ---- loading and running without speech-to-text -----------------------------------------------

SMALL = "## Intro [0:05]\n[KEY] Trees cool the street. //\nShade matters / a lot.\n"
SPOKEN = "trees cool the street shade matters a lot"


def _recording(tmp_path, labels="0\t1.6\tline 1\n1.6\t2.4\tpause\n", statuses="KEY:L1,diverged\n", **files):
    d = tmp_path / "rec"
    d.mkdir(parents=True)
    (d / "script.md").write_text(SMALL, encoding="utf-8")
    (d / "labels.txt").write_text(labels, encoding="utf-8")
    (d / "audio.wav").write_bytes(b"not decoded by these tests")
    if statuses is not None:
        (d / "statuses.csv").write_text(statuses, encoding="utf-8")
    for name, text in files.items():
        (d / name.replace("_", ".")).write_text(text, encoding="utf-8")
    return d


def test_load_recording_checks_labels_and_statuses_against_the_script(tmp_path):
    with pytest.raises(ValueError, match="script.md has 2 lines"):
        ev_run.load_recording(_recording(tmp_path, labels="0\t1\tline 3\n"))
    with pytest.raises(ValueError, match="--list-marks"):
        ev_run.load_recording(_recording(tmp_path / "b", statuses="KEY:L2,met\n"))
    rec = ev_run.load_recording(_recording(tmp_path / "c", settings_json='{"short_pause_s": 0.4}'))
    assert rec.settings.short_pause_s == 0.4 and rec.settings_source == "settings.json"


def test_the_scripts_settings_line_wins_and_is_named(tmp_path):
    rec = ev_run.load_recording(_recording(tmp_path, settings_json='{"short_pause_s": 0.4, "long_pause_s": 2.0}',
                                           script_md="<!-- take-two: short_pause_s=0.9 -->\n" + SMALL))
    assert rec.settings.short_pause_s == 0.9 and rec.settings.long_pause_s == 2.0
    assert rec.settings_source == "settings.json + the script's settings line (short_pause_s=0.9)"
    with pytest.raises(ValueError, match="script.md: unknown setting"):
        ev_run.load_recording(_recording(tmp_path / "b", script_md="<!-- take-two: nope=1 -->\n" + SMALL))


def test_load_recording_reads_utf16_written_by_powershell(tmp_path):
    d = _recording(tmp_path, statuses=None)
    (d / "statuses.csv").write_bytes("mark,status\r\nKEY:L1,met\r\n".encode("utf-16"))
    assert ev_run.load_recording(d).statuses[("KEY", 0)].status == "met"


def test_list_marks_template_parses_back(tmp_path):
    template, numbered = ev_run.list_marks(str(_recording(tmp_path) / "script.md"))
    assert template.splitlines() == ["mark,status", "section:Intro,", "KEY:L1,", "//:L1:W4,", "/:L2:W2,"]
    assert numbered.splitlines()[0] == "line 1: [KEY] Trees cool the street."


def test_run_writes_results_without_touching_the_takes_folder(tmp_path, monkeypatch):
    from take_two import stt
    monkeypatch.setattr(stt, "audio_leaves_machine", lambda: False)  # whatever this machine's environment says
    d = _recording(tmp_path, info_json='{"synthetic": true, "speaker": "test voice"}')
    _, analysis = _analysis(SMALL, SPOKEN)
    analysis["stt"] = {"backend": "fake", "model": "fake", "device": "test", "local": True}
    seen = {}

    def fake_analyse(rec, reuse, save):
        seen["takes_dir"] = config.TAKES_DIR
        return analysis

    before = config.TAKES_DIR
    monkeypatch.setattr(ev_run, "RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(ev_run, "analyse", fake_analyse)
    out = tmp_path / "RESULTS.md"
    assert ev_run.main([d.name, "--out", str(out)]) == 0
    assert seen["takes_dir"] != before and not seen["takes_dir"].exists()  # a scratch folder, removed afterwards
    assert config.TAKES_DIR == before
    md = out.read_text(encoding="utf-8")
    assert "Synthetic voice only" in md and "say nothing about how the app does on real speakers" in md
    assert "fake `fake` on `test` (local)" in md
    assert "| `KEY:L1` |" in md and "Confusion" in md


def test_run_refuses_cloud_speech_to_text(tmp_path, monkeypatch):
    from take_two import stt
    d = _recording(tmp_path)
    monkeypatch.setattr(ev_run, "RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(stt, "audio_leaves_machine", lambda: True)
    monkeypatch.setattr(ev_run, "analyse", lambda *a: pytest.fail("the pipeline must not run"))
    assert ev_run.main([d.name, "--out", str(tmp_path / "R.md")]) == 2
    assert not (tmp_path / "R.md").exists()


def test_render_reports_a_failed_recording_and_keeps_the_others():
    md = ev_run.render([{"name": "broken", "info": {}, "error": "could not decode"}], reused=False,
                       today="2026-01-01", version="test")
    assert "0 evaluated, 1 failed (broken)" in md and "Not evaluated: the pipeline failed (could not decode)" in md


# ---- retest (noise floor) --------------------------------------------------------------------

def test_spread():
    s = retest.spread([140.0, 150.0, None, 160.0])
    assert (s["n"], s["missing"], s["min"], s["max"], s["range"]) == (3, 1, 140.0, 160.0, 20.0)
    assert s["stdev"] == pytest.approx(8.16497, abs=1e-5)  # population stdev
    assert retest.spread([None])["n"] == 0


def _take(tid, wpm, pause_s, created):
    return {"take_id": tid, "label": "", "created_at": created, "kind": "take", "baseline": {"median_wpm": wpm},
            "pauses": [{"kind": "/", "line": 2, "word_index": 4, "measured_s": pause_s}]}


def test_retest_report_spread_of_median_and_pauses():
    md = retest.report([_take("a", 140.0, 0.5, "1"), _take("b", 150.0, 0.7, "2")])
    assert "| Median wpm | 2 | 140.0 | 150.0 | 10.0 | 5.0 |" in md
    assert "| `/:L3:W4` | 2 | 0.50 | 0.70 | 0.20 | 0.10 |" in md
    one = retest.report([_take("a", 140.0, None, "1")])
    assert "at least two takes" in one
    assert "| Median wpm | 1 | 140.0 | 140.0 | – | – |" in one
    assert "| `/:L3:W4` | 0 (1 not measured) |" in one


def test_retest_command_reads_takes_and_refuses_different_scripts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    ids = ["20261009-100000-aaaa", "20261009-110000-bbbb", "20261009-120000-cccc"]
    for i, (tid, script) in enumerate(zip(ids, [SMALL, SMALL, SMALL + "One more line here.\n"])):
        (tmp_path / tid).mkdir()
        (tmp_path / tid / "script.md").write_text(script, encoding="utf-8")
        a = _take(tid, 140.0 + 10 * i, 0.5 + 0.1 * i, f"2026-10-09T1{i}:00:00")
        (tmp_path / tid / "analysis.json").write_text(json.dumps(a), encoding="utf-8")
    assert retest.main(ids[:2]) == 0
    assert "| Median wpm | 2 | 140.0 | 150.0 | 10.0 | 5.0 |" in capsys.readouterr().out
    assert retest.main(["--same-script", ids[0]]) == 0
    assert "2 take(s) of the same script" in capsys.readouterr().out
    assert retest.main(ids) == 2
    assert "do not share one script" in capsys.readouterr().err
    assert retest.main(["20261009-130000-dddd"]) == 2
