"""Drills: one line or section recorded on its own, judged against the full take's median."""

import io

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from take_two import app as app_mod
from take_two import config, pipeline, takes
from take_two.audio import SR
from take_two.compare import compare_takes
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.marks import drill_script, parse_script
from take_two.stt.base import Transcript, Word
from tests.helpers import silences_from_gaps
from tests.test_report import GRADING

SCRIPT = """## Intro [0:20]
This is the first line of the talk and it is fairly long.
Here is another ordinary line of roughly the same length.
## Results [0:10]
[KEY] The main result is that the method works well. //
And we close with a final ordinary line of text.
"""
FULL = ("this is the first line of the talk and it is fairly long "
        "here is another ordinary line of roughly the same length "
        "the main result is that the method works well "
        "and we close with a final ordinary line of text")


class Said:
    """A transcriber that 'hears' whatever text the test sets, at 0.3 s per word plus 0.1 s gaps."""
    text = FULL
    gap_after: dict[int, float] = {}

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
        t, words = 0.2, []
        for i, w in enumerate(Said.text.split()):
            words.append(Word(w, round(t, 3), round(t + 0.3, 3)))
            t += 0.4 + Said.gap_after.get(i, 0.0)
        return Transcript(words=words, text=Said.text, backend="stub", model="stub", device="cpu")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: Said())
    Said.text, Said.gap_after = FULL, {}
    set_llm(NullLLM())
    yield TestClient(app_mod.app, base_url="http://127.0.0.1")
    set_llm(None)
    takes.QUEUED.clear()


def _wav(seconds):
    buf = io.BytesIO()
    sf.write(buf, np.zeros(int(seconds * SR), dtype=np.float32), SR, format="WAV")
    return buf.getvalue()


