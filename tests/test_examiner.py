"""M17 spoken examiner: follow-up validation, one per question, sessions as groups of takes, the closing line."""

import json

import pytest
from fastapi.testclient import TestClient

from take_two import config, takes
from take_two.app import app
from take_two.examiner import FollowUp, FollowUpOutput, ask_followup, closing_line, validate_followups
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.llm.fake_llm import FakeLLM
from tests.test_report import GRADING

ANSWER = "The effect doubled when we added the second sensor, and it held for three weeks."


def fu(q, on="The effect doubled"):
    return FollowUp(question=q, builds_on=on)


def test_a_grounded_single_question_is_kept():
    kept, dropped = validate_followups(FollowUpOutput(followups=[fu("You said the effect doubled: compared with what?")]), ANSWER)
    assert kept == {"text": "You said the effect doubled: compared with what?", "builds_on": "The effect doubled"}
    assert dropped == []


def test_a_quote_not_in_the_answer_or_script_is_dropped():
    out = FollowUpOutput(followups=[fu("You said “the effect tripled”: compared with what?")])
    kept, dropped = validate_followups(out, ANSWER)
    assert kept is None and dropped == [{"reason": "quotes words that are not in your answer or script", "count": 1}]
    kept, _ = validate_followups(out, ANSWER, script_text="We saw the effect tripled in the lab.")
    assert kept is not None  # the script counts for quotes
    kept, _ = validate_followups(FollowUpOutput(followups=[fu("Why did you say “held for three weeks”?")]), ANSWER)
    assert kept is not None


def test_multi_question_and_multi_sentence_output_is_dropped():
    for q, reason in [("Compared with what? And why two sensors?", "more than one question"),
                      ("That is interesting. Compared with what?", "more than one sentence"),
                      ("Tell me more about the sensor.", "not a question"),
                      ("Could you " + "please " * 30 + "explain?", "longer than 30 words")]:
        kept, dropped = validate_followups(FollowUpOutput(followups=[fu(q)]), ANSWER)
        assert kept is None and dropped == [{"reason": reason, "count": 1}], q


def test_a_question_not_grounded_in_the_answer_is_dropped():
    kept, dropped = validate_followups(FollowUpOutput(followups=[fu("What about cost?", on="the price was high")]), ANSWER)
    assert kept is None and dropped[0]["reason"] == "not grounded in words from your answer"


def test_at_most_one_follow_up_per_question():
    out = FollowUpOutput(followups=[fu("Compared with what?"), fu("And for how long?", on="three weeks")])
    kept, dropped = validate_followups(out, ANSWER)
    assert kept["text"] == "Compared with what?"
    assert dropped == [{"reason": "more than one follow-up for a question", "count": 1}]


# ---- stored with the answer ---------------------------------------------------------------------------------------

@pytest.fixture
def tmp_takes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    yield tmp_path
    set_llm(None)


def _answer(session=None, text=ANSWER, first=2.5, pace="met", created="2026-10-09T10:00:00"):
    tid = takes.new_take("improv", upload=b"x", original_name="a.webm", settings={}, label="",
                         improv={"topic": "What did you find?", "goal_s": None, "content": False,
                                 **({"session": session} if session else {})})
    words = [{"i": i, "text": w, "start": first + i * 0.4, "end": first + i * 0.4 + 0.3} for i, w in enumerate(text.split())]
    takes.save_json(takes.take_path(tid) / "analysis.json", {
        "mode": "improv", "take_id": tid, "created_at": created, "label": "", "topic": "What did you find?",
        "session": session, "transcript": {"text": text, "words": words},
        "improv": {"pace": {"status": pace, "overall_wpm": 150}, "goal": {"spoken_s": 10}}})
    return tid


class CountingFake(FakeLLM):
    calls = 0

    def complete_structured(self, system, user, output, max_tokens=16000):
        CountingFake.calls += 1
        return super().complete_structured(system, user, output, max_tokens)


