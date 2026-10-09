"""M16 Hear it: cue plans from marks, the coach's version, pronunciations, clarity, SSML, providers."""

import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from take_two import config, delivery, pronounce, tts
from take_two.align import align
from take_two.app import app
from take_two.clarity import clarity_report, set_dismissed, load_dismissed
from take_two.config import Settings
from take_two.llm import set_llm
from take_two.llm.base import NullLLM
from take_two.llm.fake_llm import FakeLLM
from take_two.marks import parse_script, say_mark, drill_script
from take_two.suggest import apply_marks
from tests.helpers import make_transcript
from tests.test_report import GRADING

ROOT = config.ROOT


@pytest.fixture(autouse=True)
def _no_model():
    set_llm(NullLLM())
    yield
    set_llm(None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    return TestClient(app, base_url="http://127.0.0.1:8765")


def seg_texts(plan):
    return [s["text"] for s in plan["segments"]]


# ---- "As I marked it" -------------------------------------------------------------------------------------------

def test_short_and_long_pauses_use_your_thresholds():
    s = parse_script("one two / three four // five")
    p = delivery.marked_plan(s, 0, Settings(short_pause_s=0.9, long_pause_s=2.2))
    assert seg_texts(p) == ["one two", "three four", "five"]
    assert [x["pause_after_s"] for x in p["segments"]] == [0.9, 2.2, 0.0]
    assert all(x["checked"] for x in p["segments"][:2])
    assert any("0.9 s pause after “two” (your short-pause setting)" == c["text"] for c in p["cues"])
    assert all(c["label"] == "checked in your report" for c in p["cues"])


def test_key_uses_your_measured_median():
    s = parse_script("[KEY] The model predicted bleaching three weeks ahead.")
    p = delivery.marked_plan(s, 0, Settings(key_slower_pct=20, key_pause_after_s=1.0), median_wpm=150, median_source="this take")
    seg = p["segments"][-1]
    assert seg["wpm"] == 120.0 and seg["rate"] == 0.8 and seg["pause_after_s"] == 1.0
    assert "your median 150 wpm from this take" == p["reference_source"]
    assert any("20% below your median (150 wpm → 120)" in c["text"] for c in p["cues"])


def test_key_without_a_take_uses_a_labelled_baseline():
    s = parse_script("[KEY] It still works.")
    p = delivery.marked_plan(s, 0, Settings(hear_baseline_wpm=160), median_wpm=None)
    assert p["reference_wpm"] == 160
    assert "no take yet" in p["reference_source"] and "not your own rate" in p["reference_source"]
    assert any("a typical baseline (no take yet)" in c["text"] for c in p["cues"])
    assert not any("your median" in c["text"] for c in p["cues"])


def test_emphasis_is_its_own_segment_and_checked_only_when_the_check_is_on():
    s = parse_script("It was only *waiting* for someone.")
    off = delivery.marked_plan(s, 0, Settings(emphasis_enabled=False))
    assert seg_texts(off) == ["It was only", "waiting", "for someone."]
    w = off["segments"][1]
    assert w["stress"] and w["volume_db"] > 0 and w["pitch_st"] > 0 and w["source"] == "mark:emphasis"
    assert not w["checked"] and "demonstration only" in off["cues"][0]["label"]
    on = delivery.marked_plan(s, 0, Settings(emphasis_enabled=True))
    assert on["segments"][1]["checked"] and on["cues"][0]["label"] == "checked in your report"


def test_an_unmarked_line_is_spoken_plainly():
    p = delivery.marked_plan(parse_script("Thank you all for coming."), 0, Settings())
    assert len(p["segments"]) == 1 and p["segments"][0]["rate"] == 1.0 and p["segments"][0]["pause_after_s"] == 0
    assert p["segments"][0]["source"] == "plain"
    assert p["notes"] == ["No marks on this line: it is spoken plainly."] and p["cues"] == []


def test_the_toast_and_the_poem_give_the_expected_plans():
    toast = parse_script((ROOT / "examples/scripts/toast.md").read_text(encoding="utf-8"))
    last = delivery.marked_plan(toast, len(toast.lines) - 2, Settings())
    assert last["segments"][-1]["pause_after_s"] == 1.5  # the // before "To Maya and Daniel."
    poem = parse_script((ROOT / "examples/scripts/slam_poem.md").read_text(encoding="utf-8"))
    first = delivery.marked_plan(poem, 0, Settings())
    assert seg_texts(first) == ["My mother kept her voice", "in the kitchen drawer,", "next to the batteries", "and the rubber bands."]


# ---- pronunciation lexicon ----------------------------------------------------------------------------------------

def test_say_mark_parses_round_trips_and_reaches_the_plan_as_say_as():
    text = "We met Dr. Nguyen in Hanoi. [SAY: Nguyen = WIN | wɪn]\nNguyen said / hello."
    s = parse_script(text)
    assert s.lines[0].text == "We met Dr. Nguyen in Hanoi."  # stripped, not aligned
    assert [(m.word, m.respelling, m.ipa) for m in s.says] == [("Nguyen", "WIN", "wɪn")]
    assert parse_script(say_mark("Nguyen", "WIN", "wɪn")).says[0].respelling == "WIN"
    p = delivery.marked_plan(s, 1, Settings())
    nguyen = p["segments"][0]
    assert nguyen["text"] == "Nguyen" and nguyen["say_as"] == "WIN" and nguyen["ipa"] == "wɪn"
    assert any(c["source"] == "mark:SAY" and not c["checked"] for c in p["cues"])


def test_say_marks_survive_accepting_suggestions():
    text = "Coral reefs are dying [SAY: coral = KOH-ral]\n"
    out = apply_marks(text, [{"type": "pause", "word_index": 2, "raw_line_no": 0}])
    assert "[SAY: coral = KOH-ral]" in out and "reefs / are" in out


def test_flagging_names_acronyms_loanwords_and_rare_words():
    s = parse_script("We met Dr. Nguyen at NASA. Then São Paulo. The parselmouth library works.\nMaya's friend.")
    rows, note = pronounce.flag_words(s, pieces=lambda w: 3 if w == "parselmouth" else 1)
    got = {r["word"]: r["reasons"] for r in rows}
    assert got["Nguyen"] == ["a name"] and got["NASA"] == ["an acronym: letters or a word?"]
    assert "letters from another language" in got["São Paulo"]
    assert got["parselmouth"] == ["an uncommon word"] and "Maya" in got and "Then" not in got and "The" not in got
    assert note is None
    _, note = pronounce.flag_words(parse_script("a longishword here"), pieces=lambda w: None)
    assert "not flagged" in note


def test_model_pronunciations_are_validated_and_labelled():
    s = parse_script("We met Dr. Nguyen at NASA.")
    flagged, _ = pronounce.flag_words(s, pieces=lambda w: 1)
    out = pronounce.SayingsOutput(words=[
        pronounce.ProposedSaying(word="Nguyen", respelling="WIN", ipa="/wɪn/"),
        pronounce.ProposedSaying(word="NASA", respelling="NA<SA>", ipa=""),
        pronounce.ProposedSaying(word="Hanoi", respelling="ha-NOY", ipa="")])
    kept, dropped = pronounce.validate_sayings(out, flagged)
    assert kept == {"nguyen": {"respelling": "WIN", "ipa": "wɪn"}}
    assert {d["reason"] for d in dropped} == {"respelling is not plain letters and hyphens", "word not in the list"}
    res = pronounce.propose(s, NullLLM())
    assert res["provider"] is None and "nothing is proposed" in res["reason"]
    assert all(r["respelling"] is None for r in res["words"])
    fake = pronounce.propose(s, FakeLLM())
    assert all("confirm it" in r["source"] for r in fake["words"] if r["respelling"])


def test_confirming_writes_one_say_mark(client):
    text = "I'm Maya's brother.\nMaya plays chess. [SAY: Maya = MAY-uh]\n"
    r = client.post("/api/pronounce/confirm", json={"script": text, "word": "Maya", "respelling": "MY-uh"}).json()["text"]
    assert r.count("[SAY:") == 1 and r.splitlines()[0].endswith("[SAY: Maya = MY-uh]")
    assert client.post("/api/pronounce/confirm", json={"script": text, "word": "Maya", "respelling": "<b>"}).status_code == 400


# ---- the coach's version ------------------------------------------------------------------------------------------

LINE = "[KEY] The model predicted bleaching three weeks in advance. // That is earlier than today."


def test_coach_adds_cues_and_never_removes_or_shortens_a_mark():
    s = parse_script(LINE)
    st = Settings(hear_register="technical")
    marked = delivery.marked_plan(s, 0, st, 150)
    proposal = delivery.CoachOutput(pace_pct=-10, pace_reason="slower", cues=[
        delivery.CoachCue(kind="stress", text="bleaching", reason="the subject"),
        delivery.CoachCue(kind="pause", text="advance.", pause_s=0.3, reason="shorter"),
        delivery.CoachCue(kind="pause", text="advance.", pause_s=2.4, reason="longer"),
        delivery.CoachCue(kind="contour", text="today.", contour="fall", reason="finished"),
    ])
    coach = delivery.coach_plan(s, 0, st, proposal, {"kind": "model", "label": "m"}, 150)
    m_breaks = {x["text"].split()[-1]: x["pause_after_s"] for x in marked["segments"] if x["pause_after_s"]}
    c_breaks = {x["text"].split()[-1]: x["pause_after_s"] for x in coach["segments"] if x["pause_after_s"]}
    for word, t in m_breaks.items():
        assert c_breaks[word] >= t
    assert c_breaks["advance."] == 2.4
    # the [KEY] rate is the speaker's: the coach's pace does not change it
    assert all(x["rate"] <= 0.9 for x in coach["segments"])
    assert any("your [KEY] rate wins" in n for n in coach["notes"])
    assert {x["source"] for x in coach["segments"]} >= {"mark:KEY"}
    assert any(sg["kind"] == "stress" for sg in coach["suggestions"])
    assert all("coach's suggestion" in sg["label"] for sg in coach["suggestions"])


def test_model_cues_not_verbatim_are_dropped_and_values_clamped():
    s = parse_script("We sampled forty colonies over two summers.")
    out = delivery.CoachOutput(pace_pct=-80, pace_reason="much slower", cues=[
        delivery.CoachCue(kind="slow", text="forty colonies", reason="the number"),
        delivery.CoachCue(kind="stress", text="fourty", reason="typo"),
        delivery.CoachCue(kind="pause", text="summers.", pause_s=9.0, reason="silence"),
        delivery.CoachCue(kind="stress", text="sampled", reason=""),
        delivery.CoachCue(kind="stress", text="We sampled forty", reason="too many words"),
    ])
    kept, pace, _, dropped = delivery.validate_coach(s.lines[0], out, Settings())
    assert pace == delivery.PACE_RANGE[0]
    assert [(c["kind"], c["text"]) for c in kept] == [("slow", "forty colonies"), ("pause", "summers.")]
    assert kept[1]["pause_s"] == delivery.PAUSE_RANGE[1]
    reasons = {d["reason"] for d in dropped}
    assert {"words not found verbatim in the line", "no reason given", "stress on more than 2 words"} <= reasons


def test_coach_caps_cues_and_stress_per_sentence():
    s = parse_script("alpha beta gamma delta epsilon zeta eta theta.")
    out = delivery.CoachOutput(cues=[delivery.CoachCue(kind="stress", text=w, reason="r") for w in
                                     ["alpha", "beta", "gamma"]] +
                               [delivery.CoachCue(kind="slow", text=w, reason="r") for w in ["delta", "epsilon", "zeta", "eta", "theta."]])
    kept, _, _, dropped = delivery.validate_coach(s.lines[0], out, Settings())
    assert len(kept) == delivery.MAX_COACH_CUES
    assert sum(c["kind"] == "stress" for c in kept) == 2


def test_heuristic_coach_is_labelled_and_needs_a_register():
    provider, use_model = delivery.coach_provider(NullLLM(), "none")
    assert provider["kind"] == "none" and "Pick a register" in provider["reason"] and not use_model
    provider, use_model = delivery.coach_provider(NullLLM(), "slam")
    assert provider["kind"] == "heuristic" and "not a model" in provider["label"] and not use_model
    provider, use_model = delivery.coach_provider(FakeLLM(), "none")
    assert provider["kind"] == "fake" and use_model


def test_every_register_heuristic_validates_on_every_example_line():
    for path in ["examples/scripts/toast.md", "examples/scripts/slam_poem.md", "sample_script.md", "demo_speech.md"]:
        s = parse_script((ROOT / path).read_text(encoding="utf-8"))
        for reg in delivery.REGISTERS:
            st = Settings(hear_register=reg)
            for ln in s.lines:
                out = delivery.heuristic_coach(s, ln, reg)
                kept, _, _, dropped = delivery.validate_coach(ln, out, st)
                assert not any(d["reason"] in ("words not found verbatim in the line", "no reason given") for d in dropped), (path, reg, ln.text)
                plan = delivery.coach_plan(s, ln.index, st, out, {"kind": "heuristic", "label": "h"})
                assert plan["available"] and all(x["source"] for x in plan["segments"])
                assert all(sg["source"] == f"register:{reg}" for sg in plan["suggestions"])


def test_technical_heuristic_slows_numbers_and_ends_statements_falling():
    s = parse_script("We sampled forty colonies over two summers.")
    out = delivery.heuristic_coach(s, s.lines[0], "technical")
    kinds = {(c.kind, c.text) for c in out.cues}
    assert ("slow", "forty") in kinds and ("contour", "summers.") in kinds
    assert next(c for c in out.cues if c.kind == "contour").contour == "fall"


def test_accept_into_script_turns_pauses_and_stress_into_marks(client):
    text = "We sampled forty colonies over two summers.\n"
    s = parse_script(text)
    out = delivery.CoachOutput(cues=[delivery.CoachCue(kind="stress", text="forty", reason="r"),
                                     delivery.CoachCue(kind="pause", text="colonies", pause_s=0.7, reason="r"),
                                     delivery.CoachCue(kind="pause", text="summers.", pause_s=2.0, reason="r"),
                                     delivery.CoachCue(kind="contour", text="summers.", contour="fall", reason="r")])
    plan = delivery.coach_plan(s, 0, Settings(), out, {"kind": "model", "label": "m"})
    labels = [sg["label"] for sg in plan["suggestions"]]
    assert "demonstration only, not checked" in labels[-1]
    r = client.post("/api/hear/accept", json={"script": text, "line_index": 0, "suggestions": plan["suggestions"]}).json()
    assert r["text"].strip() == "We sampled *forty* colonies / over two summers. //" and r["applied"] == 3


def test_hear_route_marked_coach_and_fake(client):
    text = (ROOT / "examples/scripts/toast.md").read_text(encoding="utf-8")
    r = client.post("/api/hear", json={"script": text, "line_index": 5, "version": "marked"}).json()
    assert r["provider"]["kind"] == "marks" and "no take yet" in r["reference_source"]
    r = client.post("/api/hear", json={"script": text, "line_index": 5, "version": "coach"}).json()
    assert r["available"] is False and "register" in r["reason"]
    r = client.post("/api/hear", json={"script": text, "line_index": 5, "version": "coach",
                                       "settings": {"hear_register": "celebratory"}}).json()
    assert r["provider"]["kind"] == "heuristic" and r["available"]
    set_llm(FakeLLM())
    r = client.post("/api/hear", json={"script": text, "line_index": 0, "version": "coach"}).json()
    assert r["provider"]["kind"] == "fake" and {"reason": "words not found verbatim in the line", "count": 1} in r["dropped"]
    assert client.post("/api/hear", json={"script": text, "line_index": 99}).status_code == 400


# ---- clarity -------------------------------------------------------------------------------------------------------

def _clarity(script_text, said, probs, settings=None, dismissed=frozenset()):
    s = parse_script(script_text)
    tr = make_transcript(said)
    for i, p in probs.items():
        tr.words[i].prob = p
    st = settings or Settings()
    al = align(s, tr, st)
    return clarity_report(s, al, tr, set(range(len(s.lines))), st, dismissed)


def test_clarity_lists_exactly_the_unsure_and_misheard_words():
    r = _clarity("Corals bleach when the water stays too warm for weeks", "corals leach when the water stays too warm for weeks",
                 {0: 0.95, 4: 0.3, 9: 0.2}, Settings(clarity_context_words=0))
    words = [(w["word"], w["kind"], w["prob"]) for w in r["words"]]
    assert words == [("bleach", "heard", 1.0), ("water", "unsure", 0.3), ("weeks", "unsure", 0.2)]
    assert r["words"][0]["text"] == "The script says “bleach”; the recognizer heard “leach” (confidence 1.00)."
    assert r["words"][1]["text"] == "The recognizer was unsure of “water” (confidence 0.30)."
    assert all(w["start"] is not None for w in r["words"])


def test_clarity_threshold_and_confident_context_skip_live_in_settings():
    text = "one two three four five six seven"
    probs = {i: 0.95 for i in range(7)} | {3: 0.4}
    assert [w["word"] for w in _clarity(text, text, probs, Settings(clarity_context_words=2))["words"]] == []
    assert [w["word"] for w in _clarity(text, text, probs, Settings(clarity_context_words=0))["words"]] == ["four"]
    assert _clarity(text, text, probs, Settings(clarity_context_words=0, clarity_prob=0.3))["words"] == []
    probs[2] = 0.7  # a neighbour is not confident, so the skip does not apply
    assert [w["word"] for w in _clarity(text, text, probs, Settings(clarity_context_words=2))["words"]] == ["four"]


def test_dismissed_words_are_left_out_and_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TAKES_DIR", tmp_path)
    set_dismissed("Water", True)
    assert load_dismissed() == {"water"}
    r = _clarity("the water stays warm", "the water stays warm", {1: 0.2}, Settings(clarity_context_words=0),
                 frozenset(load_dismissed()))
    assert r["words"] == [] and r["dismissed_skipped"] == 1
    set_dismissed("water", False)
    assert load_dismissed() == set()


def test_clarity_wording_has_no_grades_or_accent_judgements():
    r = _clarity("Corals bleach when the water stays warm", "corals leach when the water stays warm",
                 {3: 0.2}, Settings(clarity_context_words=0))
    text = " ".join([w["text"] for w in r["words"]] + [r["note"]]).lower()
    for bad in GRADING + ("enunciat", "mumbl", "your accent", "pronunciation was", "incorrect"):
        assert bad not in text, bad


def test_word_drill_script_keeps_its_say_mark():
    sub, info = drill_script("## A\nHello Nguyen there. [SAY: Nguyen = WIN]\n", "word", 0, 1)
    assert sub.strip() == "Nguyen [SAY: Nguyen = WIN]" and info["kind"] == "word" and info["word"] == "Nguyen"
    with pytest.raises(ValueError):
        drill_script("Hello.\n", "word", 0, 5)


# ---- SSML and providers --------------------------------------------------------------------------------------------

def test_ssml_escapes_text_and_bounds_values():
    plan = {"lead_pause_s": 99, "segments": [
        {"text": "Fish & <chips> \"now\"", "rate": 9, "pitch_st": -40, "volume_db": 30, "stress": True,
         "contour": "rise", "pause_after_s": 12},
        {"text": "Nguyen", "say_as": "WIN", "ipa": 'w"ɪn', "rate": 1, "pitch_st": 0, "volume_db": 0, "pause_after_s": 0},
        {"text": "Coral", "say_as": "KOH-ral", "rate": 0.5, "pitch_st": 2, "volume_db": -3, "pause_after_s": 0.7}]}
    ssml = tts.compile_ssml(plan, voice="v")
    assert "Fish &amp; &lt;chips&gt;" in ssml and "<chips>" not in ssml
    assert 'rate="+50%"' in ssml and 'pitch="-6.0st"' in ssml and 'volume="+50%"' in ssml
    assert ssml.startswith("<speak") and ssml.count('<break time="5000ms"/>') == 2
    assert '<emphasis level="moderate">' in ssml and 'contour="(60%,+0st) (100%,+3st)"' in ssml
    assert '<phoneme alphabet="ipa" ph=\'w"ɪn\'>Nguyen</phoneme>' in ssml
    assert '<sub alias="koh ral">Coral</sub>' in ssml and 'rate="-50%"' in ssml and '<break time="700ms"/>' in ssml
    import xml.dom.minidom
    xml.dom.minidom.parseString(ssml)  # well-formed


def test_server_voice_disabled_with_a_reason_without_a_key(client, monkeypatch):
    monkeypatch.setattr(tts, "PROVIDER", "azure")
    monkeypatch.setattr(tts, "AZURE_KEY", "")
    st = client.get("/api/tts").json()
    assert st["available"] is False and "AZURE_SPEECH_KEY" in st["reason"]
    assert client.post("/api/tts", json={"plan": {"segments": []}}).status_code == 409
    monkeypatch.setattr(tts, "PROVIDER", "browser")
    assert "browser" in client.get("/api/tts").json()["reason"]


def test_cloud_voice_needs_consent_on_the_request(client, monkeypatch):
    monkeypatch.setattr(tts, "PROVIDER", "azure")
    monkeypatch.setattr(tts, "AZURE_KEY", "k")
    monkeypatch.setattr(tts, "AZURE_REGION", "westeurope")
    st = client.get("/api/tts").json()
    assert st["sends"].startswith("the text of the line you play (script text, no audio)")
    r = client.post("/api/tts", json={"plan": {"segments": [{"text": "hi"}]}})
    assert r.status_code == 403 and "consent" in r.json()["detail"]


def test_fake_voice_renders_tones_with_the_plan_timing(client, monkeypatch):
    monkeypatch.setattr(tts, "PROVIDER", "fake")
    plan = delivery.marked_plan(parse_script("one two / three"), 0, Settings(short_pause_s=1.0), 120)
    r = client.post("/api/tts", json={"plan": plan})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        seconds = w.getnframes() / w.getframerate()
    assert seconds == pytest.approx(2 * 0.5 + 1.0 + 0.5, abs=0.01)  # two words at 120 wpm, the pause, one word
    assert "tones" in client.get("/api/tts").json()["label"]


def test_health_reports_the_server_voice(client):
    assert "tts" in client.get("/api/health").json()
