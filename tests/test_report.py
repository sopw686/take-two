"""Report additions: what was said vs. the script, cut to fit, and the focus for the next take."""

from take_two.analysis import analyze, cut_to_fit
from take_two.config import Settings
from take_two.focus import focus
from take_two.marks import parse_script
from tests.helpers import make_transcript, silences_from_gaps

GRADING = ("bad", "poor", "score", "fail", "wrong", "better", "worse", "grade")


def _run(script, text, gaps=None, durs=None, settings=None):
    s = parse_script(script)
    tr = make_transcript(text, gaps=gaps, durs=durs)
    return analyze(s, tr, silences_from_gaps(tr), settings or Settings(), tr.duration_s)


# ---- what you said vs. the script --------------------------------------------------------

SAID = """## A [0:30]
The quick brown fox jumps over the lazy dog.
We measured accuracy on the held out set.
This line will be skipped entirely by the speaker.
Finally we conclude that the method works.
"""


def test_adlibs_are_placed_between_the_script_words_they_interrupt():
    res = _run(SAID, "the quick brown fox um really jumps over the the lazy dog "
                     "we measured accuracy on the held out set "
                     "finally we conclude that the method works")
    l0 = res["lines"][0]
    spans = [(a["word_index"], a["text"], a["repeat"]) for a in l0["adlibs"]]
    assert (4, "um really", False) in spans  # sits before "jumps" (token 4)
    assert any(t == "the" and rep for _, t, rep in spans)  # the restart "the the lazy"
    assert l0["words_differ"] == 3
    assert all(a["start"] is not None and a["end"] >= a["start"] for a in l0["adlibs"])


def test_dropped_words_are_flagged_and_skipped_lines_are_not_compared():
    res = _run(SAID, "the quick brown fox jumps over the dog "
                     "we measured accuracy on the held out set "
                     "finally we conclude that the method works")
    l0 = res["lines"][0]
    assert [w["text"] for w in l0["words"] if w["dropped"]] == ["lazy"]
    assert l0["words_differ"] == 1
    skipped = res["lines"][2]
    assert skipped["status"] == "not_found" and skipped["adlibs"] == [] and skipped["words_differ"] is None


def test_adlib_between_lines_goes_to_the_nearer_line():
    # "okay so" follows line 1 with no gap and is followed by a long pause before line 2 (16 words in).
    text = ("the quick brown fox jumps over the lazy dog we measured accuracy on the held out set okay so "
            "finally we conclude that the method works")
    res = _run(SAID, text, gaps={18: 2.0})
    assert [a["text"] for a in res["lines"][1]["adlibs"]] == ["okay so"]
    assert res["lines"][1]["adlibs"][0]["word_index"] == len(res["lines"][1]["words"])
    assert res["lines"][3]["adlibs"] == []


# ---- cut to fit --------------------------------------------------------------------------

def test_cut_to_fit_is_plain_arithmetic_at_the_speakers_median():
    c = cut_to_fit("Methods", 22.0, 150.0)
    assert c["words"] == 55 and c["text"] == "Methods ran 0:22 over: about 55 words at your 150 wpm."
    assert cut_to_fit("Methods", 3.0, 150.0)["words"] == 8      # under 10: exact
    assert cut_to_fit("Methods", 13.0, 150.0)["words"] == 30    # 32.5 -> nearest 5
    none = cut_to_fit("Methods", 22.0, None)
    assert none["words"] is None and "no median" in none["text"]


TIMED = """## Intro [0:02]
This is the first line of the talk and it is fairly long.
Here is another ordinary line of roughly the same length.
## Results [0:04]
The main result is that the method works well today.
"""
TIMED_TEXT = ("this is the first line of the talk and it is fairly long "
              "here is another ordinary line of roughly the same length "
              "the main result is that the method works well today")


def test_only_sections_over_budget_get_a_cut_and_the_total_is_checked():
    res = _run(TIMED, TIMED_TEXT)
    intro, results = res["sections"]
    assert intro["status"] == "over" and intro["cut"]["words"] and "Intro ran" in intro["cut"]["text"]
    assert results["status"] == "met" and results["cut"] is None
    total = res["fit_total"]
    assert total["status"] == "over" and total["budget_s"] == 6
    assert total["cut"]["text"].startswith("The whole talk ran") and "its 0:06 budget" in total["cut"]["text"]
    assert abs(total["spoken_s"] - (res["lines"][-1]["end"] - res["lines"][0]["start"])) < 0.01


