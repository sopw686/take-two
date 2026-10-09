"""End-to-end: audio file + script text + settings -> analysis JSON on disk.

A take is created first (folder, upload, script or topic, requested settings),
then processed in stages. If a stage fails, the folder keeps everything needed
to retry, and processing resumes from the first stage whose output is missing.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from take_two import audio as audio_mod
from take_two import config, takes
from take_two.analysis import analyze
from take_two.config import Settings
from take_two.marks import drill_script, parse_script
from take_two.stt import get_transcriber
from take_two.stt.base import Transcript

log = logging.getLogger(__name__)

Progress = Callable[[str], None]
STAGES = {"script": ("decoding", "transcribing", "aligning", "definition check"),
          "improv": ("decoding", "transcribing", "measuring")}
EXAMPLE_LABEL = "Example take (synthetic voice)"


class TakeFailed(Exception):
    def __init__(self, take_id: str, message: str):
        super().__init__(message)
        self.take_id = take_id
        self.message = message


def run_take(src_audio: Path, script_text: str, settings: Settings, label: str = "",
             original_name: str = "") -> dict:
    take_id = takes.new_take("script", upload=src_audio, original_name=original_name or src_audio.name,
                             settings=settings.model_dump(), label=label, script=script_text)
    return process_take(take_id, settings=settings)


def process_take(take_id: str, progress: Progress | None = None, settings: Settings | None = None) -> dict:
    """Decode, transcribe and analyze a created take, skipping stages whose output already exists.

    Raises takes.Busy if the take is already being processed, TakeFailed (with the
    error recorded in take.json) if a stage fails.
    """
    meta = takes.load_meta(take_id)
    mode = meta.get("mode")
    with takes.claim(take_id):
        def stage(name: str) -> None:
            takes.update_meta(take_id, stage=name)
            if progress:
                progress(name)

        takes.update_meta(take_id, status="processing", error=None,
                          owner={"boot_id": takes.BOOT_ID, "started_at": datetime.now().isoformat(timespec="seconds")})
        try:
            if mode not in ("script", "improv"):
                raise ValueError("this take has neither a saved script nor a topic")
            st = settings or (Settings.model_validate(meta["settings"]) if meta.get("settings") else Settings())
            timing = _transcribe(take_id, mode, st, meta.get("timing") or {}, stage)
            if mode == "improv":
                stage("measuring")
                result = reanalyze_improv(take_id, st, timing=timing)
            else:
                script = (takes.take_path(take_id) / "script.md").read_text(encoding="utf-8")
                result = reanalyze(take_id, script, st, timing=timing, progress=stage)
        except Exception as exc:
            log.exception("take %s failed", take_id)
            msg = str(exc) or type(exc).__name__
            takes.update_meta(take_id, status="failed", error=msg[:500])
            raise TakeFailed(take_id, msg) from exc
        takes.update_meta(take_id, status="done", stage=None, error=None)
        return result


def _transcribe(take_id: str, mode: str, settings: Settings, timing: dict, stage: Progress) -> dict:
    """audio.orig.* -> audio.wav (16 kHz) -> transcript.json, each step only if its output is missing."""
    tdir = takes.take_path(take_id)
    timing = dict(timing)
    wav = tdir / "audio.wav"
    audio = None
    if not wav.exists():
        stage("decoding")
        orig = takes.orig_audio(take_id)
        if orig is None:
            raise FileNotFoundError("the original recording is missing from the take folder")
        t0 = time.time()
        try:
            audio = audio_mod.load_audio(orig)
        except Exception as exc:  # PyAV errors name the file path; the reason is what helps
            raise ValueError(f"the recording could not be decoded ({getattr(exc, 'strerror', None) or exc})") from exc
        if not len(audio):
            raise ValueError("the recording contains no audio")
        part = tdir / ".audio.part.wav"
        audio_mod.save_wav(part, audio)
        os.replace(part, wav)
        timing["decode_s"] = round(time.time() - t0, 2)
    tr_path = tdir / "transcript.json"
    try:
        Transcript.from_dict(takes.load_json(tr_path))
        have_transcript = True
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        have_transcript = False
    if not have_transcript:
        if audio is None:
            audio = audio_mod.load_audio(wav)
        stage("transcribing")
        t0 = time.time()
        prompt = IMPROV_PROMPT if mode == "improv" else _initial_prompt(settings)
        transcript = get_transcriber().transcribe(audio, initial_prompt=prompt)
        takes.save_json(tr_path, transcript.to_dict())
        timing["stt_s"] = round(time.time() - t0, 2)
    takes.update_meta(take_id, timing=timing)
    return timing


def _meta_fields(take_id: str, label: str | None, prev: dict) -> dict:
    """Fields every analysis write carries over from take.json, so a re-analysis never drops them."""
    meta = takes.load_meta(take_id)
    if label is not None and label != meta.get("label"):
        meta = takes.update_meta(take_id, label=label)
    out = {"label": meta.get("label") if meta.get("label") is not None else prev.get("label", ""),
           "kind": meta.get("kind") or "take"}
    for k in ("drill_of", "drill", "example"):
        if meta.get(k) is not None:
            out[k] = meta[k]
    return out


def reanalyze(take_id: str, script_text: str, settings: Settings, label: str | None = None,
              timing: dict | None = None, progress: Progress | None = None) -> dict:
    with takes.take_lock(take_id):
        tdir = takes.take_path(take_id)
        transcript = Transcript.from_dict(takes.load_json(tdir / "transcript.json"))
        audio = audio_mod.load_audio(tdir / "audio.wav")
        duration = len(audio) / audio_mod.SR
        if progress:
            progress("aligning")
        silences, method = audio_mod.silence_regions(audio, min_silence_s=settings.min_silence_s)
        script = parse_script(script_text)
        (tdir / "script.md").write_text(script_text, encoding="utf-8")

        prev = takes.load_take(take_id) or {}
        meta = takes.load_meta(take_id)
        drill = meta.get("drill") if meta.get("kind") == "drill" else None
        # A drill is one line or section: its rates are judged against the median of the full take it came from.
        override = {"median_wpm": drill.get("parent_median_wpm"), "source": "your full take"} if drill else None
        result = analyze(script, transcript, silences, settings, duration, baseline_override=override)
        result.update({
            "take_id": take_id,
            "created_at": prev.get("created_at") or takes.load_meta(take_id)["created_at"],
            **_meta_fields(take_id, label, prev),
            "stt": transcriber_info(transcript),
            "silence_method": method,
            "silences": [{"start": s.start, "end": s.end} for s in silences],
            "transcript": {"text": transcript.text, "words": [{"i": i, "text": w.text, "start": w.start, "end": w.end}
                                                              for i, w in enumerate(transcript.words)]},
            "audio_url": f"/takes/{take_id}/audio.wav",
            "script_key": takes.script_key(script_text),
            "timing": timing or prev.get("timing") or takes.load_meta(take_id).get("timing") or {},
        })
        from take_two.define import check_defines, define_summary
        from take_two.llm import get_llm
        if progress and script.defines:
            progress("definition check")
        result["defines"] = check_defines(script, transcript, get_llm(), cache_dir=tdir)
        result["summary"].extend(define_summary(result["defines"]))
        if settings.conventions_enabled:
            from take_two.conventions import conventions_report
            result["conventions"] = conventions_report(transcript, result, settings)
        if settings.emphasis_enabled:
            from take_two.emphasis import emphasis_report
            result["emphasis"] = emphasis_report(script, result, audio, audio_mod.SR)
        if drill:
            result["drill_summary"] = drill_summary(result, drill)
            # The drill card lists every mark; a whole-talk check or a focus list of one line would only repeat it.
            result["fit_total"] = {"status": "not_measurable", "reason": "A drill covers one line or section."}
        from take_two.focus import focus
        earlier = [] if result["kind"] != "take" else [
            a for a in takes.same_script(result["script_key"], before=result["created_at"]) if a.get("take_id") != take_id]
        result["focus"] = None if drill else focus(result, earlier)
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


# ---- Drills ----------------------------------------------------------------------

_RATE = {"met": "met your mark", "near": "close to your mark", "diverged": "diverged from your mark"}
_PAUSE = {"met": "met your mark", "short": "shorter than your mark", "missing": "no pause found"}
_SECTION = {"met": "within your budget", "over": "over budget", "under": "under budget"}


def drill_summary(result: dict, drill: dict) -> list[str]:
    """One plain sentence per mark of the drill, judged against the full take's median."""
    out: list[str] = []
    median = result["baseline"]["median_wpm"]
    duration = result.get("duration_s") or 0.0
    end_note = " (measured to the end of the recording)"
    for r in result["lines"]:
        number = drill["line_start"] + r["index"] + 1
        k = r.get("key")
        who = "This try" if drill.get("kind") == "line" else f"Line {number}" + (" [KEY]" if k else "")
        if r["status"] == "paraphrased":
            text = (f"{who}: paraphrased, {r['duration_s']:.1f} s; its words do not match the script closely "
                    "enough to compare its rate with your median")
            if k and k.get("pause_after_s") is not None:
                text += f"; pause after {k['pause_after_s']:.1f} s: {_PAUSE.get(k['pause_status'], k['pause_status'])}"
            out.append(text + ".")
            continue
        if r["status"] != "ok":
            out.append(f"Line {number} was not found in this recording.")
            continue
        pct = k.get("wpm_vs_median_pct") if k else (
            (r["wpm"] - median) / median * 100.0 if r.get("wpm") and median else None)
        if pct is not None:
            rate = (f"{abs(pct):.0f}% {'slower' if pct < 0 else 'faster'} than your median from the full take "
                    f"({median:.0f} wpm)" + (f", {_RATE.get(k['rate_status'], k['rate_status'])}" if k else ""))
        else:
            rate = "rate not compared (the full take has no median)" if not median else "too few words to measure a rate"
        text = f"{who}: {rate}"
        if k and k.get("pause_after_s") is not None:
            to_end = bool(k.get("pause_window")) and abs(k["pause_window"][1] - duration) < 0.01
            text += f"; pause after {k['pause_after_s']:.1f} s{end_note if to_end else ''}: {_PAUSE.get(k['pause_status'], k['pause_status'])}"
        out.append(text + ".")
    for p in result["pauses"]:
        if p["status"] == "unmeasurable":
            continue
        to_end = p.get("after") is None  # nothing after it in the drill: the window runs to the end of the recording
        out.append(f"The {p['kind']} after “{p.get('before') or ''}”: {p['measured_s']:.2f} s{end_note if to_end else ''} "
                   f"against your {p['target_s']} s mark: {_PAUSE.get(p['status'], p['status'])}.")
    if drill.get("kind") == "section":
        for sec in result["sections"]:
            if sec.get("duration_s") is not None and sec.get("budget_s"):
                out.append(f"Section {sec['name']}: {sec['duration_label']} of its {sec['budget_label']} budget, "
                           f"{_SECTION.get(sec['status'], sec['status'])}.")
    return out


