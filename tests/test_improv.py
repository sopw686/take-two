"""Improvise mode: measures, drills, LLM validation and routes."""

import numpy as np
import pytest

from marked.config import Settings
from marked.improv import analyze_improv, find_hedges, split_sentences
from marked.improv_coach import (ContentItem, ContentReview, ImprovCoachOutput, ImprovSuggestion, coach_improv,
                                 validate_content, validate_delivery)
from marked.stt.base import Word
from tests.helpers import make_transcript, silences_from_gaps

SR = 16000


def _run(text, gaps=None, durs=None, audio=None, settings=None, goal_s=None, probs=None):
    tr = make_transcript(text, gaps=gaps, durs=durs)
    for i, p in (probs or {}).items():
        tr.words[i].prob = p
    rep = analyze_improv(tr.words, silences_from_gaps(tr), audio, SR, settings or Settings(), topic="trees",
                         goal_s=goal_s, duration_s=tr.duration_s)
    return tr, rep


def _voice(tr, f0_of, amp_of=lambda i: 0.2):
    """Harmonic tone per word; f0_of(i, frac) gives the pitch at a fraction 0..1 through word i."""
    audio = np.zeros(int(tr.duration_s * SR) + SR, dtype=np.float64)
    for i, w in enumerate(tr.words):
        a, b = int(w.start * SR), int(w.end * SR)
        frac = np.linspace(0, 1, b - a, endpoint=False)
        f0 = np.array([f0_of(i, x) for x in frac])
        phase = 2 * np.pi * np.cumsum(f0) / SR
        audio[a:b] = amp_of(i) * (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase))
    return audio.astype(np.float32)


# ---- text measures -------------------------------------------------------------------

def test_kind_of_is_a_hedge_not_a_filler_and_noun_use_is_ignored():
    text = "um trees are kind of amazing. a kind of tree grows here. you know I think they matter."
    _, rep = _run(text)
    fillers = {f["text"] for f in rep["fillers"]["items"]}
    hedges = [h["phrase"] for h in rep["hedges"]["items"]]
    assert fillers == {"um", "you know"}
    assert hedges == ["kind of", "i think"]


def test_hedges_map_to_word_indexes_and_times():
    tr = make_transcript("maybe it is fine or something")
    h = find_hedges(tr.words)
    assert [x["phrase"] for x in h] == ["maybe", "or something"]
    assert h[1]["i"] == 4 and h[1]["j"] == 5 and h[1]["end"] == tr.words[5].end


def test_restarts_and_fragments():
    _, rep = _run("I I went to the the park and th- then very very far")
    r = rep["hesitation"]["restarts"]
    kinds = [(x["kind"], x["text"]) for x in r]
    assert ("repeat", "I I") in kinds and ("repeat", "the the") in kinds and ("fragment", "th-") in kinds
    assert not any("very" in t for _, t in kinds)


def test_long_pause_mid_sentence_is_hesitation_but_between_sentences_is_purposeful():
    text = "trees give us shade. they also clean the air we breathe every day."
    # word 3 ends a sentence (1.0 s pause), word 6 is mid-sentence (1.5 s pause)
    _, rep = _run(text, gaps={3: 1.0, 6: 1.5})
    hp = rep["hesitation"]["pauses"]
    assert len(hp) == 1 and hp[0]["before"] == "clean" and hp[0]["kind"] == "mid-sentence"
    pp = rep["engagement"]["purposeful_pauses"]
    assert len(pp) == 1 and pp[0]["before"] == "shade."


def test_split_sentences_on_terminal_punctuation():
    tr = make_transcript("one two. three four? five")
    assert split_sentences(tr.words) == [(0, 2), (2, 4), (4, 5)]


# ---- goal and pace -------------------------------------------------------------------

def test_goal_status_with_five_second_floor():
    words = " ".join(["word"] * 30)  # 30 words * 0.4 s = ~12 s
    _, rep = _run(words, goal_s=15)
    assert rep["goal"]["status"] == "met" and rep["goal"]["tolerance_s"] == 5.0
    _, rep = _run(words, goal_s=60)
    assert rep["goal"]["status"] == "under" and rep["goal"]["delta_s"] < -40
    _, rep = _run(words, goal_s=None)
    assert rep["goal"]["status"] == "no_goal"


def test_pace_overall_and_windows():
    _, rep = _run(" ".join(["word"] * 120))  # 150 wpm, ~48 s
    p = rep["pace"]
    assert 145 <= p["overall_wpm"] <= 155 and p["status"] == "met"
    assert len(p["windows"]) == 3 and all(140 <= w["wpm"] <= 160 for w in p["windows"])
    assert rep["engagement"]["pace_var_status"] == "diverged"  # perfectly even pace
    _, rep = _run(" ".join(["word"] * 120), settings=Settings(improv_wpm_min=170, improv_wpm_max=200))
    assert rep["pace"]["status"] == "diverged"


# ---- clarity -------------------------------------------------------------------------

