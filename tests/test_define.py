from marked.define import DefineJudgement, DefineJudgements, check_defines, define_summary, heuristic_check, _Flat
from marked.marks import parse_script
from tests.helpers import make_transcript


def _flat(text: str) -> _Flat:
    return _Flat(make_transcript(text))


def test_defined_after_first_use_with_which_is():
    r = heuristic_check("degree heating weeks", _flat(
        "for each reef we computed degree heating weeks which is the accumulated heat above the summer maximum"))
    assert r["status"] == "defined" and r["defined"] is True
    assert r["cue"] == "which is"
    assert "which is the accumulated heat" in r["evidence"]["quote"]
    assert r["evidence"]["start"] is not None and r["first_spoken_at"] is not None
    assert r["method"] == "heuristic"


def test_defined_before_first_use_with_called():
    r = heuristic_check("convolution", _flat(
        "we slide a small filter across the image and sum the products an operation called a convolution"))
    assert r["status"] == "defined" and r["cue"] == "called"


def test_never_spoken():
    r = heuristic_check("convolution", _flat("we trained a network on images and it worked"))
    assert r["status"] == "never_spoken" and r["first_spoken_at"] is None


def test_used_then_defined_much_later_is_undefined_with_note():
    filler = " ".join(["word"] * 30)
    r = heuristic_check("entropy", _flat(f"the entropy went up {filler} entropy which is a measure of disorder"))
    assert r["status"] == "undefined" and r["defined"] is False
    assert "later" in r["note"]
    assert r["later_evidence"]["start"] is not None


def test_plural_and_stem_forms_count_as_spoken():
    r = heuristic_check("convolution", _flat("convolutions are the core operation here"))
    assert r["status"] != "never_spoken"


def test_check_defines_uses_script_terms_and_summary():
    script = parse_script("## A [0:10]\nWe use [DEFINE: entropy] entropy here.\n[DEFINE: convolution] later.")
    tr = make_transcript("we use entropy here and then we stop")
    rows = check_defines(script, tr)
    assert [r["term"] for r in rows] == ["entropy", "convolution"]
    assert rows[0]["status"] == "undefined" and rows[0]["line"] == 0
    assert rows[1]["status"] == "never_spoken"
    s = define_summary(rows)
    assert any("not defined" in x for x in s) and any("never spoken" in x for x in s)


class FakeLLM:
    name = "fake"
    available = True

    def __init__(self, out):
        self.out = out
        self.calls = 0

    def complete_structured(self, system, user, output, max_tokens=4000):
        self.calls += 1
        return self.out


def test_llm_judgement_with_verifiable_quote_gets_timestamps():
    script = parse_script("[DEFINE: entropy] text")
    tr = make_transcript("entropy that is a measure of disorder went up")
    llm = FakeLLM(DefineJudgements(judgements=[DefineJudgement(
        term="entropy", spoken=True, defined_at_or_before_first_use=True,
        evidence_quote="a measure of disorder", explanation="Paraphrased right after first use.")]))
    rows = check_defines(script, tr, llm)
    assert rows[0]["method"] == "llm" and rows[0]["status"] == "defined"
    assert rows[0]["evidence"]["quote"] == "a measure of disorder"
    assert rows[0]["evidence"]["start"] == tr.words[3].start
    assert llm.calls == 1


def test_llm_unverifiable_quote_falls_back_to_heuristic():
    script = parse_script("[DEFINE: entropy] text")
    tr = make_transcript("entropy went up and that was it")
    llm = FakeLLM(DefineJudgements(judgements=[DefineJudgement(
        term="entropy", spoken=True, defined_at_or_before_first_use=True,
        evidence_quote="words that are not in the transcript")]))
    rows = check_defines(script, tr, llm)
    assert rows[0]["method"] == "heuristic" and rows[0]["status"] == "undefined"
    assert "could not be found" in rows[0]["note"]


def test_llm_failure_never_breaks_the_report():
    script = parse_script("[DEFINE: entropy] text")
    tr = make_transcript("entropy which is disorder")
    llm = FakeLLM(None)
    rows = check_defines(script, tr, llm)
    assert rows[0]["method"] == "heuristic" and rows[0]["status"] == "defined"


def test_llm_quote_far_after_first_use_falls_back_to_heuristic():
    script = parse_script("[DEFINE: entropy] text")
    filler = " ".join(["word"] * 40)
    tr = make_transcript(f"entropy went up {filler} a measure of disorder")
    llm = FakeLLM(DefineJudgements(judgements=[DefineJudgement(
        term="entropy", spoken=True, defined_at_or_before_first_use=True, evidence_quote="a measure of disorder")]))
    rows = check_defines(script, tr, llm)
    assert rows[0]["method"] == "heuristic" and rows[0]["status"] == "undefined"


def test_llm_spoken_flag_does_not_override_measured_occurrence():
    script = parse_script("[DEFINE: entropy] text")
    tr = make_transcript("entropy went up and that was it")
    llm = FakeLLM(DefineJudgements(judgements=[DefineJudgement(
        term="entropy", spoken=False, defined_at_or_before_first_use=False)]))
    rows = check_defines(script, tr, llm)
    assert rows[0]["status"] == "undefined" and rows[0]["first_spoken_at"] is not None
