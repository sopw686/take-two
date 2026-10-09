"""Alignment that survives real speakers: misheard words, spoken years, paraphrased lines."""

import pytest

from take_two.align import align
from take_two.analysis import analyze
from take_two.config import Settings
from take_two.marks import normalize_word, parse_script
from tests.helpers import make_transcript, silences_from_gaps


def _al(script, said, **settings):
    return align(parse_script(script), make_transcript(said), Settings(**settings))


# ---- misheard words -------------------------------------------------------------------------

def test_a_misheard_word_matches_its_script_word():
    al = _al("The model predicted bleaching three weeks early.", "the model predicted leaching three weeks early")
    assert al.lines[0].coverage == 1.0
    tok = next(t for t in al.tokens if t.token.text == "bleaching")
    assert tok.fuzzy and tok.heard == "leaching" and tok.start is not None
    assert not any(t.fuzzy for t in al.tokens if t.token.text != "bleaching")


@pytest.mark.parametrize("script_word,heard", [("than", "then"), ("possible", "impossible"),
                                               ("seventy", "seventeen"), ("consistent", "inconsistent"),
                                               ("fourteenth", "fourteen"), ("thousands", "thousand")])
def test_loose_matching_never_flips_meaning_or_numbers(script_word, heard):
    al = _al(f"It was {script_word} at the end.", f"it was {heard} at the end")
    tok = next(t for t in al.tokens if t.token.text == script_word)
    assert not tok.aligned


def test_exact_only_when_the_threshold_is_one():
    al = _al("The model predicted bleaching early.", "the model predicted leaching early", fuzzy_match_ratio=1.0)
    assert not next(t for t in al.tokens if t.token.text == "bleaching").aligned


def test_loose_matches_stay_between_exact_ones():
    # "leaching" is said after "methods", so it must not be paired back across the exact "methods" to "bleaching".
    al = _al("First the bleaching. Then the methods were described.", "first the methods were described then the leaching")
    bleach = next(t for t in al.tokens if t.token.text == "bleaching.")
    meth = next(t for t in al.tokens if t.token.text == "methods")
    assert meth.aligned and not bleach.aligned


def test_short_words_match_only_exactly_unless_lowered():
    assert not next(t for t in _al("The cat sat there.", "the cats sat there").tokens if t.token.text == "cat").aligned
    tok = next(t for t in _al("The cat sat there.", "the cats sat there", fuzzy_min_chars=3).tokens if t.token.text == "cat")
    assert tok.fuzzy and tok.heard == "cats"


def test_settings_bounds_for_alignment():
    with pytest.raises(ValueError):
        Settings(fuzzy_match_ratio=0.5)
    with pytest.raises(ValueError):
        Settings(paraphrase_min_words_pct=150)
    for bad in (2, 11):
        with pytest.raises(ValueError):
            Settings(fuzzy_min_chars=bad)


# ---- numbers and years ------------------------------------------------------------------------

@pytest.mark.parametrize("said", ["in twenty nineteen we began", "in two thousand nineteen we began",
                                  "in two thousand and nineteen we began", "in 2019 we began"])
def test_a_year_matches_however_it_is_said(said):
    assert _al("In 2019 we began.", said).lines[0].coverage == 1.0


def test_spoken_years_in_the_script_match_digits_in_the_transcript():
    assert _al("Back in nineteen ninety nine, then.", "back in 1999 then").lines[0].coverage == 1.0
    assert _al("It opened in 1905.", "it opened in nineteen oh five").lines[0].coverage == 1.0
    assert _al("About 1500 reefs.", "about fifteen hundred reefs").lines[0].coverage == 1.0


def test_a_spoken_year_keeps_its_timestamps():
    tr = make_transcript("in twenty nineteen we began")
    al = align(parse_script("In 2019 we began."), tr)
    year = next(t for t in al.tokens if t.token.text == "2019")
    assert year.start == tr.words[1].start and year.end == tr.words[2].end


