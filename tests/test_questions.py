"""Defense Q&A: likely audience questions from the script, and "answered the question" in the content review."""

import io
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from take_two import app as app_mod
from take_two import config, pipeline, takes
from take_two.audio import SR
from take_two.improv_coach import ContentItem, QAContentReview, coach_improv, validate_content
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.llm.fake_llm import FakeLLM
from take_two.marks import parse_script
from take_two.questions import MAX_QUESTIONS, ProposedQuestion, QuestionsOutput, validate_questions
from take_two.stt.base import Transcript, Word
from tests.helpers import make_transcript

SCRIPT = parse_script("We sampled forty reefs.\nWarm years bleached more reefs.\nSo shading may help.")


def _q(text="How did you choose the reefs?", tag="methods challenge", line=0):
    return ProposedQuestion(text=text, tag=tag, line_index=line)


def test_questions_are_validated_against_the_script():
    out = QuestionsOutput(questions=[
        _q(), _q("What counts as bleached?", "Clarification", 1), _q("Does it hold for deep reefs?", "limitation", 2),
        _q("A question about nothing?", "clarification", 7),           # no such line
        _q("Who funded this?", "gossip", 0),                            # unknown tag
        _q("   ", "implication", 0),                                    # empty
        _q("x" * 201, "implication", 0),                                # too long
        _q("How did you  choose the reefs?", "methods-challenge", 1),  # duplicate (spacing differs)
        _q("how did you choose the reefs", "limitation", 2),            # duplicate (case and punctuation differ)
        _q("Before the talk?", "clarification", -1),                    # negative index
        _q("After the talk?", "clarification", 3),                      # one past the last line
    ])
    kept, dropped = validate_questions(out, SCRIPT)
    assert [q["tag"] for q in kept] == ["methods challenge", "clarification", "limitation"]
    assert kept[1]["line_index"] == 1 and kept[1]["line_text"] == "Warm years bleached more reefs."
    reasons = {d["reason"]: d["count"] for d in dropped}
    assert reasons == {"line index outside the script": 3, "unknown tag": 1, "empty question": 1,
                       "longer than 200 characters": 1, "duplicate": 2}


def test_questions_are_capped_at_eight():
    out = QuestionsOutput(questions=[_q(f"Question number {i}?", "implication", i % 3) for i in range(12)])
    kept, dropped = validate_questions(out, SCRIPT)
    assert len(kept) == MAX_QUESTIONS and dropped == [{"reason": "more than 8 questions", "count": 4}]


# ---- routes -------------------------------------------------------------------------------------

class Stub:
    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        text = "We picked the reefs at random from a public list, so the choice was not ours."
        words = [Word(w, 0.2 + 0.3 * i, 0.45 + 0.3 * i) for i, w in enumerate(text.split())]
        return Transcript(words=words, text=text, backend="stub", model="stub", device="cpu")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: Stub())
    set_llm(NullLLM())
    yield TestClient(app_mod.app, base_url="http://127.0.0.1")
    set_llm(None)
    takes.QUEUED.clear()


def _wav():
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(5 * SR), dtype=np.float32), SR, format="WAV")
    return buf.getvalue()


def test_generating_questions_needs_a_key(client):
    r = client.post("/api/improv/questions", json={"script": "We sampled forty reefs."}).json()
    assert r["available"] is False and "ANTHROPIC_API_KEY" in r["reason"] and r["questions"] == []


def test_generated_questions_are_validated_in_the_route(client):
    set_llm(FakeLLM())
    r = client.post("/api/improv/questions", json={"script": "We sampled forty reefs.\nWarm years bleached more reefs."}).json()
    assert r["available"] and r["proposed"] == 7 and len(r["questions"]) == 5
    assert {d["reason"] for d in r["dropped"]} == {"line index outside the script", "unknown tag"}
    assert all(0 <= q["line_index"] < 2 for q in r["questions"])


def test_a_typed_question_works_without_a_key(client):
    q = "How did you choose the reefs?"
    r = client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")},
                    data={"topic": q, "goal_s": "60", "question": json.dumps({"text": q})})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["mode"] == "improv" and a["topic"] == q and a["question"]["text"] == q and a["question"]["tag"] is None