def test_total_fit_needs_every_section_budgeted_and_found():
    res = _run(TIMED.replace(" [0:04]", ""), TIMED_TEXT)
    assert res["fit_total"]["status"] == "not_measurable" and "Results has no budget" in res["fit_total"]["reason"]
    res = _run(TIMED, TIMED_TEXT.replace("the main result is that the method works well today", ""))
    assert res["fit_total"]["status"] == "not_measurable" and "Results was not found" in res["fit_total"]["reason"]


# ---- focus for the next take ---------------------------------------------------------------

def _key(index, status, pct, pause=0.9, rate_status=None, pause_status="met", text="the key line"):
    return {"index": index, "text": text, "status": "ok",
            "key": {"status": status, "rate_status": rate_status or status, "pause_status": pause_status,
                    "wpm_vs_median_pct": pct, "median_wpm": 150.0, "slower_target_pct": 10.0,
                    "pause_after_s": pause, "pause_after_target_s": 0.7}}


def _pause(line, status, measured, kind="/", wi=2):
    return {"line": line, "word_index": wi, "kind": kind, "target_s": 0.7 if kind == "/" else 1.5,
            "measured_s": measured, "status": status, "before": "this", "after": "that"}


def _section(name, status, delta, budget=60.0, line_start=0):
    return {"name": name, "status": status, "delta_s": delta, "budget_s": budget, "budget_label": "1:00",
            "line_start": line_start, "cut": None}


def _analysis(lines=(), pauses=(), sections=(), defines=()):
    return {"lines": list(lines), "pauses": list(pauses), "sections": list(sections), "defines": list(defines),
            "duration_s": 120.0, "baseline": {"median_wpm": 150.0}}


def test_focus_caps_at_three_and_every_item_cites_a_number_and_names_its_mark():
    a = _analysis(lines=[_key(0, "diverged", 20.0), _key(3, "diverged", 5.0)],
                  pauses=[_pause(1, "missing", 0.0), _pause(2, "short", 0.4)],
                  sections=[_section("Methods", "over", 12.0)],
                  defines=[{"term": "entropy", "line": 1, "status": "undefined", "first_spoken_at": 12.3, "method": "heuristic"}])
    f = focus(a)
    assert len(f["items"]) == 3 and not f["all_met"]
    for it in f["items"]:
        assert any(ch.isdigit() for ch in it["text"]) and it["mark"].split(" (")[0] in it["text"]
        assert not any(g in it["text"].lower() for g in GRADING)


def test_focus_ranks_repeated_divergence_first_then_the_largest_gap():
    current = _analysis(lines=[_key(0, "diverged", 40.0)], pauses=[_pause(1, "missing", 0.0), _pause(2, "short", 0.5)])
    # Alone: by relative gap, the missing pause (0 s of 0.7 s) is furthest from its mark, then the KEY line
    # (40% faster against 10% slower), then the short pause (0.5 of 0.7 s, only "close").
    alone = focus(current)
    assert [(i["kind"], i["status"]) for i in alone["items"]] == [("/", "missing"), ("KEY", "diverged"), ("/", "short")]
    # The short pause in line 3 also came up short in two earlier takes: it moves to the top.
    earlier = [_analysis(pauses=[_pause(2, "short", 0.3)]), _analysis(pauses=[_pause(2, "missing", 0.0)])]
    f = focus(current, earlier)
    top = f["items"][0]
    assert top["mark"] == "The / in line 3" and top["repeat"] == 3 and top["takes"] == 3
    assert [i["status"] for i in f["items"][1:]] == ["missing", "diverged"]


def test_focus_says_so_when_everything_met():
    a = _analysis(lines=[_key(0, "met", -20.0)], pauses=[_pause(1, "met", 0.9)], sections=[_section("Intro", "met", 1.0)])
    f = focus(a)
    assert f["all_met"] is True and f["items"] == [] and f["note"] == "Everything met its mark in this take."


def test_a_full_divergence_outranks_a_close_one_with_a_bigger_gap():
    a = _analysis(lines=[_key(0, "near", -8.0)], sections=[_section("Intro", "over", 4.0, budget=60.0)])
    assert [i["kind"] for i in focus(a)["items"]] == ["section", "KEY"]
