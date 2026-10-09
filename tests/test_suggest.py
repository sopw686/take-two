"""Suggestion validator and caps, with a mocked model that over-marks."""

from take_two.marks import parse_script
from take_two.suggest import Proposal, ProposedMark, apply_marks, build_user_prompt, validate_and_cap

LINES = [
    "Coral reefs cover less than one percent of the ocean floor yet they shelter a quarter of marine species.",
    "When water stays warm too long corals expel the algae that feed them and we call this bleaching.",
    "Today I will show that we can predict which reefs will bleach weeks ahead using only satellite data.",
    "We used twenty years of sea surface temperature records covering four hundred reefs.",
    "For each reef we computed degree heating weeks the accumulated heat above the local summer maximum.",
    "We trained a gradient boosted model and tested it on reefs it had never seen.",
    "The model predicted bleaching three weeks in advance with eighty seven percent accuracy.",
    "That is two weeks earlier than the warning system managers use today.",
    "Three weeks is enough time to deploy shading and collect samples before the damage is done.",
    "Thank you.",
]
UNSECTIONED = "\n".join(LINES)
SECTIONED = "## Intro [0:40]\n" + "\n".join(LINES[:3]) + "\n## Methods [0:40]\n" + "\n".join(LINES[3:6]) + "\n## Results [0:40]\n" + "\n".join(LINES[6:])


def overmarked() -> Proposal:
    marks = [ProposedMark(type="key", line_index=i, reason=f"key {i}") for i in range(8)]          # 8 keys
    marks += [ProposedMark(type="pause", line_index=i, word_index=3, reason="pause") for i in range(10)]
    marks += [ProposedMark(type="long_pause", line_index=6, word_index=13, reason="land it")]
    marks += [ProposedMark(type="define", line_index=4, term="degree heating weeks", reason="jargon"),
              ProposedMark(type="define", line_index=1, term="bleaching", reason="jargon"),
              ProposedMark(type="define", line_index=5, term="gradient boosted model", reason="jargon"),
              ProposedMark(type="define", line_index=0, term="ocean", reason="common word but model says so"),
              ProposedMark(type="define", line_index=0, term="quantum chromodynamics", reason="not in script"),
              ProposedMark(type="define", line_index=2, term="satellite data", reason="fifth define, over cap")]
    marks += [ProposedMark(type="key", line_index=42, reason="out of range"),
              ProposedMark(type="pause", line_index=0, word_index=99, reason="word out of range"),
              ProposedMark(type="pause", line_index=0, word_index=-1, reason="negative")]
    return Proposal(marks=marks)