def test_clarity_flags_low_confidence_non_filler_words_only():
    _, rep = _run("um the arboretum is lovely today", probs={0: 0.1, 2: 0.2, 1: 0.95})
    c = rep["clarity"]
    assert c["available"] and [u["text"] for u in c["unclear"]] == ["arboretum"]


def test_clarity_unmeasurable_without_word_confidence():
    _, rep = _run("the arboretum is lovely today")
    assert rep["clarity"]["available"] is False and rep["clarity"]["status"] == "unmeasurable"


# ---- prosody -------------------------------------------------------------------------

STATEMENTS = "trees grow very slowly. they live for centuries here. forests store a lot of carbon."


def test_uptalk_detected_on_rising_statement_endings():
    tr = make_transcript(STATEMENTS, durs={i: 0.45 for i in range(20)})
    last = {3, 8, 14}
    rising = _voice(tr, lambda i, x: 150 * (1 + 0.35 * x) if i in last else 150 + 20 * np.sin(i))
    _, rep = _run(STATEMENTS, durs={i: 0.45 for i in range(20)}, audio=rising)
    t = rep["tone"]
    if not t["pitch_available"]:
        pytest.skip("no pitch backend")
    assert t["uptalk_measured"] == 3 and len(t["uptalk"]) == 3 and t["uptalk_status"] == "diverged"
    falling = _voice(tr, lambda i, x: 150 * (1 - 0.2 * x) if i in last else 150 + 20 * np.sin(i))
    _, rep = _run(STATEMENTS, durs={i: 0.45 for i in range(20)}, audio=falling)
    assert rep["tone"]["uptalk"] == [] and rep["tone"]["uptalk_status"] == "met"


def test_monotone_vs_varied_pitch_range():
    text = " ".join(["word"] * 40)
    tr = make_transcript(text)
    flat = _voice(tr, lambda i, x: 140.0)
    _, rep = _run(text, audio=flat)
    e = rep["engagement"]
    if e["pitch_backend"] is None:
        pytest.skip("no pitch backend")
    assert e["pitch_range_st"] < 1 and e["pitch_status"] == "diverged"
    varied = _voice(tr, lambda i, x: [110, 140, 180, 220][i % 4])
    _, rep = _run(text, audio=varied)
    assert rep["engagement"]["pitch_range_st"] > 8 and rep["engagement"]["pitch_status"] == "met"
    assert len(rep["engagement"]["contour"]) > 10


def test_trailing_off_detected_by_final_word_loudness():
    tr = make_transcript(STATEMENTS)
    last = {3, 8, 14}
    audio = _voice(tr, lambda i, x: 150.0, amp_of=lambda i: 0.03 if i in last else 0.3)
    _, rep = _run(STATEMENTS, audio=audio)
    t = rep["tone"]
    assert t["trail_measured"] == 3 and len(t["trail_off"]) == 3 and t["trail_off"][0]["drop_db"] > 15


def test_opening_energy_compares_first_ten_seconds():
    text = " ".join(["word"] * 70)  # ~28 s
    tr = make_transcript(text)
    audio = _voice(tr, lambda i, x: 150.0, amp_of=lambda i: 0.05 if tr.words[i].start < 10 else 0.3)
    _, rep = _run(text, audio=audio)
    op = rep["engagement"]["opening"]
    assert op["db_delta"] < -10 and op["status"] == "diverged"


# ---- summary and drills ------------------------------------------------------------------

def test_summary_is_plain_and_drills_cite_numbers_and_cap_at_three():
    text = "um so I think trees are uh kind of good. um I guess like, maybe they are uh nice."
    _, rep = _run(text, goal_s=60)
    s = " ".join(rep["summary"]).lower()
    for bad in ("bad", "poor", "score", "fail", "wrong"):
        assert bad not in s
    assert 1 <= len(rep["drills"]) <= 3
    assert all(any(ch.isdigit() for ch in d["text"]) for d in rep["drills"])
    assert rep["drills"][0]["status"] == "diverged"


def test_empty_take():
    rep = analyze_improv([], [], None, SR, Settings(), topic="x", goal_s=60)
    assert rep["words"] == 0 and rep["drills"] == [] and rep["summary"]


# ---- LLM validation ---------------------------------------------------------------------

class FakeLLM:
    name = "fake"
    available = True

    def __init__(self, outs):
        self.outs = outs
        self.users = []

    def complete_structured(self, system, user, output, max_tokens=16000):
        self.users.append(user)
        return self.outs.get(output.__name__)


def test_delivery_coaching_requires_numbers_and_caps_at_three():
    out = ImprovCoachOutput(suggestions=[
        ImprovSuggestion(text="You used 4.2 fillers per 100 words.", metric="4.2"),
        ImprovSuggestion(text="Sound more confident."),
        ImprovSuggestion(text="Pitch range was 3 semitones."),
        ImprovSuggestion(text="2 of 5 statements rose."),
        ImprovSuggestion(text="Another with 9."),
    ])
    v = validate_delivery(out)
    assert len(v["suggestions"]) == 3 and "confident" not in " ".join(s["text"] for s in v["suggestions"])


