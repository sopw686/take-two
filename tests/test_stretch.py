"""Conventions preset, coaching validation, emphasis plumbing, take comparison."""

import numpy as np

from marked.analysis import analyze
from marked.coaching import CoachOutput, CoachSuggestion, all_marks_met, coach, validate
from marked.compare import compare_takes
from marked.config import Settings
from marked.conventions import conventions_report
from marked.emphasis import emphasis_report
from marked.marks import parse_script
from tests.helpers import make_transcript, silences_from_gaps


def _analysis(script_text, text, settings=None, gaps=None, durs=None):
    s = parse_script(script_text)
    tr = make_transcript(text, gaps=gaps, durs=durs)
    return s, tr, analyze(s, tr, silences_from_gaps(tr), settings or Settings(), tr.duration_s)


def test_conventions_only_when_enabled_and_counts_fillers():
    script = "This is a line of text that is long enough.\nAnother line of text follows here."
    text = "this is um a line of text that is long enough another line you know of text follows here"
    _, tr, a = _analysis(script, text)
    assert "conventions" not in a
    st = Settings(conventions_enabled=True, conventions_wpm_min=100, conventions_wpm_max=200)
    rep = conventions_report(tr, a, st)
    assert rep["enabled"] and rep["filler_count"] == 2
    assert {f["text"] for f in rep["fillers"]} == {"um", "you know"}
    assert rep["wpm_status"] == "met" and 100 <= rep["overall_wpm"] <= 200
    assert rep["fillers"][0]["start"] is not None


def test_conventions_band_is_user_editable():
    script = "This is a line of text that is long enough.\nAnother line of text follows here."
    text = "this is a line of text that is long enough another line of text follows here"
    _, tr, a = _analysis(script, text)
    rep = conventions_report(tr, a, Settings(conventions_enabled=True, conventions_wpm_min=200, conventions_wpm_max=250))
    assert rep["wpm_status"] == "diverged"


class FakeLLM:
    name = "fake"
    available = True

    def __init__(self, out):
        self.out = out
        self.calls = 0
        self.last_user = ""

    def complete_structured(self, system, user, output, max_tokens=4000):
        self.calls += 1
        self.last_user = user
        return self.out


def test_coaching_requires_numbers_and_caps_at_three():
    out = CoachOutput(all_met=False, suggestions=[
        CoachSuggestion(text="Your key line in Results ran 22% faster than your median.", mark="KEY line 6", metric="22% faster"),
        CoachSuggestion(text="Try to sound more confident.", mark="", metric=""),
        CoachSuggestion(text="The // after line 2 measured 0.4 s against your 1.5 s mark.", mark="// line 2", metric="0.4 s"),
        CoachSuggestion(text="Methods ran 0:40 over its 1:00 budget.", mark="section Methods", metric="0:40 over"),
        CoachSuggestion(text="A fifth one with 5 numbers.", mark="", metric="5"),
    ])
    v = validate(out, {})
    assert len(v["suggestions"]) == 3
    assert all(any(ch.isdigit() for ch in s["text"] + s["metric"]) for s in v["suggestions"])
    assert "confident" not in " ".join(s["text"] for s in v["suggestions"])


def test_coaching_skips_model_when_all_met_and_without_key():
    script = "## A [0:05]\n[KEY] This key line is slow and long enough. //\nAnother ordinary line of text here."
    text = "this key line is slow and long enough another ordinary line of text here"
    durs = {i: 0.5 for i in range(0, 8)}
    _, _, a = _analysis(script, text, gaps={7: 1.6}, durs=durs, settings=Settings(section_tolerance_pct=100))
    assert all_marks_met(a)
    llm = FakeLLM(None)
    r = coach(a, llm)
    assert r["all_met"] is True and r["suggestions"] == [] and llm.calls == 0
    r2 = coach(a, type("NoLLM", (), {"available": False})())
    assert r2["available"] is False


def test_coaching_sends_measurements_not_audio_and_includes_history():
    script = "## A [0:05]\n[KEY] This key line is fast. //\nAnother ordinary line of text here."
    text = "this key line is fast another ordinary line of text here"
    _, _, a = _analysis(script, text)
    llm = FakeLLM(CoachOutput(all_met=False, suggestions=[CoachSuggestion(text="KEY line 0 ran 10% faster than your median.", mark="KEY line 0", metric="10% faster")]))
    r = coach(a, llm, earlier=[a])
    assert llm.calls == 1 and "earlier_takes_same_script" in llm.last_user and "wpm_vs_median_pct" in llm.last_user
    assert "audio" not in llm.last_user.lower().replace("audio_url", "")
    assert r["suggestions"][0]["mark"] == "KEY line 0"


def test_emphasis_reports_louder_word():
    script = "The result was *huge* and clear and obvious to all."
    text = "the result was huge and clear and obvious to all"
    s, tr, a = _analysis(script, text)
    sr = 16000
    audio = np.zeros(int(tr.duration_s * sr) + sr, dtype=np.float32)
    rng = np.random.default_rng(0)
    for i, w in enumerate(tr.words):
        amp = 0.3 if i == 3 else 0.05
        seg = slice(int(w.start * sr), int(w.end * sr))
        audio[seg] = (amp * np.sin(2 * np.pi * 150 * np.arange(seg.stop - seg.start) / sr)).astype(np.float32) + 0.001 * rng.standard_normal(seg.stop - seg.start).astype(np.float32)
    rows = emphasis_report(s, a, audio, sr)
    assert len(rows) == 1 and rows[0]["word"] == "huge"
    assert rows[0]["delta_db"] > 3 and rows[0]["status"] == "met"


def test_compare_takes_counts_outcomes_per_mark():
    script = "## A [0:05]\n[KEY] This key line is fast. //\nAnother / ordinary line of text here."
    text = "this key line is fast another ordinary line of text here"
    _, _, a1 = _analysis(script, text)
    _, _, a2 = _analysis(script, text, gaps={4: 1.6, 5: 0.8})
    cmp = compare_takes([a1, a2])
    assert cmp["takes"] == 2
    key = next(m for m in cmp["marks"] if m["kind"] == "KEY")
    assert key["takes"] == 2 and set(key["statuses"]) <= {"met", "near", "diverged"}
    pause = next(m for m in cmp["marks"] if m["kind"] == "/")
    assert pause["statuses"] == ["missing", "met"]
    assert any("2 takes" in s or "of 2" in s for s in cmp["summary"])


def _key_take(status, pct):
    return {"take_id": "t", "lines": [{"index": 0, "text": "key", "key": {"status": status, "wpm_vs_median_pct": pct}}],
            "pauses": [], "sections": [], "defines": []}


def test_compare_does_not_call_a_missed_pause_rushing():
    # Diverged because of the pause (slower than median), plus one met take that ran fast.
    cmp = compare_takes([_key_take("diverged", -20.0), _key_take("diverged", -15.0), _key_take("met", 5.0)])
    assert not any("rushed" in s for s in cmp["summary"])
    assert any("diverged on key line 1" in s and "2 of 3" in s for s in cmp["summary"])
    cmp = compare_takes([_key_take("diverged", 10.0), _key_take("diverged", 12.0)])
    assert any("rushed key line 1" in s and "2 of 2" in s for s in cmp["summary"])