def test_ordinary_numbers_are_not_mistaken_for_years():
    assert _al("About 25% of reefs.", "about twenty five percent of reefs").lines[0].coverage == 1.0
    assert _al("It cost 1,200 dollars.", "it cost one thousand two hundred dollars").lines[0].coverage == 1.0


def test_known_limitation_two_numbers_said_as_a_year():
    # "fifteen twenty" reads as the year 1520, so "15 to 20" only partly matches. Recorded in DECISIONS.md.
    assert _al("From 15 to 20 minutes.", "from fifteen twenty minutes").lines[0].coverage < 1.0


def test_numbers_never_join_into_a_year_across_a_sentence_end():
    script = "The sample size was 20.\n15 of them bleached badly."
    s = parse_script(script)
    al = align(s, make_transcript("the sample size was 20. 15 of them bleached badly"))
    assert al.lines[0].coverage == 1.0 and al.lines[1].coverage == 1.0


def test_punctuation_no_longer_hides_a_number():
    assert normalize_word("2019.") == ["two", "thousand", "nineteen"]
    assert normalize_word("(30") == ["thirty"]
    assert _al("The data ends in 2019.", "the data ends in 2019 and").lines[0].coverage == 1.0


# ---- paraphrased lines ---------------------------------------------------------------------------

SCRIPT = """## A [0:30]
The quick brown fox jumps over the lazy dog.
[KEY] We measured remarkable accuracy on the held out set. //
Finally we conclude that the method works.
"""
FIRST = "the quick brown fox jumps over the lazy dog"
LAST = "finally we conclude that the method works"


def _run(middle, gaps=None):
    s = parse_script(SCRIPT)
    tr = make_transcript(f"{FIRST} {middle} {LAST}".replace("  ", " "), gaps=gaps)
    return analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s), tr


def test_a_paraphrased_line_is_timed_but_not_rate_checked():
    middle = "so basically our accuracy was remarkable on data we never trained on"
    res, tr = _run(middle, gaps={20: 1.6})  # a 1.6 s pause after the paraphrase
    line = res["lines"][1]
    assert line["status"] == "paraphrased" and line["wpm"] is None
    assert line["start"] == tr.words[9].start and line["end"] == tr.words[20].end
    assert line["said"]["text"] == middle
    key = line["key"]
    assert key["rate_status"] == "unmeasurable" and key["paraphrased"] and "paraphrased" in key["rate_note"]
    assert key["pause_status"] == "met" and key["status"] == "unmeasurable"  # never "close" without a rate
    # It counts toward section timing, not toward the median or the key-line tally.
    assert res["sections"][0]["start"] == res["lines"][0]["start"] and res["sections"][0]["end"] == res["lines"][2]["end"]
    assert res["baseline"]["lines_used"] == 2
    assert "1 line paraphrased: timed, not rate-checked." in res["summary"]
    assert not any("key lines met" in s for s in res["summary"])
    # The // at the end of the line is measured from its last word to the next line.
    pause = res["pauses"][0]
    assert pause["status"] == "met" and pause["measured_s"] >= 1.6
    # Its words are not shown as ad-libs on the neighbours.
    assert res["lines"][0]["adlibs"] == [] and res["lines"][2]["adlibs"] == []


def test_a_paraphrased_key_line_without_its_pause_diverged():
    res, _ = _run("so basically our accuracy was remarkable on data we never trained on")
    key = res["lines"][1]["key"]
    assert key["pause_status"] == "missing" and key["status"] == "diverged"


def test_an_aside_in_place_of_a_line_stays_not_found():
    # Enough words between the neighbours, but none of the line's own words.
    res, _ = _run("sorry let me get some water before I go on with this")
    assert res["lines"][1]["status"] == "not_found" and "start" in res["lines"][1] and res["lines"][1]["start"] is None


def test_a_skipped_line_stays_not_found():
    res, _ = _run("")
    assert res["lines"][1]["status"] == "not_found"
    assert "1 key line not found in this take." in res["summary"]
    assert not any("of 0 key lines" in s for s in res["summary"])


