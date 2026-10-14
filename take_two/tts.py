"""Server-side voices for Hear it and the examiner. The browser's own voice (speechSynthesis, in the frontend)
needs nothing from here; it is the fallback when no server voice is available.

- kokoro: the default. A local neural voice (Kokoro-82M, neural_voice.py) that reads each phrase naturally,
  with the plan's pauses, pace, stress and contours laid onto that reading. Nothing leaves the computer; the
  model is downloaded once (about 190 MB) from GitHub.
- gemini: optional, cloud. Google's Gemini TTS, directed per phrase in words ("speaking slowly, ending on a
  rising note"), stressed words in capitals, pauses as real silence between phrases. It receives the text
  of the line you play and those directions (script text, never audio), only with GEMINI_API_KEY (or
  GOOGLE_API_KEY) set, and only for a request that carries the speaker's consent.
- azure: optional, cloud. Microsoft Azure Speech with SSML, as before (AZURE_SPEECH_KEY + AZURE_SPEECH_REGION).
- fake: a development stand-in (TAKE_TWO_TTS=fake) that renders the plan as tones and silences, so the UI
  and tests run offline. It is labelled as tones, not speech.

TAKE_TWO_TTS lists the server voices to offer, in order (default "kokoro,gemini,azure"; "browser" offers
none). Each is offered only when it can work. The synthetic audio is never stored with a take or analyzed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import threading
import wave
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from take_two import neural_voice
from take_two.shaping import Shape, Span, shape


def _providers(raw: str) -> list[str]:
    names = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return [] if names in ([], ["browser"]) else names


PROVIDERS = _providers(os.environ.get("TAKE_TWO_TTS", "kokoro,gemini,azure"))
AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "")
AZURE_VOICE = os.environ.get("TAKE_TWO_AZURE_VOICE", "en-US-JennyNeural")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.environ.get("TAKE_TWO_GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# A few of Gemini's prebuilt voices, with Google's own one-word descriptions.
GEMINI_VOICES = {"Sulafat": "warm", "Achird": "friendly", "Charon": "informative", "Kore": "firm",
                 "Puck": "upbeat", "Algieba": "smooth"}
GEMINI_DEFAULT = {"coach": "Sulafat", "examiner": "Charon"}

RATE_PCT = (-50.0, 50.0)
PITCH_ST = (-6.0, 6.0)
VOLUME_PCT = (-50.0, 50.0)
MAX_BREAK_MS = 5000
MAX_TEXT_CHARS = 2000
CONTOUR = {"rise": "(60%,+0st) (100%,+3st)", "fall": "(60%,+0st) (100%,-3st)", "hold": "(60%,+0st) (100%,+0st)"}
SR = 24000

_cache: OrderedDict[str, tuple[bytes, str, list]] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_ITEMS = 64


# ---- what is on offer ------------------------------------------------------------------------------------------

def voices() -> list[dict]:
    """Every server voice on offer, in order, each with whether it can be used now and why not."""
    out: list[dict] = []
    for p in PROVIDERS:
        if p == "kokoro":
            eng = neural_voice.ENGINE
            if not eng.installed():
                reason = (f"kokoro-onnx is installed but could not be loaded ({eng.import_error})" if eng.import_error
                          else "the kokoro-onnx package is not installed (uv sync installs it)")
            else:
                reason = None
            note = None
            if eng.state == "failed":  # still offered: playing a line tries again (after neural_voice.RETRY_S)
                note = f"the last attempt to prepare it failed ({eng.error}); playing a line tries again"
            elif eng.state == "downloading":
                note = f"downloading the voice model, {eng.progress:.0%} of {neural_voice.DOWNLOAD_MB} MB"
            elif eng.state != "ready" and not eng.files_present():
                note = f"the first use downloads the voice model ({neural_voice.DOWNLOAD_MB} MB) from GitHub"
            for vid, (label, _) in neural_voice.VOICES.items():
                out.append({"id": f"kokoro:{vid}", "provider": "kokoro", "label": f"{label}, natural voice",
                            "local": True, "sends": None, "available": reason is None, "ready": eng.state == "ready",
                            "reason": reason and f"The natural voice is unavailable: {reason}.", "note": note})
        elif p == "gemini":
            for vid, desc in GEMINI_VOICES.items():
                out.append({"id": f"gemini:{vid}", "provider": "gemini", "label": f"Gemini {vid} ({desc}), cloud",
                            "local": False, "available": bool(GEMINI_KEY), "ready": True, "note": None,
                            "sends": "the text of the line you play and how to say it (script text, no audio) to Google Gemini",
                            "reason": None if GEMINI_KEY else "Gemini voices need GEMINI_API_KEY (or GOOGLE_API_KEY) on the server."})
        elif p == "azure":
            ok = bool(AZURE_KEY and AZURE_REGION)
            out.append({"id": "azure", "provider": "azure", "label": f"Azure Speech ({AZURE_VOICE}), cloud",
                        "local": False, "available": ok, "ready": True, "note": None,
                        "sends": f"the text of the line you play (script text, no audio) to Microsoft Azure Speech ({AZURE_REGION})",
                        "reason": None if ok else "Azure Speech needs AZURE_SPEECH_KEY and AZURE_SPEECH_REGION."})
        elif p == "fake":
            out.append({"id": "fake", "provider": "fake", "label": "fake (development stand-in: tones in place of speech)",
                        "local": True, "sends": None, "available": True, "ready": True, "reason": None, "note": None})
    return out


def status() -> dict:
    """The voices that can be used now, each role's default (the first local voice, never a cloud one), and
    one line per configured provider that cannot be used, saying why."""
    every = voices()
    vs = [v for v in every if v["available"]]
    local = [v for v in vs if v["local"]]
    default = {}
    for role in ("coach", "examiner"):
        want = f"kokoro:{neural_voice.DEFAULT_VOICE[role]}"
        pick = next((v for v in local if v["id"] == want), local[0] if local else None)
        default[role] = pick["id"] if pick else None
    unavailable = list(dict.fromkeys(v["reason"] for v in every if not v["available"] and v["reason"]))
    reason = None if vs else "No server voice is available; Hear it uses your browser's voice, on this computer."
    return {"voices": vs, "default": default, "unavailable": unavailable, "reason": reason}


def find(voice_id: str | None) -> dict | None:
    """The voice with this id; None picks the first local voice (the old "server" choice did the same)."""
    vs = voices()
    if voice_id in (None, "", "server"):
        return next((v for v in vs if v["available"] and v["local"]), next((v for v in vs if v["available"]), None))
    return next((v for v in vs if v["id"] == voice_id), None)


# ---- synthesis -------------------------------------------------------------------------------------------------

def synthesize(plan: dict, voice_id: str | None = None) -> tuple[bytes, str, list]:
    """(audio bytes, media type, each segment's start in seconds or None) from a server voice.
    Raises RuntimeError with a reason the speaker can read."""
    v = find(voice_id)
    if v is None:
        raise RuntimeError(f"No server voice called {voice_id}." if voice_id else
                           "No server voice is configured; Hear it uses your browser's voice.")
    if not v["available"]:
        raise RuntimeError(v["reason"])
    key = hashlib.sha256(json.dumps([v["id"], plan], sort_keys=True, default=str).encode("utf-8")).hexdigest()
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    provider, _, name = v["id"].partition(":")
    try:
        if provider == "fake":
            out = (fake_audio(plan), "audio/wav", _even_starts(plan, 16000))
        elif provider == "kokoro":
            audio, starts, _ = neural_voice.ENGINE.render(plan, name)
            out = (neural_voice.wav_bytes(audio), "audio/wav", starts)
        elif provider == "gemini":
            out = gemini_render(plan, name)
        elif provider == "azure":
            out = (_azure(plan), "audio/mpeg", [])
        else:
            raise RuntimeError(f"Unknown voice {v['id']}.")
    except (ValueError, TypeError, AttributeError, ArithmeticError) as exc:  # kokoro-onnx refusing the input, or a malformed plan
        raise RuntimeError(f"The voice could not read this line ({exc}).") from exc
    with _cache_lock:
        _cache[key] = out
        while len(_cache) > CACHE_ITEMS:
            _cache.popitem(last=False)
    return out


def warm_up() -> None:
    """Prepare the local voice (download once, then load, then say one word: the first inference is the
    slowest) so the first Hear it does not wait for it."""
    if "kokoro" in PROVIDERS and neural_voice.ENGINE.installed():
        neural_voice.ENGINE.load()
        neural_voice.ENGINE.render({"segments": [{"text": "Ready."}]}, neural_voice.DEFAULT_VOICE["coach"])


def _even_starts(plan: dict, sr: int) -> list:
    """Segment starts for the fake voice, which lays segments out exactly (see fake_audio)."""
    t = min(max(float(plan.get("lead_pause_s") or 0.0), 0.0), 5.0)
    out = []
    for seg in plan.get("segments", []):
        out.append(round(t, 3))
        words = max(1, len(str(seg.get("text", "")).split()))
        t += min(10.0, words * 60.0 / max(40.0, float(seg.get("wpm") or 150.0)))
        t += min(max(float(seg.get("pause_after_s") or 0.0), 0.0), 5.0)
    return out


# ---- Gemini: directed in words --------------------------------------------------------------------------------

def gemini_text(segments: list[dict], idx: list[int]) -> str:
    """The phrase as Gemini reads it, verbatim: a stressed word in capitals (Gemini's documented emphasis), a
    [SAY] word as its respelling."""
    words = []
    for i in idx:
        s = segments[i]
        text = str(s.get("text") or "").strip()
        if s.get("say_as"):
            text = respelling_to_speech(str(s["say_as"])) + neural_voice.trailing_punct(text)
        if s.get("stress"):
            text = " ".join(w.upper() if sum(c.isalpha() for c in w) > 2 else w for w in text.split())
        if text:
            words.append(text)
    return " ".join(words)


def gemini_style(segments: list[dict], idx: list[int], ref_wpm: float | None) -> str:
    """The plan for one phrase as a short delivery direction. Short on purpose: Google's guide says long
    direction makes the voice drift, and most lines need none."""
    parts: list[str] = []
    mean = neural_voice.mean_wpm(segments, idx)
    if mean and ref_wpm:
        r = mean / ref_wpm
        if r <= 0.8:
            parts.append("speaking slowly and deliberately")
        elif r <= 0.93:
            parts.append("a little slower than conversation")
        elif r >= 1.08:
            parts.append("a little brisker than conversation")
    soft = [i for i in idx if (segments[i].get("pitch_st") or 0) < -0.5 and (segments[i].get("volume_db") or 0) < -0.5]
    if soft:
        parts.append("softer and lower, sincere")
    slow = [str(segments[i].get("text") or "").strip(" ,.;:!?") for i in idx if segments[i].get("slow_word")]
    if slow:
        parts.append("drawing out " + " and ".join(f"“{w}”" for w in slow[:2]))
    end = str(segments[idx[-1]].get("contour") or "none") if idx else "none"
    parts.append({"rise": "ending on a rising, open note", "fall": "ending with a firm, falling, finished tone",
                  "hold": "holding the pitch level at the end, as if more is coming"}.get(end, ""))
    return ", ".join(p for p in parts if p)


def _gemini_call(text: str, style: str, voice: str) -> np.ndarray:
    import httpx
    part: dict = {"type": "text", "text": text}
    if style:
        part["annotations"] = [{"type": "speech_metadata", "style": style}]
    body = {"model": GEMINI_MODEL, "input": [{"type": "user_input", "content": [part]}],
            "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": SR},
            "generation_config": {"speech_config": [{"voice": voice}]}}
    try:
        r = httpx.post(GEMINI_URL, json=body, timeout=60,
                       headers={"x-goog-api-key": GEMINI_KEY, "Content-Type": "application/json"})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Gemini could not be reached ({type(exc).__name__})") from exc
    if r.status_code != 200:
        try:
            msg = (r.json().get("error") or {}).get("message", "")
        except ValueError:
            msg = ""
        raise RuntimeError(f"Gemini answered {r.status_code}" + (f": {msg[:200]}" if msg else ""))
    audio = [c for s in r.json().get("steps", []) if s.get("type") == "model_output"
             for c in s.get("content", []) if c.get("type") == "audio"]
    if not audio:
        raise RuntimeError("Gemini returned no audio")
    raw = base64.b64decode(audio[-1].get("data", ""))
    rate = int(audio[-1].get("sample_rate") or SR)
    if raw[:4] == b"RIFF":
        with wave.open(io.BytesIO(raw)) as w:
            rate, raw = w.getframerate(), w.readframes(w.getnframes())
    pcm = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768
    if rate != SR and pcm.size:
        pcm = np.interp(np.arange(0, pcm.size, rate / SR), np.arange(pcm.size), pcm).astype(np.float32)
    return pcm


def _trim(pcm: np.ndarray, sr: int = SR, floor_db: float = -45.0) -> np.ndarray:
    """Leading and trailing silence off, so a pause is exactly the plan's."""
    if not pcm.size:
        return pcm
    fr = int(sr * 0.01)
    n = pcm.size // fr
    if not n:
        return pcm
    e = np.sqrt(np.mean(pcm[: n * fr].reshape(n, fr) ** 2, axis=1))
    loud = np.flatnonzero(e > e.max() * 10 ** (floor_db / 20))
    if not loud.size:
        return pcm[:0]
    return pcm[max(0, loud[0] - 2) * fr: min(n, loud[-1] + 3) * fr]


def gemini_render(plan: dict, voice: str) -> tuple[bytes, str, list]:
    segments = list(plan.get("segments") or [])
    ref = float(plan.get("reference_wpm") or 0.0) or None
    phrases = neural_voice.phrases(segments)
    jobs = [(gemini_text(segments, ph.segs), gemini_style(segments, ph.segs, ref)) for ph in phrases]
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(jobs)))) as pool:
        clips = list(pool.map(lambda j: _trim(_gemini_call(j[0], j[1], voice)) if j[0] else np.zeros(0, np.float32), jobs))
    lead = min(max(float(plan.get("lead_pause_s") or 0.0), 0.0), 10.0)
    parts = [np.zeros(int(SR * lead), dtype=np.float32)]
    t = lead
    starts: list = [None] * len(segments)
    for ph, clip in zip(phrases, clips):
        total = clip.size / SR
        counts = [neural_voice.words_of(str(segments[i].get("text") or "")) for i in ph.segs]
        spans = neural_voice.segment_spans(counts, None, total)
        # The voice was told the pace in words; the line's length is then matched to the plan's words per
        # minute with a gentle, uniform stretch (no pitch change), so the demonstration keeps the marked pace.
        g = min(max(neural_voice.pace_factors(segments, ph.segs, spans)[1], 0.8), 1.25)
        if clip.size and abs(g - 1) > 0.06:
            res = shape(clip, SR, [Span(0.0, total)], [Shape(dur=g)])
            clip = res.audio
            spans = neural_voice.segment_spans(counts, None, clip.size / SR)
        for i, sp in zip(ph.segs, spans):
            starts[i] = round(t + sp.start, 3)
        parts.append(clip)
        t += clip.size / SR
        parts.append(np.zeros(int(SR * ph.pause_after), dtype=np.float32))
        t += ph.pause_after
    return neural_voice.wav_bytes(np.concatenate(parts)), "audio/wav", starts


