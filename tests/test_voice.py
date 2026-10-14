"""The natural voice: phrases and spans from a cue plan, pace factors, prosody shaping, Kokoro's phonemes,
the Gemini mapping (with the network faked), the model download's checks, and one real render (-m slow)."""

import base64
import io
import json
import wave

import numpy as np
import pytest

from take_two import delivery, neural_voice as nv, shaping, tts
from take_two.config import Settings
from take_two.marks import parse_script
from take_two.shaping import Shape, Span


def seg(text, **kw):
    return {"text": text, "wpm": 150.0, "pitch_st": 0.0, "volume_db": 0.0, "contour": "none", "pause_after_s": 0.0,
            "stress": False, "slow_word": False, "say_as": None, "ipa": None, **kw}


def voiced(seconds=1.0, f0=150.0, sr=nv.SR):
    """A buzz with harmonics: periodic enough for Praat to track and resynthesize."""
    t = np.arange(int(sr * seconds)) / sr
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8))
    return (0.2 * x / np.max(np.abs(x))).astype(np.float32)


def median_st(audio, a, b, sr=nv.SR):
    import parselmouth
    p = parselmouth.Sound(audio.astype(np.float64), sr).to_pitch(time_step=0.01, pitch_floor=75, pitch_ceiling=600)
    ts, f = p.xs(), p.selected_array["frequency"]
    sel = f[(ts >= a) & (ts <= b) & (f > 0)]
    return 12 * np.log2(np.median(sel) / 150.0)


# ---- phrases, spans, pace --------------------------------------------------------------------------------------

def test_a_phrase_ends_at_every_pause_and_empty_segments_keep_theirs():
    segs = [seg("one two", pause_after_s=0.7), seg("three"), seg("four", contour="fall"), seg("  ", pause_after_s=0.5),
            seg("five")]
    ph = nv.phrases(segs)
    assert [(p.segs, p.pause_after) for p in ph] == [([0], 0.7), ([1, 2], 0.5), ([4], 0.0)]


def test_word_spans_skip_punctuation_and_refuse_a_wrong_count():
    T = type("T", (), {})
    def t(p, a, b):
        x = T(); x.phoneme, x.start, x.end = p, a, b; return x
    timings = [t("h", 0.0, 0.1), t("i", 0.1, 0.2), t(",", 0.2, 0.5), t(" ", 0.5, 0.55), t("j", 0.55, 0.7), t(".", 0.7, 0.9)]
    assert nv.word_spans(timings, 2) == [(0.0, 0.2), (0.55, 0.7)]
    assert nv.word_spans(timings, 3) is None


def test_segment_spans_run_from_first_word_to_the_next_segments_first_word():
    words = [(0.1, 0.3), (0.35, 0.6), (0.7, 1.0)]
    spans = nv.segment_spans([2, 1], words, 1.2)
    assert [(s.start, s.end, s.last_word) for s in spans] == [(0.0, 0.7, (0.35, 0.6)), (0.7, 1.2, (0.7, 1.0))]
    est = nv.segment_spans([1, 3], None, 2.0)  # no timings: spread by word count
    assert [round(s.start, 2) for s in est] == [0.0, 0.5] and est[1].end == 2.0


def test_pace_matches_the_plans_length_and_keeps_a_slow_word_slower():
    segs = [seg("a b c d", wpm=150.0), seg("slow", wpm=100.0)]
    spans = [Span(0.0, 1.2), Span(1.2, 1.5)]   # as read: 1.2 s and 0.3 s
    factors, g = nv.pace_factors(segs, [0, 1], spans)
    target = 4 * 60 / 150 + 1 * 60 / 100
    assert 1.2 * factors[0] + 0.3 * factors[1] == pytest.approx(target)
    assert factors[1] / factors[0] == pytest.approx(150 / 100)
    assert nv.pace_factors([seg("x", wpm=0)], [0], [Span(0, 1)]) == ([1.0], 1.0)  # no pace: left as read


