"""End-to-end: audio file + script text + settings -> analysis JSON on disk."""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from marked import audio as audio_mod
from marked import takes
from marked.analysis import analyze
from marked.config import Settings
from marked.marks import parse_script
from marked.stt import get_transcriber
from marked.stt.base import Transcript

log = logging.getLogger(__name__)


def run_take(src_audio: Path, script_text: str, settings: Settings, label: str = "",
             original_name: str = "") -> dict:
    take_id = takes.new_take_id()
    tdir = takes.take_path(take_id)
    tdir.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower() or src_audio.suffix.lower() or ".bin"
    orig = tdir / f"audio.orig{suffix}"
    shutil.copyfile(src_audio, orig)

    t0 = time.time()
    audio = audio_mod.load_audio(orig)
    audio_mod.save_wav(tdir / "audio.wav", audio)
    t_decode = time.time() - t0

    transcriber = get_transcriber()
    t0 = time.time()
    transcript = transcriber.transcribe(audio, initial_prompt=_initial_prompt(settings))
    t_stt = time.time() - t0
    takes.save_json(tdir / "transcript.json", transcript.to_dict())
    (tdir / "script.md").write_text(script_text, encoding="utf-8")

    timing = {"decode_s": round(t_decode, 2), "stt_s": round(t_stt, 2)}
    return reanalyze(take_id, script_text, settings, label=label, timing=timing)


def reanalyze(take_id: str, script_text: str, settings: Settings, label: str | None = None,
              timing: dict | None = None) -> dict:
    tdir = takes.take_path(take_id)
    transcript = Transcript.from_dict(takes.load_json(tdir / "transcript.json"))
    audio = audio_mod.load_audio(tdir / "audio.wav")
    duration = len(audio) / audio_mod.SR
    silences, method = audio_mod.silence_regions(audio, min_silence_s=settings.min_silence_s)
    script = parse_script(script_text)
    (tdir / "script.md").write_text(script_text, encoding="utf-8")

    prev = takes.load_take(take_id) or {}
    result = analyze(script, transcript, silences, settings, duration)
    result.update({
        "take_id": take_id,
        "created_at": prev.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        "label": label if label is not None else prev.get("label", ""),
        "stt": transcriber_info(transcript),
        "silence_method": method,
        "silences": [{"start": s.start, "end": s.end} for s in silences],
        "transcript": {"text": transcript.text, "words": [{"i": i, "text": w.text, "start": w.start, "end": w.end}
                                                          for i, w in enumerate(transcript.words)]},
        "audio_url": f"/takes/{take_id}/audio.wav",
        "script_key": takes.script_key(script_text),
        "timing": timing or prev.get("timing", {}),
    })
    from marked.define import check_defines, define_summary
    from marked.llm import get_llm
    result["defines"] = check_defines(script, transcript, get_llm())
    result["summary"].extend(define_summary(result["defines"]))
    if settings.conventions_enabled:
        from marked.conventions import conventions_report
        result["conventions"] = conventions_report(transcript, result, settings)
    if settings.emphasis_enabled:
        from marked.emphasis import emphasis_report
        result["emphasis"] = emphasis_report(script, result, audio, audio_mod.SR)
    takes.save_json(tdir / "analysis.json", result)
    return result


def transcriber_info(transcript: Transcript) -> dict:
    return {"backend": transcript.backend, "model": transcript.model, "device": transcript.device,
            "local": "cloud" not in (transcript.device or "")}


def _initial_prompt(settings: Settings) -> str | None:
    # Whisper tends to drop fillers unless the prompt contains some. Only nudge it
    # when the user has switched the conventions preset on.
    if settings.conventions_enabled:
        return "Um, uh, so, you know, like, I mean, we measured the, uh, result."
    return None