def create_drill(parent_id: str, upload: bytes, original_name: str, kind: str, index: int, settings: Settings) -> str:
    """A take of one line or section of the parent's script, linked to the parent and carrying its median."""
    parent = takes.load_take(parent_id)
    if parent is None:
        raise ValueError("the take to drill from has not been analyzed")
    if parent.get("mode") == "improv" or parent.get("kind", "take") != "take":
        raise ValueError("drills compare with one of your own full script takes; this take is not one")
    sub, info = drill_script((takes.take_path(parent_id) / "script.md").read_text(encoding="utf-8"), kind, index)
    info["parent_median_wpm"] = parent.get("baseline", {}).get("median_wpm")
    return takes.new_take("script", upload=upload, original_name=original_name, settings=settings.model_dump(),
                          label=f"Drill: {info['what']}", script=sub, kind="drill", drill_of=parent_id, drill=info)


# ---- Example take ----------------------------------------------------------------

def create_example(name: str, settings: Settings) -> dict:
    """A new take from examples/<name>/ with its committed transcript: no speech-to-text runs."""
    src = config.EXAMPLES_DIR / name
    take_id = takes.new_take("script", upload=src / "audio.wav", original_name="audio.wav",
                             settings=settings.model_dump(), label=EXAMPLE_LABEL,
                             script=(src / "script.md").read_text(encoding="utf-8"), kind="example", example=name)
    try:
        shutil.copyfile(src / "transcript.json", takes.take_path(take_id) / "transcript.json")
    except BaseException:
        takes.delete_take(take_id)
        raise
    return process_take(take_id, settings=settings)