def test_a_generated_question_keeps_its_tag_and_line(client):
    q = {"text": "Does it hold for deep reefs?", "tag": "limitation", "line_index": 2, "line_text": "So shading may help."}
    tid = client.post("/api/jobs/improv", files={"audio": ("a.wav", _wav(), "audio/wav")},
                      data={"topic": q["text"], "question": json.dumps(q)}).json()["take_id"]
    import time
    for _ in range(200):
        job = client.get(f"/api/jobs/{tid}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["result"]["question"] == {**q}
    assert client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")},
                       data={"topic": "x", "question": "not json"}).status_code == 400


# ---- "answered the question" ----------------------------------------------------------------------

def _item(verdict, quote):
    return ContentItem(verdict=verdict, note="n", evidence_quote=quote)


TR = make_transcript("we picked the reefs at random from a public list so the choice was not ours")


def _qa(answered):
    return QAContentReview(hook=_item("present", "we picked the reefs"), on_topic=_item("present", "a public list"),
                           suspense=_item("missing", ""), ending=_item("present", "the choice was not ours"),
                           answered=answered, rewrite_opening="Here is how the reefs were chosen.")


def test_answered_the_question_needs_the_speakers_own_words():
    v = validate_content(_qa(_item("strong", "we picked the reefs at random")), TR)
    assert v["dropped"] == [] and next(i for i in v["items"] if i["key"] == "suspense")["evidence"] is None
    answered = next(i for i in v["items"] if i["key"] == "answered")
    assert answered["label"] == "Answered the question" and answered["evidence"]["start"] == TR.words[0].start
    # A judgement with no quote, even "missing", is dropped; so is one quoting words nobody said.
    for bad in (_item("missing", ""), _item("weak", "the reefs were chosen by a committee")):
        v = validate_content(_qa(bad), TR)
        assert "answered" not in [i["key"] for i in v["items"]] and "Answered the question" in v["dropped"]


def test_content_review_asks_about_the_question_only_for_a_question_take():
    class Recording:
        name, model, available = "rec", "m", True

        def __init__(self):
            self.schemas = []

        def complete_structured(self, system, user, output, max_tokens=16000):
            self.schemas.append(output.__name__)
            return None
    from tests.test_improv import _run  # hand-built Improvise analysis
    tr, rep = _run("um trees are nice. I think they are kind of great.")
    llm = Recording()
    coach_improv({"topic": "trees", "goal_s": 60, "improv": rep}, tr, llm, content=True)
    coach_improv({"topic": "Why trees?", "goal_s": 60, "improv": rep, "question": {"text": "Why trees?"}}, tr, llm, content=True)
    assert llm.schemas == ["ImprovCoachOutput", "ContentReview", "ImprovCoachOutput", "QAContentReview"]


def test_fake_model_exercises_the_question_review():
    out = FakeLLM().complete_structured("s", 'Question asked: why?\n\nTranscript:\n"""\n' + TR.text + '\n"""', QAContentReview)
    v = validate_content(out, TR)
    keys = [i["key"] for i in v["items"]]
    assert "answered" in keys and "Suspense" in v["dropped"]  # the fake invents one quote on purpose


def test_the_stored_question_is_sanitized(client):
    def stored(topic, question):
        r = client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")},
                        data={"topic": topic, "question": json.dumps(question)})
        assert r.status_code == 200, r.text
        return r.json()["question"]
    # The text is always the topic; an unknown tag and a bad line are dropped, and so is the line's text.
    assert stored("  Why reefs?  ", {"text": "something else", "tag": "gossip", "line_index": -1, "line_text": "x"}) == \
        {"text": "Why reefs?", "tag": None, "line_index": None, "line_text": ""}
    assert stored("Why reefs?", {"line_index": True, "line_text": "x"})["line_index"] is None
    assert client.post("/api/improv", files={"audio": ("a.wav", _wav(), "audio/wav")},
                       data={"topic": "Why reefs?", "question": json.dumps(["a list"])}).status_code == 400
