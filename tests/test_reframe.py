"""M15: Take Two for any speaker. Example scripts, wording, topics."""

import pytest
from fastapi.testclient import TestClient

from take_two import config, define, questions, suggest
from take_two.app import app
from take_two.marks import parse_script
from take_two.topics import CATEGORIES, TOPICS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_examples_are_listed_and_served(client):
    listed = client.get("/api/samples").json()
    assert [x["id"] for x in listed] == ["talk", "toast", "slam", "demo"]
    assert all("written for the demo" in x["label"] for x in listed if x["id"] in ("toast", "slam"))
    assert client.get("/api/sample").json()["text"] == config.SAMPLE_SCRIPT.read_text(encoding="utf-8")
    toast = client.get("/api/sample", params={"name": "toast"}).json()
    assert "## The toast" in toast["text"]
    assert client.get("/api/sample", params={"name": "nope"}).status_code == 404


def _words(script) -> int:
    return sum(ln.word_count for ln in script.lines)


def test_toast_uses_the_marks_the_demo_needs():
    s = parse_script((config.EXAMPLES_DIR / "scripts" / "toast.md").read_text(encoding="utf-8"))
    assert sum(ln.is_key for ln in s.lines) == 1
    assert any(p.kind == "/" for ln in s.lines for p in ln.pauses)
    # The long pause sits right before the last line: at the end of the line before it.
    second_last = s.lines[-2]
    assert any(p.kind == "//" and p.word_index == second_last.word_count for p in second_last.pauses)
    assert [d.term for d in s.defines] == ["first call"]
    assert s.sections[0].budget_s is not None and s.sections[0].budget_s <= 90
    assert _words(s) < 90 * 150 / 60  # under 90 s at an ordinary pace


def test_slam_poem_breathes_at_line_breaks_and_turns_on_a_long_pause():
    s = parse_script((config.EXAMPLES_DIR / "scripts" / "slam_poem.md").read_text(encoding="utf-8"))
    shorts = [p for ln in s.lines for p in ln.pauses if p.kind == "/"]
    assert len(shorts) >= 10
    turn = next(i for i, ln in enumerate(s.lines) if ln.text.startswith("But"))
    before = s.lines[turn - 1]
    assert any(p.kind == "//" and p.word_index == before.word_count for p in before.pauses)
    emph = [ln.tokens[i].text for ln in s.lines for i in ln.emphasis]
    assert 1 <= len(emph) <= 4
    assert s.sections[0].budget_s is not None and s.sections[0].budget_s <= 90


def test_prompts_are_not_only_for_science():
    for text in (define.SYSTEM, suggest.SYSTEM, questions.SYSTEM):
        low = text.lower()
        assert "science talk" not in low and "scientist" not in low and "scientific audience" not in low
    assert "in-joke" in suggest.SYSTEM and "in-joke" in define.SYSTEM
    assert "pitch" in questions.SYSTEM


def test_toasts_category_added_without_changing_the_others():
    assert CATEGORIES[:6] == ["Everyday", "Nature", "Opinions", "Stories", "Tech & science", "Games & fun"]
    assert "Toasts & occasions" in CATEGORIES
    assert sum(t["category"] == "Toasts & occasions" for t in TOPICS) >= 5
    assert all(t["category"] in CATEGORIES for t in TOPICS)


def test_demo_speech_is_not_only_for_science():
    text = (config.ROOT / "demo_speech.md").read_text(encoding="utf-8")
    assert "toast" in text and "poem" in text and "grades" not in text