# ---- Improvise -------------------------------------------------------------------
# Fillers are the point of Improvise, so Whisper is always nudged to keep them.
IMPROV_PROMPT = "Um, so, uh, I think, you know, it's like, um, kind of, I mean, uh, interesting."


def run_improv(src_audio: Path, topic: str, goal_s: float | None, content: bool, settings: Settings,
               label: str = "", original_name: str = "") -> dict:
    take_id = takes.new_take("improv", upload=src_audio, original_name=original_name or src_audio.name,
                             settings=settings.model_dump(), label=label,
                             improv={"topic": topic, "goal_s": goal_s, "content": content})
    return process_take(take_id, settings=settings)


def reanalyze_improv(take_id: str, settings: Settings, label: str | None = None, timing: dict | None = None) -> dict:
    from take_two.improv import analyze_improv

    with takes.take_lock(take_id):
        tdir = takes.take_path(take_id)
        meta = takes.load_json(tdir / "improv.json")
        transcript = Transcript.from_dict(takes.load_json(tdir / "transcript.json"))
        audio = audio_mod.load_audio(tdir / "audio.wav")
        duration = len(audio) / audio_mod.SR
        silences, method = audio_mod.silence_regions(audio, min_silence_s=settings.min_silence_s)
        rep = analyze_improv(transcript.words, silences, audio, audio_mod.SR, settings,
                             topic=meta.get("topic", ""), goal_s=meta.get("goal_s"), duration_s=duration)
        prev = takes.load_take(take_id) or {}
        result = {
            "mode": "improv",
            "take_id": take_id,
            "created_at": prev.get("created_at") or takes.load_meta(take_id)["created_at"],
            **_meta_fields(take_id, label, prev),
            "topic": meta.get("topic", ""),
            "goal_s": meta.get("goal_s"),
            "content": bool(meta.get("content")),
            "settings": settings.model_dump(),
            "duration_s": round(duration, 2),
            "summary": rep.pop("summary"),
            "improv": rep,
            "stt": transcriber_info(transcript),
            "silence_method": method,
            "transcript": {"text": transcript.text,
                           "words": [{"i": i, "text": w.text, "start": w.start, "end": w.end, "prob": round(w.prob, 3)}
                                     for i, w in enumerate(transcript.words)]},
            "audio_url": f"/takes/{take_id}/audio.wav",
            "timing": timing or prev.get("timing") or takes.load_meta(take_id).get("timing") or {},
        }
        result["history"] = takes.improv_history(take_id, before=result["created_at"])
        if "content_review" in prev:
            result["content_review"] = prev["content_review"]  # about the words, which re-analysis does not change
        if "coaching" in prev and prev.get("settings") == result["settings"]:
            result["coaching"] = prev["coaching"]  # cites bands, so only valid under the same settings
        takes.save_json(tdir / "analysis.json", result)
        return result
