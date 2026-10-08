"""Threshold logic on hand-built transcripts (no audio, no STT)."""

from marked.analysis import analyze
from marked.config import Settings
from marked.marks import parse_script
from tests.helpers import make_transcript, silences_from_gaps

SCRIPT = """## Intro [0:20]
This is the first line of the talk and it is fairly long.
Here is another ordinary line of roughly the same length.
## Results [0:10]
[KEY] The main result is that the method works well. //
We then move / on to the next point in the talk.
And we close with a final ordinary line of text.
"""
TEXT = ("this is the first line of the talk and it is fairly long "
        "here is another ordinary line of roughly the same length "
        "the main result is that the method works well "
        "we then move on to the next point in the talk "
        "and we close with a final ordinary line of text")
KEY_WORDS = range(23, 32)   # "the main result ... well" are words 23..31
SLASH_AFTER = 34            # "/" sits after "move" (word 34)


def _run(gaps=None, durs=None, settings=None):
    s = parse_script(SCRIPT)
    tr = make_transcript(TEXT, gaps=gaps, durs=durs)
    return analyze(s, tr, silences_from_gaps(tr), settings or Settings(), tr.duration_s)


def _key(res):
    return next(r["key"] for r in res["lines"] if r.get("key"))


def test_key_line_met_when_slower_and_pause_after():
    durs = {i: 0.5 for i in KEY_WORDS}            # 0.5 + 0.1 = 0.6 s/word -> 100 wpm vs 150
    gaps = {31: 1.6}                              # "//" after the key line
    res = _run(gaps, durs)
    k = _key(res)
    assert k["rate_status"] == "met" and k["wpm_vs_median_pct"] < -10
    assert k["pause_status"] == "met" and abs(k["pause_after_s"] - 1.6) < 0.05
    assert k["status"] == "met"
    pause = next(p for p in res["pauses"] if p["kind"] == "//")
    assert pause["status"] == "met" and abs(pause["measured_s"] - 1.6) < 0.05


def test_key_line_rushed_is_diverged_even_with_pause():
    durs = {i: 0.15 for i in KEY_WORDS}           # 0.15 + 0.05 = 0.2 s/word -> 300 wpm
    gaps = {i: 0.05 for i in KEY_WORDS}
    gaps[31] = 1.6
    res = _run(gaps, durs)
    k = _key(res)
    assert k["rate_status"] == "diverged" and k["wpm_vs_median_pct"] > 0
    assert k["pause_status"] == "met"
    assert k["status"] == "diverged"


def test_key_line_near_when_slightly_slower():
    durs = {i: 0.32 for i in KEY_WORDS}           # 0.42 s/word -> ~143 wpm, ~5% slower
    res = _run({31: 1.6}, durs)
    k = _key(res)
    assert k["rate_status"] == "near" and -10 < k["wpm_vs_median_pct"] < 0
    assert k["status"] == "near"


def test_key_line_missing_pause_is_diverged():
    durs = {i: 0.5 for i in KEY_WORDS}
    res = _run({}, durs)                          # no pause after the line
    k = _key(res)
    assert k["rate_status"] == "met" and k["pause_status"] == "missing"
    assert k["status"] == "diverged"


def test_pause_statuses_short_and_missing():
    missing = _run({25: 0.3})                     # a gap somewhere irrelevant; "/" has none
    p = next(p for p in missing["pauses"] if p["kind"] == "/")
    assert p["status"] == "missing" and p["measured_s"] == 0.0
    short = _run({SLASH_AFTER: 0.3})
    p = next(p for p in short["pauses"] if p["kind"] == "/")
    assert p["status"] == "short" and abs(p["measured_s"] - 0.3) < 0.05
    met = _run({SLASH_AFTER: 0.8})
    assert next(p for p in met["pauses"] if p["kind"] == "/")["status"] == "met"


def test_thresholds_are_user_adjustable():
    res = _run({SLASH_AFTER: 0.3}, settings=Settings(short_pause_s=0.25))
    assert next(p for p in res["pauses"] if p["kind"] == "/")["status"] == "met"
    res = _run({SLASH_AFTER: 0.3}, settings=Settings(short_pause_s=1.0, pause_near_ratio=0.5))
    assert next(p for p in res["pauses"] if p["kind"] == "/")["status"] == "missing"
    durs = {i: 0.5 for i in KEY_WORDS}
    k = _key(_run({31: 1.6}, durs, Settings(key_slower_pct=40)))
    assert k["rate_status"] == "near"             # 33% slower is not enough for a 40% target


def test_section_budget_status_and_delta():
    res = _run()
    intro = res["sections"][0]
    assert intro["budget_s"] == 20.0
    assert intro["status"] == "under" and intro["delta_s"] < -3
    assert "under" in intro["delta_label"]
    loose = _run(settings=Settings(section_tolerance_pct=60))
    assert loose["sections"][0]["status"] == "met"


def test_pause_measurement_is_traceable():
    res = _run({SLASH_AFTER: 0.8})
    p = next(p for p in res["pauses"] if p["kind"] == "/")
    assert p["window"][0] == p["at_time"]
    assert p["before"] == "move" and p["after"] == "on"
    assert abs(p["whisper_gap_s"] - p["measured_s"]) < 0.01


def test_skipped_line_reported_not_scored():
    s = parse_script(SCRIPT)
    text = TEXT.replace("here is another ordinary line of roughly the same length ", "")
    tr = make_transcript(text)
    res = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    assert res["lines"][1]["status"] == "not_found" and res["lines"][1]["wpm"] is None
    assert any("not found" in s for s in res["summary"])


def test_summary_wording_is_non_judgmental():
    res = _run({SLASH_AFTER: 0.3})
    text = " ".join(res["summary"]).lower()
    for bad in ("bad", "poor", "score", "fail", "wrong"):
        assert bad not in text