# ---- shaping ---------------------------------------------------------------------------------------------------

def test_nothing_to_change_returns_the_reading_untouched():
    a = voiced(0.5)
    res = shaping.shape(a, nv.SR, [Span(0, 0.5)], [Shape()])
    assert res.audio is a or np.array_equal(res.audio, a)
    assert res.applied == [] and res.starts == [0]


def test_a_stretched_span_lengthens_the_audio_and_moves_what_follows():
    a = voiced(1.0)
    res = shaping.shape(a, nv.SR, [Span(0.0, 0.5), Span(0.5, 1.0)], [Shape(dur=1.5), Shape()])
    assert len(res.audio) / nv.SR == pytest.approx(1.25, abs=0.03)
    assert res.starts[1] == pytest.approx(0.75, abs=0.02) and "pace" in res.applied


def test_pitch_is_raised_on_its_span_only_and_amounts_are_bounded():
    a = voiced(1.0)
    res = shaping.shape(a, nv.SR, [Span(0.0, 0.5), Span(0.5, 1.0)], [Shape(), Shape(pitch_st=3.0)])
    assert median_st(res.audio, 0.6, 0.95) == pytest.approx(3.0, abs=0.5)
    assert median_st(res.audio, 0.05, 0.4) == pytest.approx(0.0, abs=0.5)
    wild = shaping.shape(a, nv.SR, [Span(0, 1)], [Shape(dur=9, pitch_st=-40, gain_db=60)])
    assert len(wild.audio) / nv.SR <= 1.8 + 0.05


def test_a_rise_bends_a_flat_end_up_and_a_fall_already_there_is_kept():
    a = voiced(1.0)
    rise = shaping.shape(a, nv.SR, [Span(0, 1.0, (0.4, 1.0))], [Shape(contour="rise")])
    assert median_st(rise.audio, 0.88, 0.98) - median_st(rise.audio, 0.45, 0.6) > 2.0
    hold = shaping.shape(a, nv.SR, [Span(0, 1.0, (0.4, 1.0))], [Shape(contour="hold")])
    assert hold.applied == []  # already level: nothing to do


def test_gain_changes_only_its_span():
    a = voiced(1.0)
    res = shaping.shape(a, nv.SR, [Span(0, 0.5), Span(0.5, 1.0)], [Shape(), Shape(gain_db=-6.0)])
    rms = lambda x: float(np.sqrt(np.mean(x ** 2)))  # noqa: E731
    assert rms(res.audio[int(0.6 * nv.SR):int(0.9 * nv.SR)]) / rms(a[int(0.6 * nv.SR):int(0.9 * nv.SR)]) == pytest.approx(0.5, abs=0.03)
    assert rms(res.audio[: int(0.4 * nv.SR)]) == pytest.approx(rms(a[: int(0.4 * nv.SR)]), rel=0.01)


# ---- Kokoro's phonemes (espeak only, no model) ---------------------------------------------------------------

@pytest.fixture(scope="module")
def phonemize():
    pytest.importorskip("kokoro_onnx")
    from kokoro_onnx.tokenizer import Tokenizer
    tok = Tokenizer()
    return lambda s: tok.phonemize(s, "en-us")


def test_ipa_is_cleaned_into_kokoro_phonemes():
    assert nv.normalize_ipa("/ˈkɔr.əl/") == "ˈkɔɹəl"
    assert nv.normalize_ipa("[ŋɡwiən]") == "ŋɡwiən" and nv.normalize_ipa("'gɪt") == "ˈɡɪt"


def test_an_ipa_kokoro_cannot_say_falls_back_to_the_respelling_or_the_word():
    known = lambda s: "".join(c for c in s if c.isalpha() or c in "ˈˌ")  # noqa: E731
    assert nv.segment_phonemes(seg("coral,", ipa="123"), str.lower, known) == "coral,"
    assert nv.segment_phonemes(seg("coral", ipa="//"), str.lower) == "coral"  # nothing left after cleaning
    assert nv.segment_phonemes(seg("coral", ipa="123", say_as="KOH-ral"), str.lower, known).replace("ˈ", "") == "kohral"
    assert nv.segment_phonemes(seg("coral", ipa="ˈkɔɹəl"), str.lower, known) == "ˈkɔɹəl"


