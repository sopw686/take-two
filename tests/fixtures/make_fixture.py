"""Build a synthetic take with known ground truth.

Each script line is synthesized with the OS text-to-speech voice (pyttsx3 /
SAPI on Windows), lines are concatenated with silences of chosen lengths, and
two [KEY] lines are time-stretched: one 1.3x faster (should diverge from its
mark) and one 0.8x slower (should meet it).

Run:  uv run python tests/fixtures/make_fixture.py
Writes fixture.wav, fixture_script.md and fixture_truth.json next to this file.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

SR = 16000
HERE = Path(__file__).resolve().parent

# (clip text, silence after clip in seconds, time-stretch rate (1.0 = none))
# A script line may be split into several clips so a silence can be inserted mid-line.
SECTIONS: list[dict] = [
    {"name": "Opening", "lines": [
        [("Good morning, and thank you for having me.", 0.5, 1.0)],
        [("Today I will talk about how we measured heat stress on coral reefs.", 0.5, 1.0)],
    ]},
    {"name": "Methods", "lines": [
        # "/" inside a single clip: no real silence, expected "missing"
        [("We used twenty years of satellite temperature records.", 0.5, 1.0)],
        [("For each reef we computed degree heating weeks, which is the accumulated heat above the summer maximum.", 0.5, 1.0)],
        [("We then trained a model on reef depth and heat stress.", 0.5, 1.0)],
    ]},
    {"name": "Results", "lines": [
        # KEY line, 1.3x faster, followed by a 1.6 s "//" pause: rate should diverge, pause met
        [("The model predicted bleaching three weeks in advance.", 1.6, 1.3)],
        [("This is two weeks earlier than the current warning system.", 0.5, 1.0)],
        # KEY line, 0.8x slower, with a "/" that gets only 0.3 s, then a 1.0 s pause after the line
        [("The errors were not random.", 0.3, 0.8), ("They clustered on deep reefs.", 1.0, 0.8)],
        [("Thank you.", 0.8, 1.0)],
    ]},
]

# Script text for each line, with marks. Must match the clips above word for word.
SCRIPT_LINES: dict[str, str] = {
    "Good morning, and thank you for having me.": "Good morning, and thank you for having me.",
    "Today I will talk about how we measured heat stress on coral reefs.":
        "Today I will talk about how we measured heat stress on coral reefs.",
    "We used twenty years of satellite temperature records.": "We used twenty years / of satellite temperature records.",
    "For each reef we computed degree heating weeks, which is the accumulated heat above the summer maximum.":
        "For each reef we computed degree heating weeks, [DEFINE: degree heating weeks] which is the accumulated heat above the summer maximum.",
    "We then trained a model on reef depth and heat stress.": "We then trained a model on reef depth and heat stress.",
    "The model predicted bleaching three weeks in advance.": "[KEY] The model predicted bleaching three weeks in advance. //",
    "This is two weeks earlier than the current warning system.": "This is two weeks earlier than the current warning system.",
    "The errors were not random. They clustered on deep reefs.": "[KEY] The errors were not random. / They clustered on deep reefs.",
    "Thank you.": "Thank you.",
}


def tts(text: str, path: Path) -> None:
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty("rate", 170)
    engine.save_to_file(text, str(path))
    engine.runAndWait()
    engine.stop()


def load16k(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != SR:
        y = librosa.resample(y, orig_sr=sr, target_sr=SR)
    # trim leading/trailing silence the TTS engine adds so inserted gaps are the only gaps
    yt, _ = librosa.effects.trim(y, top_db=35)
    return yt.astype(np.float32)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="take-two-fixture-"))
    pieces: list[np.ndarray] = []
    t = 0.0
    truth_lines: list[dict] = []
    script_out: list[str] = []
    silence_truth: list[dict] = []
    line_index = 0
    section_truth: list[dict] = []

    for sec in SECTIONS:
        sec_start = t
        for clips in sec["lines"]:
            line_start = t
            rate = clips[0][2]
            for ci, (text, gap, r) in enumerate(clips):
                wav = tmp / f"clip_{line_index}_{ci}.wav"
                tts(text, wav)
                y = load16k(wav)
                if r != 1.0:
                    y = librosa.effects.time_stretch(y, rate=r)
                pieces.append(y)
                t += len(y) / SR
                clip_end = t
                pieces.append(np.zeros(int(gap * SR), dtype=np.float32))
                silence_truth.append({"after_text": text, "start": round(clip_end, 3), "end": round(t + gap, 3),
                                      "duration": gap})
                t += gap
            line_end = t - clips[-1][1]
            full_text = " ".join(c[0] for c in clips)
            script_line = SCRIPT_LINES[full_text]
            script_out.append(script_line)
            truth_lines.append({"index": line_index, "text": full_text, "script": script_line,
                                "start": round(line_start, 3), "end": round(line_end, 3),
                                "stretch_rate": rate, "pause_after": clips[-1][1]})
            line_index += 1
        sec_end = t - SECTIONS[-1]["lines"][-1][-1][1] if sec is SECTIONS[-1] else t
        section_truth.append({"name": sec["name"], "start": round(sec_start, 3), "end": round(sec_end, 3)})

    audio = np.concatenate(pieces)
    sf.write(str(HERE / "fixture.wav"), audio, SR, subtype="PCM_16")

    # Budgets: Opening and Results get a budget close to actual (met), Methods gets 6 s less (over).
    durs = {}
    for st in section_truth:
        lines_in = [ln for ln in truth_lines if st["start"] <= ln["start"] < st["end"]]
        spoken = lines_in[-1]["end"] - lines_in[0]["start"]
        durs[st["name"]] = spoken
        st["spoken_duration"] = round(spoken, 3)
    budgets = {"Opening": round(durs["Opening"]) + 1, "Methods": max(1, round(durs["Methods"]) - 6),
               "Results": round(durs["Results"]) + 1}
    expected_section_status = {"Opening": "met", "Methods": "over", "Results": "met"}
    for st in section_truth:
        st["budget_s"] = budgets[st["name"]]
        st["expected_status"] = expected_section_status[st["name"]]

    text_lines: list[str] = []
    li = 0
    for sec in SECTIONS:
        b = budgets[sec["name"]]
        text_lines.append(f"## {sec['name']} [{b // 60}:{b % 60:02d}]")
        for _ in sec["lines"]:
            text_lines.append(script_out[li])
            li += 1
        text_lines.append("")
    (HERE / "fixture_script.md").write_text("\n".join(text_lines), encoding="utf-8")

    truth = {
        "sample_rate": SR,
        "duration_s": round(len(audio) / SR, 3),
        "lines": truth_lines,
        "silences": silence_truth,
        "sections": section_truth,
        "expected": {
            "key_lines": {
                "The model predicted bleaching three weeks in advance.": {"rate": "diverged", "pause_after": "met"},
                "The errors were not random. They clustered on deep reefs.": {"rate": "met", "pause_after": "met"},
            },
            "pauses": [
                {"line_text": "We used twenty years of satellite temperature records.", "kind": "/", "status": "missing"},
                {"line_text": "The model predicted bleaching three weeks in advance.", "kind": "//", "status": "met",
                 "measured_s": 1.6},
                {"line_text": "The errors were not random. They clustered on deep reefs.", "kind": "/",
                 "status": "short", "measured_s": 0.3},
            ],
            "defines": [{"term": "degree heating weeks", "defined": True}],
            "tolerances": {"pause_s": 0.15, "section_s": 0.6, "line_s": 0.4},
        },
    }
    (HERE / "fixture_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"fixture.wav: {len(audio) / SR:.1f} s, {len(truth_lines)} lines, sections {budgets}")


if __name__ == "__main__":
    main()
