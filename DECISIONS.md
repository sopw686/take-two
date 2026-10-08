# Decisions

Each entry: what was decided, what else was considered, why.

## Repository and toolchain

**Own git repo inside `vocal-coach/`.** The folder sits inside a larger personal `CODE/` checkout with one unrelated commit. Alternatives: commit into the parent repo. A nested repo keeps the project's history self-contained and lets "commit after each milestone" mean something.

**uv + Python 3.12, not 3.11 or 3.13.** `py -3.11` on this machine is a Microsoft Store stub; 3.13 lacks wheels for some audio packages. uv gives a one-command env (`uv sync`) and reproducible lock. CUDA libraries are an optional extra (`[gpu]`) so a CPU-only machine installs ~1 GB less; `run.ps1` / `run.sh` add the extra automatically when `nvidia-smi` exists.

**Vite + vanilla TypeScript, no UI framework, no runtime dependencies.** Recommended by the brief; TypeScript types mirror the analysis JSON so the report cannot silently drift from the backend. The run scripts build once into `frontend/dist`, which FastAPI serves; no separate dev server is needed to use the app.

**No `make`.** Windows has none by default. `run.ps1` is the one command on Windows, `run.sh` elsewhere.

## Speech-to-text

**faster-whisper `small.en` by default, GPU when available, CPU int8 otherwise.** `small.en` was already cached on the dev machine and is a reasonable accuracy/speed point; `base.en` is a config switch (`MARKED_STT_MODEL`). GPU loading on Windows needs both `os.add_dll_directory` and a `PATH` prepend because CTranslate2 loads cuBLAS lazily with a plain `LoadLibrary`; without the PATH fix the model loads and then the first transcription fails or hangs. This pattern came from a sibling project where it was measured (20x slower on CPU).

**Whisper's own VAD filter stays on for transcription** (`vad_filter=True`, 500 ms min silence). It prevents hallucinated text ("Thank you.") inside the long deliberate pauses this product encourages; timestamps are mapped back to the original timeline, so pauses are not lost. Pause *measurement* never uses Whisper gaps alone (below).

**Own PyAV decoder instead of `faster_whisper.audio.decode_audio`.** PyAV 15+ removed the `metadata_errors` kwarg that faster-whisper 1.2 still passes, so the bundled decoder crashes with current PyAV. A 15-line decoder using the same resampler keeps browser webm/opus, wav, m4a and mp3 working without system ffmpeg and without pinning an old PyAV.

**OpenAI Whisper API adapter only; Deepgram skipped.** The brief said not to block on cloud adapters. The OpenAI path is implemented but unverified (no key); the UI banner says when audio leaves the machine.

## Pause detection

**Silero VAD as bundled in faster-whisper (onnxruntime), RMS energy as fallback.** Alternatives: `webrtcvad` (needs a compiler or a third-party wheel), `silero-vad` package (pulls in torch, ~2 GB). faster-whisper already ships the Silero ONNX model, so this costs no dependency. Silences shorter than `min_silence_s` (0.15 s, adjustable) are ignored.

**A pause at a mark = the longest VAD silence whose midpoint lies between the start of the aligned word before the mark and the end of the aligned word after it.** This is robust to Whisper smearing word boundaries across the silence. The raw Whisper gap is stored next to it (`whisper_gap_s`) so every number can be cross-checked. If a neighbouring word was not aligned, the nearest aligned word on that side (within the take) is used; if none exists the mark is "not measurable" rather than scored.

## Alignment and rates

**`difflib.SequenceMatcher` on normalized tokens.** Needleman–Wunsch with a similarity matrix was considered; SequenceMatcher handles skipped lines, ad-libs and repeated words well enough for scripts of a few hundred words and needs no extra code. Normalization lowercases, strips punctuation and apostrophes, splits hyphens, and expands digits and `%` to words so "95%" and "ninety five percent" match. Known gap: years ("2019" vs "twenty nineteen") and STT misspellings do not match; such words simply reduce coverage.

**Words per minute uses the script's word count across the aligned span, divided by the span's duration**, not the number of matched words. A mis-transcribed word inside a line ("bleaching" heard as "leaching") would otherwise read as slower speech. A line counts as found when at least half its words align (adjustable); below that it is reported as "not found in this take".

**[KEY] status has two parts.** Rate: met if at least `key_slower_pct` slower than the speaker's own median, near if slower but not by that much, diverged if faster than the median. Pause after: met/short/missing against `key_pause_after_s`. Overall: met only if both met; diverged if the rate diverged or the pause is missing; near otherwise. The median excludes lines under 4 words (adjustable).

**Section tolerance has a 3-second floor.** A 10 % tolerance on a 20-second section is 2 s, which is below the timing noise of word timestamps.

## Values made concrete

**No score, no grades, no universal defaults.** Every threshold is in Settings and travels with the request; the analysis JSON stores the settings it was computed with. The "conference conventions" preset is a checkbox that is off by default and its numbers only appear when it is on.

**Playback serves the 16 kHz WAV, not the browser's webm.** MediaRecorder's webm lacks duration metadata, so seeking to a line's start time is unreliable; the WAV seeks exactly. The original upload is kept alongside.

**Takes are directories of files** (`takes/<id>/audio.orig.*, audio.wav, script.md, transcript.json, analysis.json`). Re-analysis reuses the stored transcript, so changing a threshold or a mark never re-runs speech-to-text.

**The "current section" shown while rehearsing is the *planned* section** at the elapsed time (cumulative budgets), labelled as such. Live speech recognition in the browser is a stretch item; a plan-based indicator is honest and works everywhere.

## Stretch features

**`MARKED_LLM=fake` is a labelled development stand-in, not a fallback.** The brief forbids substituting a heuristic for suggestions when no key is set, and the app obeys: without a key the button is disabled with a one-line reason. The fake exists only so the review UI (ghost marks, reasons, accept/reject, caps) can be exercised and demoed without spending on a model; the UI names the provider "fake (development stand-in, not a real model)".

**Live pace is opt-in and warns about where the audio goes.** The Web Speech API in Chrome sends audio to Google. That contradicts "audio stays local", so the live pace checkbox is off by default, carries the warning inline, and the whole panel is hidden where the API does not exist. The measured report never depends on it.

**Coaching gets measurements and history, never audio.** The coaching prompt receives a compacted JSON of marks and outcomes (plus the same marks' outcomes in earlier takes of the same script) and must cite a number in every suggestion; code drops suggestions without one and caps at three. If every mark was met, the model is not even called.

**Takes are grouped by a whitespace-insensitive hash of the script text.** Comparison therefore works across takes of the same script even after cosmetic edits, and stops working after a real edit, which is the right behaviour: the marks moved.

**Emphasis uses Praat (parselmouth) when installed, else librosa's pyin, else loudness only.** All three are optional so a minimal install still runs; the status is labelled experimental in the UI and the thresholds (+3 dB or +10 % pitch over the line's median) are deliberately coarse.

**Conventions preset nudges Whisper with a filler-laden prompt only when the preset is on.** Whisper suppresses "um"/"uh" by default; an `initial_prompt` containing fillers makes it transcribe them more often. Doing that always would change transcripts for users who never asked for filler counts.