def test_a_respelling_becomes_one_word_stressed_at_its_capitals(phonemize):
    ph = nv.respelling_phonemes("KOH-ral", phonemize)
    assert " " not in ph and ph.count("ˈ") == 1 and ph.index("ˈ") < 3
    ph2 = nv.respelling_phonemes("koh-RAL", phonemize)
    assert ph2.count("ˈ") == 1 and ph2.index("ˈ") > 2


def test_segment_phonemes_keep_word_count_and_stress_a_stressed_word(phonemize):
    plain = nv.segment_phonemes(seg("the answer, then"), phonemize)
    assert len(plain.split()) == 3 and plain.split()[1].endswith(",")
    assert "ˈ" in nv.segment_phonemes(seg("the", stress=True), phonemize)
    said = nv.segment_phonemes(seg("Nguyen,", ipa="wɪn"), phonemize)
    assert said == "wɪn,"


# ---- Gemini (network faked) -----------------------------------------------------------------------------------

def test_gemini_reads_the_words_and_is_directed_separately():
    segs = [seg("we"), seg("never", stress=True, pitch_st=2.0, volume_db=4.0), seg("said it", contour="rise"),
            seg("coral", say_as="KOH-ral", wpm=110.0, slow_word=True, contour="fall")]
    assert tts.gemini_text(segs, [0, 1, 2]) == "we NEVER said it"
    assert tts.gemini_text(segs, [3]) == "koh ral"
    assert tts.gemini_style(segs, [0, 1, 2], 150.0) == "ending on a rising, open note"
    style = tts.gemini_style(segs, [3], 150.0)
    assert "slowly" in style and "“coral”" in style and "falling" in style
    assert tts.gemini_text([seg("it is ok", stress=True)], [0]) == "it is ok"  # short words are not shouted