def test_caps_enforced_on_sectioned_script():
    script = parse_script(SECTIONED)
    acc, dropped = validate_and_cap(script, overmarked(), 150.0, "your median 150 wpm from your latest take", None)
    keys = [a for a in acc if a["type"] == "key"]
    assert len(keys) == 3
    assert len({script.lines[k["line_index"]].section for k in keys}) == 3   # one per section
    pauses = [a for a in acc if a["type"] in ("pause", "long_pause")]
    total_words = sum(ln.word_count for ln in script.lines)
    assert len(pauses) <= -(-total_words // 40)
    defines = [a["term"] for a in acc if a["type"] == "define"]
    assert "quantum chromodynamics" not in defines
    assert len(defines) <= 4
    assert not any(a["type"] == "section" for a in acc)
    reasons = {d["reason"]: d["count"] for d in dropped}
    assert reasons["line index out of range"] == 1
    assert reasons["pause word index out of range"] == 3  # line 9 has 2 words, plus 99 and -1
    assert reasons["define term not found in the script"] == 1
    assert "more than one key line in a section" in reasons or "more than three key lines" in reasons


def test_sections_proposed_only_when_missing_and_budgets_computed_in_code():
    script = parse_script(UNSECTIONED)
    prop = Proposal(marks=[
        ProposedMark(type="section", line_index=3, name="Methods", reason="methods start here"),
        ProposedMark(type="section", line_index=6, name="Results", reason="results start here"),
        ProposedMark(type="key", line_index=6, reason="the finding"),
        ProposedMark(type="key", line_index=7, reason="second key in same section"),
    ])
    acc, dropped = validate_and_cap(script, prop, 150.0, "estimate at 140 wpm (no take yet)", None)
    secs = [a for a in acc if a["type"] == "section"]
    assert [s["line_index"] for s in secs] == [0, 3, 6]        # an opening section is added at line 0
    assert all(s["budget_s"] and s["budget_s"] % 5 == 0 for s in secs)
    words = [sum(script.lines[i].word_count for i in r) for r in (range(0, 3), range(3, 6), range(6, 10))]
    for s, w in zip(secs, words):
        assert abs(s["budget_s"] - w / 150 * 60) <= 5
        assert s["budget_estimated"] is True
    keys = [a for a in acc if a["type"] == "key"]
    assert [k["line_index"] for k in keys] == [6]                # second key in the same proposed section dropped
    assert any(d["reason"] == "more than one key line in a section" for d in dropped)


def test_target_length_scales_budgets_proportionally():
    script = parse_script(UNSECTIONED)
    prop = Proposal(marks=[ProposedMark(type="section", line_index=5, name="Second half", reason="r")])
    acc, _ = validate_and_cap(script, prop, 150.0, "estimate", 120)
    secs = [a for a in acc if a["type"] == "section"]
    assert abs(sum(s["budget_s"] for s in secs) - 120) <= 10


def test_existing_marks_are_not_duplicated():
    script = parse_script("[KEY] The main / finding. [DEFINE: finding]\nAnother line here.")
    prop = Proposal(marks=[ProposedMark(type="key", line_index=0, reason="r"),
                           ProposedMark(type="pause", line_index=0, word_index=2, reason="r"),
                           ProposedMark(type="define", line_index=0, term="finding", reason="r"),
                           ProposedMark(type="key", line_index=1, reason="ok")])
    acc, dropped = validate_and_cap(script, prop, 140.0, "estimate", None)
    assert [a["type"] for a in acc] == ["key"] and acc[0]["line_index"] == 1
    assert {d["reason"] for d in dropped} == {"line already marked key", "pause already marked at that spot", "term already has a define mark"}


def test_reason_is_capped_at_twenty_words():
    script = parse_script(UNSECTIONED)
    prop = Proposal(marks=[ProposedMark(type="key", line_index=0, reason=" ".join(["why"] * 40))])
    acc, _ = validate_and_cap(script, prop, 140.0, "estimate", None)
    assert len(acc[0]["reason"].rstrip("…").split()) <= 20


def test_apply_marks_rewrites_only_accepted_lines():
    text = "## Intro [0:10]\nFirst line of text here.\nSecond line with *stress* and km/h.\n\nThird line."
    accepted = [
        {"type": "key", "raw_line_no": 1},
        {"type": "pause", "raw_line_no": 1, "word_index": 2},
        {"type": "long_pause", "raw_line_no": 1, "word_index": 5},
        {"type": "define", "raw_line_no": 2, "term": "km/h"},
    ]
    out = apply_marks(text, accepted).splitlines()
    assert out[0] == "## Intro [0:10]"
    assert out[1] == "[KEY] First line / of text here. //"
    assert out[2] == "[DEFINE: km/h] Second line with *stress* and km/h."
    assert out[4] == "Third line."
    parsed = parse_script("\n".join(out))
    assert parsed.lines[0].is_key and [(p.word_index, p.kind) for p in parsed.lines[0].pauses] == [(2, "/"), (5, "//")]
    assert parsed.lines[1].text == "Second line with stress and km/h."


def test_apply_section_inserts_header_with_budget():
    text = "Line a.\nLine b.\nLine c."
    out = apply_marks(text, [{"type": "section", "raw_line_no": 1, "name": "Results", "budget_s": 65}])
    assert out.splitlines() == ["Line a.", "", "## Results [1:05]", "Line b.", "Line c."]


def test_prompt_mentions_goal_and_existing_sections():
    script = parse_script(SECTIONED)
    p = build_user_prompt(script, "somber", "I want the ending to land.", 120)
    assert "somber" in p and "Do not propose sections" in p and "Target length: 2:00" in p and "ending to land" in p
    assert "0: Coral reefs" in p


def test_term_with_symbol_words_does_not_crash():
    from take_two.suggest import _term_in_text
    assert _term_in_text("p < 0.05", "we found p < 0.05 here")
    assert not _term_in_text("p < 0.05", "we found nothing here")
