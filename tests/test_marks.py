from take_two.marks import format_budget, normalize_word, parse_script, strip_marks

SCRIPT = """<!-- comment line -->
## Intro [1:30]
[KEY] The main / finding is // here.
We define [DEFINE: convolution] a convolution as a sliding dot product.

## Methods
Plain line with *emphasis* and 95% and a time-stretched word.
## Results [0:05]
"""


def test_sections_and_budgets():
    s = parse_script(SCRIPT)
    assert [sec.name for sec in s.sections] == ["Intro", "Methods", "Results"]
    assert [sec.budget_s for sec in s.sections] == [90.0, None, 5.0]
    assert (s.sections[0].line_start, s.sections[0].line_end) == (0, 2)
    assert (s.sections[1].line_start, s.sections[1].line_end) == (2, 3)
    assert (s.sections[2].line_start, s.sections[2].line_end) == (3, 3)


def test_key_pauses_and_display_text():
    s = parse_script(SCRIPT)
    ln = s.lines[0]
    assert ln.is_key
    assert ln.text == "The main finding is here."
    assert [(p.word_index, p.kind) for p in ln.pauses] == [(2, "/"), (4, "//")]
    assert ln.raw_line_no == 2


def test_define_and_emphasis():
    s = parse_script(SCRIPT)
    assert [(d.term, d.line, d.section) for d in s.defines] == [("convolution", 1, 0)]
    assert s.lines[1].text == "We define a convolution as a sliding dot product."
    assert s.lines[2].emphasis == [3]
    assert s.lines[2].text.split()[3] == "emphasis"


def test_implicit_section_when_no_header():
    s = parse_script("Just a line.\nAnother one.")
    assert len(s.sections) == 1 and s.sections[0].name == "" and s.sections[0].budget_s is None
    assert s.sections[0].line_end == 2


def test_slash_inside_word_is_not_a_pause():
    s = parse_script("Use km/h and/or m/s here.")
    assert s.lines[0].pauses == []
    assert s.lines[0].text == "Use km/h and/or m/s here."


def test_normalize_numbers_and_punctuation():
    assert normalize_word("95%") == ["ninety", "five", "percent"]
    assert normalize_word("1,200") == ["one", "thousand", "two", "hundred"]
    assert normalize_word("3.5") == ["three", "point", "five"]
    assert normalize_word("Time-stretched,") == ["time", "stretched"]
    assert normalize_word("don't") == ["dont"]
    assert normalize_word("--") == []


def test_strip_marks():
    assert strip_marks(SCRIPT).splitlines()[0] == "The main finding is here."
    assert "##" not in strip_marks(SCRIPT)


def test_format_budget():
    assert format_budget(90) == "1:30"
    assert format_budget(None) == ""


def test_raw_line_numbers_survive_multiline_comments():
    text = "<!-- a\nmulti-line\ncomment -->\n## S [0:10]\nFirst line.\n\nSecond line."
    s = parse_script(text)
    assert [ln.raw_line_no for ln in s.lines] == [4, 6]
    assert s.sections[0].raw_line_no == 3
    assert text.splitlines()[4] == "First line."


def test_emphasis_with_trailing_punctuation():
    s = parse_script("Hello *world*, again.")
    assert s.lines[0].emphasis == [1]
    assert s.lines[0].text == "Hello world, again."