def _parent(c, settings="{}"):
    r = c.post("/api/takes", files={"audio": ("t.wav", _wav(24.0), "audio/wav")}, data={"script": SCRIPT, "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()


def _drill(c, parent_id, kind, index, text, seconds=6.0, gap_after=None):
    Said.text, Said.gap_after = text, gap_after or {}
    return c.post(f"/api/takes/{parent_id}/drill", files={"audio": ("d.wav", _wav(seconds), "audio/wav")},
                  data={"kind": kind, "index": str(index)})


def test_drill_script_takes_one_line_or_one_section():
    sub, info = drill_script(SCRIPT, "line", 2)
    assert sub == "## Results\n[KEY] The main result is that the method works well. //\n"  # no budget for one line
    assert info["line_start"] == 2 and info["line_end"] == 3 and info["what"] == "line 3 ([KEY])"
    sub, info = drill_script(SCRIPT, "section", 0)
    s = parse_script(sub)
    assert s.sections[0].name == "Intro" and s.sections[0].budget_s == 20 and len(s.lines) == 2
    for bad in (("line", 9), ("section", 5), ("word", 0)):
        with pytest.raises(ValueError):
            drill_script(SCRIPT, *bad)


def _gap_silences(monkeypatch):
    """Silences where the stub transcript has gaps, instead of measuring the silent test audio."""
    from take_two import audio as audio_mod
    real = audio_mod.silence_regions

    def from_transcript(audio, sample_rate=16000, min_silence_s=0.15):
        tr = Said().transcribe(None)
        tr.duration_s = len(audio) / sample_rate
        return silences_from_gaps(tr, min_silence_s), "stub"
    monkeypatch.setattr(pipeline.audio_mod, "silence_regions", from_transcript)
    return real


def test_key_line_drill_is_judged_against_the_parent_median(client, monkeypatch):
    parent = _parent(client)
    median = parent["baseline"]["median_wpm"]
    assert median  # about 150 wpm by construction
    _gap_silences(monkeypatch)
    # Said with longer gaps (slower than the full take) and stopped 1.5 s after the last word.
    words = "the main result is that the method works well".split()
    d = _drill(client, parent["take_id"], "line", 2, " ".join(words), seconds=6.4,
               gap_after={i: 0.15 for i in range(len(words) - 1)})
    assert d.status_code == 200, d.text
    a = d.json()
    assert a["kind"] == "drill" and a["drill_of"] == parent["take_id"] and a["drill"]["parent_median_wpm"] == median
    assert a["baseline"]["median_wpm"] == median and a["baseline"]["median_source"] == "your full take"
    key = a["lines"][0]["key"]
    assert key["median_wpm"] == median and key["wpm_vs_median_pct"] < -10
    assert key["rate_status"] == "met" and key["pause_status"] == "met"
    sentence = a["drill_summary"][0]
    assert sentence.startswith("This try:") and "slower than your median from the full take" in sentence
    assert f"({median:.0f} wpm)" in sentence and "measured to the end of the recording" in sentence
    assert "met your mark" in sentence
    pause = next(t for t in a["drill_summary"] if t.startswith("The //"))
    assert "measured to the end of the recording" in pause
    assert not any(g in " ".join(a["drill_summary"]).lower() for g in GRADING)
    assert a["focus"] is None and a["fit_total"]["status"] == "not_measurable"


def test_drill_keeps_the_median_it_was_recorded_against(client):
    parent = _parent(client)
    first_median = parent["baseline"]["median_wpm"]
    drill = _drill(client, parent["take_id"], "line", 2, "the main result is that the method works well").json()
    # The parent is re-analyzed with a stricter baseline: its median changes or disappears...
    client.post(f"/api/takes/{parent['take_id']}/reanalyze", json={"settings": {"baseline_min_words": 20}})
    # ...but the drill still compares with the median it was recorded against.
    again = client.post(f"/api/takes/{drill['take_id']}/reanalyze", json={}).json()
    assert again["baseline"]["median_wpm"] == first_median


def test_parent_without_a_median_compares_no_rate(client):
    parent = _parent(client, settings='{"baseline_min_words": 20}')  # no line is long enough for a median
    assert parent["baseline"]["median_wpm"] is None
    a = _drill(client, parent["take_id"], "line", 2, "the main result is that the method works well").json()
    key = a["lines"][0]["key"]
    assert key["rate_status"] == "unknown" and "no median" in key["rate_note"]
    assert "rate not compared" in a["drill_summary"][0]


def test_section_drill_reports_the_section_budget(client):
    parent = _parent(client)
    a = _drill(client, parent["take_id"], "section", 0, " ".join(FULL.split()[:23]), seconds=12.0).json()
    # About 9 s spoken against a 20 s budget; each line is named, not "This try".
    assert any(t.startswith("Section Intro:") and t.endswith("under budget.") for t in a["drill_summary"])
    assert any(t.startswith("Line 1:") for t in a["drill_summary"]) and any(t.startswith("Line 2:") for t in a["drill_summary"])
    assert not any(t.startswith("This try") for t in a["drill_summary"])
    assert not any(g in " ".join(a["drill_summary"]).lower() for g in GRADING)


def test_a_drill_that_misses_its_line_says_so(client):
    parent = _parent(client)
    a = _drill(client, parent["take_id"], "line", 2, "completely unrelated words spoken here today").json()
    assert a["drill_summary"] == ["Line 3 was not found in this recording."]


def test_section_drill_of_an_untitled_section_keeps_its_name():
    text = "## First [0:10]\nOne two three four.\n##\nFive six seven eight.\n"
    sub, _ = drill_script(text, "section", 1)
    assert parse_script(sub).sections[0].name == parse_script(text).sections[1].name == "Section 2"


def test_drills_stay_out_of_comparisons_and_are_listed_under_their_parent(client):
    one_section = "## Intro [0:20]\nThis is the first line of the talk and it is fairly long.\nHere is another ordinary line of roughly the same length.\n"
    Said.text = " ".join(FULL.split()[:23])
    parent = client.post("/api/takes", files={"audio": ("t.wav", _wav(12.0), "audio/wav")}, data={"script": one_section}).json()
    # A drill of the only section has the same script as its parent: it must still not join comparisons.
    d = _drill(client, parent["take_id"], "section", 0, Said.text, seconds=12.0).json()
    key = takes.analysis_script_key(d)
    assert key == takes.analysis_script_key(parent)
    assert [x["take_id"] for x in takes.takes_with_same_script(parent["take_id"])] == [parent["take_id"]]
    assert [x["take_id"] for x in takes.same_script(key)] == [parent["take_id"]]
    # The latest median is the parent's current one, never the copy a drill carries.
    takes.update_analysis(d["take_id"], lambda a: {**a, "baseline": {**a["baseline"], "median_wpm": 999.0}})
    assert takes.latest_median_wpm() == parent["baseline"]["median_wpm"]
    row = next(t for t in client.get("/api/takes").json() if t["take_id"] == d["take_id"])
    assert row["kind"] == "drill" and row["drill_of"] == parent["take_id"]
    # A drill keeps its own script.
    assert client.post(f"/api/takes/{d['take_id']}/reanalyze", json={"script": SCRIPT}).status_code == 400


def test_only_real_script_takes_can_be_drilled(client):
    ex = client.post("/api/examples/coral").json()
    assert _drill(client, ex["take_id"], "line", 0, "good morning").status_code == 400
    parent = _parent(client)
    assert _drill(client, parent["take_id"], "line", 99, "x").status_code == 400
    assert _drill(client, parent["take_id"], "verse", 0, "x").status_code == 400


def test_compare_gives_each_take_the_moment_to_play():
    def take(start):
        return {"take_id": "t", "lines": [{"index": 0, "text": "k", "start": start, "end": start + 2,
                                           "key": {"status": "met", "wpm_vs_median_pct": -12.0}}],
                "pauses": [{"line": 0, "word_index": 3, "kind": "/", "status": "met", "measured_s": 0.8,
                            "window": [start + 1.0, start + 1.9], "before": "a", "after": "b"}],
                "sections": [], "defines": []}
    cmp = compare_takes([take(1.0), take(5.0)])
    key = next(m for m in cmp["marks"] if m["kind"] == "KEY")
    pause = next(m for m in cmp["marks"] if m["kind"] == "/")
    assert key["times"] == [[1.0, 3.0], [5.0, 7.0]] and pause["times"] == [[2.0, 2.9], [6.0, 6.9]]
    assert "at" not in key and "until" not in key


def test_compare_route_lists_each_takes_audio(client):
    parent = _parent(client)
    info = client.get(f"/api/compare?take_id={parent['take_id']}").json()["takes_info"]
    assert info[0]["audio_url"] == f"/takes/{parent['take_id']}/audio.wav"


def test_compare_lists_line_up_with_takes_when_a_mark_is_missing():
    with_pause = {"take_id": "a", "lines": [], "sections": [], "defines": [],
                  "pauses": [{"line": 0, "word_index": 1, "kind": "/", "status": "met", "measured_s": 0.8,
                              "window": [1.0, 1.8], "before": "x", "after": "y"}]}
    without = {"take_id": "b", "lines": [], "sections": [], "defines": [], "pauses": []}
    cmp = compare_takes([without, with_pause])
    m = cmp["marks"][0]
    assert m["statuses"] == [None, "met"] and m["values"] == [None, 0.8] and m["times"] == [None, [1.0, 1.8]]
    assert m["takes"] == 1 and m["latest"] == "met"


def test_word_drill_says_what_the_recognizer_heard(client):
    parent = _parent(client)
    assert "clarity" in parent and parent["clarity"]["words"] == []
    Said.text = "method"
    d = client.post(f"/api/takes/{parent['take_id']}/drill", files={"audio": ("d.wav", _wav(2.0), "audio/wav")},
                    data={"kind": "word", "index": "2", "word": "6"})
    assert d.status_code == 200, d.text
    a = d.json()
    assert a["drill"]["kind"] == "word" and a["drill"]["word"] == "method"
    assert a["drill_summary"] == ["This try: the recognizer heard “method” with confidence 1.00."]
    Said.text = "mess it"
    a = client.post(f"/api/takes/{parent['take_id']}/drill", files={"audio": ("d.wav", _wav(2.0), "audio/wav")},
                    data={"kind": "word", "index": "2", "word": "6"}).json()
    assert a["drill_summary"] == ["This try: the recognizer heard “mess it”, not “method”."]
