from marked.align import align
from marked.marks import parse_script
from tests.helpers import make_transcript

SCRIPT = """## A [0:30]
The quick brown fox jumps over the lazy dog.
We measured 95% accuracy on the held-out set.
This line will be skipped entirely by the speaker.
## B [0:30]
Finally we conclude that the method works.
"""


def test_exact_alignment_gives_full_coverage_and_times():
    s = parse_script(SCRIPT)
    tr = make_transcript("the quick brown fox jumps over the lazy dog "
                         "we measured ninety five percent accuracy on the held out set "
                         "this line will be skipped entirely by the speaker "
                         "finally we conclude that the method works")
    al = align(s, tr)
    assert all(lt.coverage == 1.0 for lt in al.lines)
    assert al.lines[0].start == tr.words[0].start
    assert al.lines[0].end == tr.words[8].end
    assert al.lines[1].start == tr.words[9].start


def test_skipped_line_and_adlib_are_tolerated():
    s = parse_script(SCRIPT)
    tr = make_transcript("the quick brown fox jumps over the lazy dog "
                         "um so basically we measured 95% accuracy on the held-out set okay "
                         "finally we conclude that the method works")
    al = align(s, tr)
    assert al.lines[0].coverage == 1.0
    assert al.lines[1].coverage == 1.0
    assert al.lines[2].coverage == 0.0 and al.lines[2].start is None
    assert al.lines[3].coverage == 1.0
    assert len(tr.words) - len(al.matched_transcript) == 4  # um so basically okay


def test_repeated_words_and_restart():
    s = parse_script("The model the model predicted the result.\nThe result was clear.")
    tr = make_transcript("the model the the model predicted the result the result was clear")
    al = align(s, tr)
    assert al.lines[0].coverage == 1.0
    assert al.lines[1].coverage == 1.0
    assert al.lines[1].start > al.lines[0].end


def test_partial_line_gets_partial_coverage():
    s = parse_script("One two three four five six seven eight.")
    tr = make_transcript("one two three something else entirely")
    al = align(s, tr)
    assert al.lines[0].matched == 3 and al.lines[0].total == 8
    assert round(al.lines[0].coverage, 3) == 0.375


def test_numbers_written_differently_still_match():
    s = parse_script("It took 30 seconds and cost 1,200 dollars.")
    tr = make_transcript("it took thirty seconds and cost one thousand two hundred dollars")
    al = align(s, tr)
    assert al.lines[0].coverage == 1.0