def test_fillers_do_not_count_as_speech():
    assert _run("our remarkable result")[0]["lines"][1]["status"] == "paraphrased"
    assert _run("um uh remarkable uh")[0]["lines"][1]["status"] == "not_found"


def test_a_common_word_alone_does_not_make_an_aside_a_paraphrase():
    # The aside shares only "this" with the line; common words are not the line's own words.
    script = SCRIPT.replace("We measured remarkable accuracy on the held out set.", "This method measured remarkable accuracy.")
    s = parse_script(script)
    tr = make_transcript(f"{FIRST} sorry let me find this slide again one moment {LAST}")
    res = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    assert res["lines"][1]["status"] == "not_found"


def test_a_neighbours_stray_last_word_and_its_pause_stay_with_the_neighbour():
    # Line 1 ends with a misheard "hound" and a 1.6 s pause before the paraphrase starts.
    script = SCRIPT.replace("The quick brown fox jumps over the lazy dog.", "[KEY] The quick brown fox jumps over the lazy dog.")
    s = parse_script(script)
    middle = "so basically our accuracy was remarkable on data we never trained on"
    tr = make_transcript(f"the quick brown fox jumps over the lazy hound {middle} {LAST}", gaps={8: 1.6})
    res = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    assert res["lines"][1]["status"] == "paraphrased" and res["lines"][1]["said"]["text"] == middle
    key = res["lines"][0]["key"]
    assert key["pause_after_s"] >= 1.6 and key["pause_status"] == "met"


def test_a_paraphrased_first_line_of_a_section_sets_the_section_start():
    script = ("## A [0:05]\nThe quick brown fox jumps over the lazy dog.\n"
              "## B [0:05]\n[KEY] We measured remarkable accuracy on the held out set. //\n"
              "Finally we conclude that the method works.\n")
    s = parse_script(script)
    tr = make_transcript(f"{FIRST} so basically our accuracy was remarkable on data we never trained on {LAST}")
    res = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    assert res["lines"][1]["status"] == "paraphrased"
    sec = res["sections"][1]
    assert sec["start"] == res["lines"][1]["start"]
    assert abs(sec["duration_s"] - (res["lines"][2]["end"] - res["lines"][1]["start"])) < 0.02


def test_a_drill_reports_a_paraphrased_line_as_timed_not_missing():
    from take_two.pipeline import drill_summary
    res, _ = _run("so basically our accuracy was remarkable on data we never trained on", gaps={20: 1.6})
    text = drill_summary(res, {"kind": "section", "line_start": 0})
    line2 = next(t for t in text if t.startswith("Line 2 [KEY]"))
    assert "paraphrased" in line2 and "pause after" in line2 and "met your mark" in line2
    assert not any("Line 2 was not found" in t for t in text)


def test_a_mark_inside_a_paraphrased_line_is_not_measured():
    script = SCRIPT.replace("remarkable accuracy / on", "x").replace("[KEY] We measured remarkable accuracy on the held out set. //",
                                                                     "We measured remarkable accuracy / on the held out set.")
    s = parse_script(script)
    tr = make_transcript(f"{FIRST} so basically our accuracy was remarkable on data we never trained on {LAST}")
    res = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    assert res["lines"][1]["status"] == "paraphrased"
    assert res["pauses"][0]["status"] == "unmeasurable" and "paraphrased" in res["pauses"][0]["note"]


def test_the_threshold_for_enough_speech_is_a_setting():
    s = parse_script(SCRIPT)
    tr = make_transcript(f"{FIRST} our accuracy was remarkable {LAST}")
    loose = analyze(s, tr, silences_from_gaps(tr), Settings(), tr.duration_s)
    strict = analyze(s, tr, silences_from_gaps(tr), Settings(paraphrase_min_words_pct=80), tr.duration_s)
    assert loose["lines"][1]["status"] == "paraphrased" and strict["lines"][1]["status"] == "not_found"
