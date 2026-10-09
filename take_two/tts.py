"""Server-side voices for Hear it. The default voice is the browser's own (speechSynthesis, in the
frontend): local, no key, no network. This module is the optional alternative.

- azure: Microsoft Azure Speech, through its REST endpoint, with SSML for real pauses, prosody,
  pitch contours, emphasis and IPA pronunciations. It receives the text of the line being played
  (script text, never audio), only when AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are set and
  TAKE_TWO_TTS=azure, and only for a request that carries the speaker's consent.
- fake: a development stand-in (TAKE_TWO_TTS=fake) that renders the plan as tones and silences,
  so the UI and tests run offline. It is labelled as tones, not speech.

The synthetic audio is never stored with a take or analyzed.
"""

from __future__ import annotations

import io
import math
import os
import wave
from xml.sax.saxutils import escape, quoteattr

import numpy as np

PROVIDER = os.environ.get("TAKE_TWO_TTS", "browser")  # browser | azure | fake
AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION", "")
AZURE_VOICE = os.environ.get("TAKE_TWO_AZURE_VOICE", "en-US-JennyNeural")

RATE_PCT = (-50.0, 50.0)
PITCH_ST = (-6.0, 6.0)
VOLUME_PCT = (-50.0, 50.0)
MAX_BREAK_MS = 5000
MAX_TEXT_CHARS = 2000
CONTOUR = {"rise": "(60%,+0st) (100%,+3st)", "fall": "(60%,+0st) (100%,-3st)", "hold": "(60%,+0st) (100%,+0st)"}


def status() -> dict:
    if PROVIDER == "fake":
        return {"kind": "fake", "available": True, "label": "fake (development stand-in: tones in place of speech)",
                "sends": None, "reason": None}
    if PROVIDER == "azure":
        if not (AZURE_KEY and AZURE_REGION):
            return {"kind": "azure", "available": False, "label": "Azure Speech", "sends": None,
                    "reason": "TAKE_TWO_TTS=azure needs AZURE_SPEECH_KEY and AZURE_SPEECH_REGION; the browser voice is used."}
        return {"kind": "azure", "available": True, "label": f"Azure Speech ({AZURE_VOICE})", "reason": None,
                "sends": f"the text of the line you play (script text, no audio) to Microsoft Azure Speech ({AZURE_REGION})"}
    return {"kind": None, "available": False, "label": None, "sends": None,
            "reason": "No server voice is configured; Hear it uses your browser's voice, on this computer."}


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


def synthesize(plan: dict) -> tuple[bytes, str]:
    """(audio bytes, media type) from the configured server voice. Raises RuntimeError if there is none."""
    st = status()
    if not st["available"]:
        raise RuntimeError(st["reason"])
    if st["kind"] == "fake":
        return fake_audio(plan), "audio/wav"
    import httpx
    r = httpx.post(f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
                   headers={"Ocp-Apim-Subscription-Key": AZURE_KEY, "Content-Type": "application/ssml+xml",
                            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3", "User-Agent": "take-two"},
                   content=compile_ssml(plan).encode("utf-8"), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Azure Speech answered {r.status_code}")
    return r.content, "audio/mpeg"


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