# ---- Azure: SSML ---------------------------------------------------------------------------------------------

def _clamp(x: float, lo_hi: tuple[float, float]) -> float:
    return min(max(float(x), lo_hi[0]), lo_hi[1])


def _signed(x: float, unit: str) -> str:
    return f"{x:+.0f}{unit}" if unit == "%" else f"{x:+.1f}{unit}"


def compile_ssml(plan: dict, voice: str = AZURE_VOICE) -> str:
    """The cue plan as SSML. Pure: text is escaped, every number is bounded, breaks are capped."""
    out: list[str] = []
    used = 0
    lead = int(_clamp(plan.get("lead_pause_s") or 0.0, (0.0, MAX_BREAK_MS / 1000)) * 1000)
    if lead:
        out.append(f'<break time="{lead}ms"/>')
    for seg in plan.get("segments", []):
        text = str(seg.get("text", ""))[: max(0, MAX_TEXT_CHARS - used)]
        used += len(text)
        if not text.strip():
            continue
        body = escape(text)
        if seg.get("ipa"):
            body = f'<phoneme alphabet="ipa" ph={quoteattr(str(seg["ipa"]))}>{body}</phoneme>'
        elif seg.get("say_as"):
            body = f'<sub alias={quoteattr(respelling_to_speech(str(seg["say_as"])))}>{body}</sub>'
        if seg.get("stress"):
            body = f'<emphasis level="moderate">{body}</emphasis>'
        rate = _clamp((float(seg.get("rate") or 1.0) - 1.0) * 100.0, RATE_PCT)
        pitch = _clamp(seg.get("pitch_st") or 0.0, PITCH_ST)
        vol = _clamp((10 ** (float(seg.get("volume_db") or 0.0) / 20.0) - 1.0) * 100.0, VOLUME_PCT)
        attrs = f'rate="{_signed(rate, "%")}" pitch="{_signed(pitch, "st")}" volume="{_signed(vol, "%")}"'
        if seg.get("contour") in CONTOUR:
            attrs += f' contour="{CONTOUR[seg["contour"]]}"'
        out.append(f"<prosody {attrs}>{body}</prosody>")
        brk = int(_clamp(seg.get("pause_after_s") or 0.0, (0.0, MAX_BREAK_MS / 1000)) * 1000)
        if brk:
            out.append(f'<break time="{brk}ms"/>')
    return ('<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f"<voice name={quoteattr(voice)}>{''.join(out)}</voice></speak>")


def respelling_to_speech(respelling: str) -> str:
    """KOH-ral -> "koh ral": what a voice reads aloud for a respelling (capitals would be spelled out)."""
    return " ".join(respelling.replace("-", " ").lower().split())


def _azure(plan: dict) -> bytes:
    import httpx
    r = httpx.post(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
                   headers={"Ocp-Apim-Subscription-Key": AZURE_KEY, "Content-Type": "application/ssml+xml",
                            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3", "User-Agent": "take-two"},
                   content=compile_ssml(plan).encode("utf-8"), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Azure Speech answered {r.status_code}")
    return r.content


# ---- fake: tones ---------------------------------------------------------------------------------------------

def fake_audio(plan: dict, sr: int = 16000) -> bytes:
    """Tones in place of speech: one per segment, as long as its words take at its pace, pitched and as loud as
    the plan asks, with a glide for a contour, and real silences for the pauses. For offline development."""
    parts = [np.zeros(int(sr * _clamp(plan.get("lead_pause_s") or 0.0, (0.0, 5.0))))]
    for seg in plan.get("segments", []):
        words = max(1, len(str(seg.get("text", "")).split()))
        dur = min(10.0, words * 60.0 / max(40.0, float(seg.get("wpm") or 150.0)))
        t = np.arange(int(sr * dur)) / sr
        f0 = 220.0 * 2 ** (_clamp(seg.get("pitch_st") or 0.0, PITCH_ST) / 12.0)
        glide = {"rise": 3.0, "fall": -3.0}.get(seg.get("contour") or "", 0.0)
        f = f0 * 2 ** (glide * np.clip((t / max(dur, 1e-6) - 0.6) / 0.4, 0, 1) / 12.0)
        amp = 0.25 * 10 ** (_clamp(seg.get("volume_db") or 0.0, (-20.0, 6.0)) / 20.0)
        tone = amp * np.sin(2 * math.pi * np.cumsum(f) / sr)
        fade = min(len(tone) // 2, int(0.01 * sr))
        if fade:
            tone[:fade] *= np.linspace(0, 1, fade)
            tone[-fade:] *= np.linspace(1, 0, fade)
        parts += [tone, np.zeros(int(sr * _clamp(seg.get("pause_after_s") or 0.0, (0.0, 5.0))))]
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