def _item(verdict, quote):
    return ContentItem(verdict=verdict, note="n", evidence_quote=quote)


def test_content_review_drops_unverifiable_quotes_and_caps_opening():
    tr = make_transcript("trees are older than you think. the oldest one is five thousand years old.")
    out = ContentReview(hook=_item("strong", "Trees are older than you think"),
                        on_topic=_item("present", "the oldest one"),
                        suspense=_item("present", "a line nobody said"),
                        ending=_item("missing", ""),
                        rewrite_opening=" ".join(["word"] * 40))
    v = validate_content(out, tr)
    keys = [i["key"] for i in v["items"]]
    assert keys == ["hook", "on_topic", "ending"] and v["dropped"] == ["Suspense"]
    assert v["items"][0]["evidence"]["start"] == tr.words[0].start
    assert len(v["rewrite_opening"].split()) == 30


def test_coach_improv_sends_numbers_not_audio_and_respects_content_choice():
    tr, rep = _run("um trees are nice. I think they are kind of great.")
    analysis = {"topic": "trees", "goal_s": 60, "improv": rep}
    llm = FakeLLM({"ImprovCoachOutput": ImprovCoachOutput(suggestions=[ImprovSuggestion(text="1 filler.")]),
                   "ContentReview": None})
    r = coach_improv(analysis, tr, llm, history=[{"fillers_per_100": 3.0}], content=False)
    assert len(llm.users) == 1 and "content_review" not in r
    assert "earlier_improvise_takes" in llm.users[0] and "per_100" in llm.users[0]
    r = coach_improv(analysis, tr, llm, content=True)
    assert len(llm.users) == 3 and "trees are nice" in llm.users[2] and r["content_review"]["items"] == []
    r = coach_improv(analysis, tr, type("No", (), {"available": False})(), content=True)
    assert r["coaching"]["available"] is False and r["content_review"]["available"] is False


# ---- routes -------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from marked import app as app_mod, config, pipeline
    from marked.stt.base import Transcript

    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)

    class Stub:
        def transcribe(self, audio, sample_rate=16000, initial_prompt=None):
            Stub.prompt = initial_prompt
            words = [Word("Um,", 0.2, 0.4, 0.9), Word("trees", 0.5, 0.9, 0.95), Word("are", 1.0, 1.2, 0.99),
                     Word("great.", 1.3, 1.8, 0.4)]
            return Transcript(words=words, text="Um, trees are great.", backend="stub", model="stub", device="cpu")

    monkeypatch.setattr(pipeline, "get_transcriber", lambda: Stub())
    return TestClient(app_mod.app, base_url="http://127.0.0.1"), Stub


def _wav_bytes(seconds=2.0):
    import io

    import soundfile as sf
    buf = io.BytesIO()
    t = np.arange(int(seconds * SR)) / SR
    sf.write(buf, (0.1 * np.sin(2 * np.pi * 150 * t)).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


def test_topics_route(client):
    c, _ = client
    r = c.get("/api/improv/topics").json()
    assert "Nature" in r["categories"] and len(r["topics"]) >= 40
    assert any(t["text"] == "Trees" for t in r["topics"])


def test_create_improv_take_and_script_routes_refuse_it(client):
    c, stub = client
    r = c.post("/api/improv", files={"audio": ("take.wav", _wav_bytes(), "audio/wav")},
               data={"topic": "  trees  ", "goal_s": "60", "content": "true"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["mode"] == "improv" and a["topic"] == "trees" and a["goal_s"] == 60 and a["content"] is True
    assert "um" in (stub.prompt or "").lower()
    assert a["improv"]["fillers"]["count"] == 1 and a["transcript"]["words"][3]["prob"] == 0.4
    tid = a["take_id"]
    assert c.post(f"/api/takes/{tid}/coach").status_code == 400
    assert c.post(f"/api/takes/{tid}/reanalyze", json={}).status_code == 400
    assert c.get(f"/api/compare?take_id={tid}").status_code == 400
    r2 = c.post(f"/api/improv/{tid}/reanalyze", json={"settings": {"improv_filler_per_100": 50}}).json()
    assert r2["improv"]["fillers"]["status"] == "met"
    listed = c.get("/api/takes").json()
    assert listed[0]["mode"] == "improv" and listed[0]["topic"] == "trees"


def test_create_improv_validates_topic_and_goal(client):
    c, _ = client
    files = {"audio": ("take.wav", _wav_bytes(), "audio/wav")}
    assert c.post("/api/improv", files=files, data={"topic": "   "}).status_code == 400
    assert c.post("/api/improv", files=files, data={"topic": "x" * 201}).status_code == 400
    assert c.post("/api/improv", files=files, data={"topic": "trees", "goal_s": "5"}).status_code == 400