def test_no_key_means_no_follow_up_and_a_reason(tmp_takes):
    tid = _answer({"id": "s1", "index": 0, "total": 3, "followup_of": None})
    r = ask_followup(tid, NullLLM())
    assert r["followup"] is None and r["available"] is False and "no follow-ups" in r["reason"]


def test_follow_up_is_stored_once_and_never_for_a_follow_up_answer(tmp_takes):
    CountingFake.calls = 0
    tid = _answer({"id": "s1", "index": 0, "total": 3, "followup_of": None})
    r1 = ask_followup(tid, CountingFake())
    assert r1["followup"]["text"].startswith("(fake) You said “The effect doubled when”")
    assert "fake" in r1["followup"]["provider"]
    assert {"reason": "more than one follow-up for a question", "count": 1} in r1["dropped"]
    r2 = ask_followup(tid, CountingFake())
    assert r2["followup"] == r1["followup"] and r2["stored"] and CountingFake.calls == 1
    child = _answer({"id": "s1", "index": 0, "total": 3, "followup_of": tid})
    assert ask_followup(child, CountingFake())["followup"] is None and CountingFake.calls == 1


def test_session_groups_ordinary_takes_and_route_writes_closing(tmp_takes):
    a = _answer({"id": "s9", "index": 0, "total": 3, "followup_of": None}, first=1.0, pace="met", created="2026-10-09T10:00:00")
    _answer({"id": "s9", "index": 0, "total": 3, "followup_of": a}, first=6.4, pace="diverged", created="2026-10-09T10:01:00")
    _answer({"id": "s9", "index": 1, "total": 3, "followup_of": None}, first=2.0, pace="near", created="2026-10-09T10:02:00")
    _answer({"id": "other", "index": 0, "total": 3, "followup_of": None})
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    r = c.get("/api/improv/session/s9", params={"skipped": 1}).json()
    assert [x["followup_of"] for x in r["answers"]] == [None, a, None]
    assert r["closing"] == ("You answered 2 questions and 1 follow-up. 1 stayed within your pace band, 1 was close to it, "
                            "1 was outside it. The longest hesitation before an answer was 6 seconds. You skipped 1 question.")
    assert c.get("/api/improv/session/bad id!").status_code in (400, 404)
    set_llm(NullLLM())
    assert c.post(f"/api/improv/{a}/followup", json={}).json()["available"] is False


def test_session_field_is_validated_and_saved(tmp_takes, monkeypatch):
    import take_two.app as app_mod
    started: dict = {}
    monkeypatch.setattr(app_mod, "_start_job", lambda tid, st: started.setdefault("id", tid) and {"take_id": tid})
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    audio = {"audio": ("a.webm", b"xx", "audio/webm")}
    form = {"topic": "Why two sensors?", "settings": "{}",
            "session": json.dumps({"id": "abc-1", "index": 9, "total": 4, "followup_of": "nope"})}
    assert c.post("/api/jobs/improv", files=audio, data=form).status_code == 200
    meta = takes.load_json(takes.take_path(started["id"]) / "improv.json")
    assert meta["session"] == {"id": "abc-1", "index": None, "total": 4, "followup_of": None}
    bad = {**form, "session": json.dumps({"id": "../../x"})}
    assert c.post("/api/jobs/improv", files=audio, data=bad).status_code == 400


def test_closing_line_is_measured_and_never_grades():
    assert closing_line([], 2) == "No answers were recorded in this session. You skipped 2 questions."
    a = {"session": {"followup_of": None}, "improv": {"pace": {"status": "diverged"}},
         "transcript": {"words": [{"start": 1.2}]}}
    text = closing_line([a, a])
    assert text == ("You answered 2 questions. None stayed within your pace band, 2 were outside it. "
                    "The longest hesitation before an answer was 1 second.")
    for t in (text, closing_line([{"improv": {"pace": {"status": "met"}}, "transcript": {"words": []}}])):
        low = t.lower()
        assert not any(g in low for g in GRADING) and "score" not in low and "streak" not in low