def test_gemini_request_shape_and_exact_pauses(monkeypatch):
    sent = []
    pcm = (np.r_[np.zeros(2400), voiced(0.5, sr=24000), np.zeros(4800)] * 32767).astype("<i2").tobytes()

    class R:
        status_code = 200
        def json(self):
            return {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": base64.b64encode(pcm).decode(),
                                                                    "mime_type": "audio/l16", "sample_rate": 24000}]}]}

    def post(url, json=None, headers=None, timeout=None):
        sent.append((url, json, headers))
        return R()
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(tts, "GEMINI_KEY", "g")
    plan = {"lead_pause_s": 0.3, "reference_wpm": 150.0,
            "segments": [seg("first part", pause_after_s=0.8, wpm=0), seg("second", contour="rise", wpm=0)]}
    audio, media, starts = tts.gemini_render(plan, "Sulafat")
    url, body, headers = sent[0]
    assert url.endswith("/v1beta/interactions") and headers["x-goog-api-key"] == "g"
    assert body["model"] == tts.GEMINI_MODEL and body["generation_config"] == {"speech_config": [{"voice": "Sulafat"}]}
    assert body["response_format"] == {"type": "audio", "mime_type": "audio/l16", "sample_rate": 24000}
    texts = sorted(b["input"][0]["content"][0]["text"] for _, b, _ in sent)
    assert texts == ["first part", "second"]
    rise = next(b for _, b, _ in sent if b["input"][0]["content"][0]["text"] == "second")
    assert rise["input"][0]["content"][0]["annotations"] == [{"type": "speech_metadata", "style": "ending on a rising, open note"}]
    with wave.open(io.BytesIO(audio)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert media == "audio/wav" and starts[0] == pytest.approx(0.3)
    gap = starts[1] - starts[0]  # one trimmed clip (about 0.5 s of sound), then exactly 0.8 s of silence
    assert gap == pytest.approx(0.5 + 0.8, abs=0.06)
    assert not np.any(x[int((starts[1] - 0.75) * 24000): int((starts[1] - 0.05) * 24000)])


def test_gemini_errors_are_readable(monkeypatch):
    class R:
        status_code = 429
        def json(self):
            return {"error": {"message": "Resource has been exhausted"}}
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    monkeypatch.setattr(tts, "GEMINI_KEY", "g")
    with pytest.raises(RuntimeError, match="429: Resource has been exhausted"):
        tts.gemini_render({"segments": [seg("hi")]}, "Kore")


# ---- the model download ---------------------------------------------------------------------------------------

def test_a_download_that_does_not_match_its_checksum_is_refused(tmp_path, monkeypatch):
    import httpx

    class Stream:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def raise_for_status(self):
            pass
        def iter_bytes(self, n):
            yield b"not the model"
    monkeypatch.setattr(httpx, "stream", lambda *a, **k: Stream())
    eng = nv.Kokoro(tmp_path)
    with pytest.raises(RuntimeError, match="could not be prepared"):
        eng.load()
    assert eng.state == "failed" and "checksum" in eng.error
    assert not list(tmp_path.iterdir())  # no partial file left behind


def test_a_failed_load_says_why_in_words_and_is_tried_again_after_a_while(tmp_path, monkeypatch):
    import httpx
    calls = []

    def stream(*a, **k):
        calls.append(a)
        raise httpx.ConnectError("[WinError 10061] No connection could be made")
    monkeypatch.setattr(httpx, "stream", stream)
    eng = nv.Kokoro(tmp_path)
    with pytest.raises(RuntimeError, match="could not reach GitHub"):
        eng.load()
    assert eng.state == "failed" and "WinError" not in eng.error and "ConnectError" not in eng.error
    with pytest.raises(RuntimeError, match="could not reach GitHub"):
        eng.load()  # within the cooldown: refused at once, no new download
    assert len(calls) == 1 and eng.retry_in() > 0
    eng._failed_at -= nv.RETRY_S + 1
    with pytest.raises(RuntimeError):
        eng.load()
    assert len(calls) == 2


def test_a_line_too_long_is_refused_before_the_model_loads(tmp_path):
    eng = nv.Kokoro(tmp_path)
    with pytest.raises(RuntimeError, match="too long"):
        eng.render({"segments": [seg("word " * 300)]}, "af_heart")
    assert eng.state == "not loaded"


def test_the_status_says_the_first_use_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "PROVIDERS", ["kokoro"])
    monkeypatch.setattr(nv, "ENGINE", nv.Kokoro(tmp_path))
    v = tts.status()["voices"][0]
    assert v["available"] and not v["ready"] and "downloads the voice model" in v["note"]


# ---- one real render ------------------------------------------------------------------------------------------

@pytest.mark.slow
def test_kokoro_says_a_marked_line_with_its_pauses():
    if not nv.ENGINE.files_present():
        pytest.skip("the Kokoro model is not downloaded (it downloads on the app's first start)")
    script = parse_script("We call this / bleaching. // It is not death.\n")
    plan = delivery.marked_plan(script, 0, Settings(short_pause_s=0.7, long_pause_s=1.5), 140)
    audio, starts, _ = nv.ENGINE.render(plan, "af_heart")
    assert len(starts) == len(plan["segments"]) and all(s is not None for s in starts)
    fr = int(nv.SR * 0.02)
    quiet = np.sqrt(np.mean(audio[: len(audio) // fr * fr].reshape(-1, fr) ** 2, axis=1)) < 1e-4
    runs, n = [], 0
    for q in quiet:
        n = n + 1 if q else (runs.append(n) or 0)
    assert sorted(r * 0.02 for r in runs if r * 0.02 >= 0.5)[-2:] == pytest.approx([0.7, 1.5], abs=0.05)
    assert json.dumps(starts)
