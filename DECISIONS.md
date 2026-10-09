# Decisions

Each entry: what was decided, what else was considered, why.

## Repository and toolchain

**Own git repo inside `vocal-coach/`.** The folder sits inside a larger personal `CODE/` checkout with one unrelated commit. Alternatives: commit into the parent repo. A nested repo keeps the project's history self-contained and lets "commit after each milestone" mean something.

**uv + Python 3.12, not 3.11 or 3.13.** `py -3.11` on this machine is a Microsoft Store stub; 3.13 lacks wheels for some audio packages. uv gives a one-command env (`uv sync`) and reproducible lock. CUDA libraries are an optional extra (`[gpu]`) so a CPU-only machine installs ~1 GB less; `run.ps1` / `run.sh` add the extra automatically when `nvidia-smi` exists.

**Vite + vanilla TypeScript, no UI framework, no runtime dependencies.** Recommended by the brief; TypeScript types mirror the analysis JSON so the report cannot silently drift from the backend. The run scripts build once into `frontend/dist`, which FastAPI serves; no separate dev server is needed to use the app.

**No `make`.** Windows has none by default. `run.ps1` is the one command on Windows, `run.sh` elsewhere.

## Speech-to-text

**faster-whisper `small.en` by default, GPU when available, CPU int8 otherwise.** `small.en` was already cached on the dev machine and is a reasonable accuracy/speed point; `base.en` is a config switch (`TAKE_TWO_STT_MODEL`). GPU loading on Windows needs both `os.add_dll_directory` and a `PATH` prepend because CTranslate2 loads cuBLAS lazily with a plain `LoadLibrary`; without the PATH fix the model loads and then the first transcription fails or hangs. This pattern came from a sibling project where it was measured (20x slower on CPU).

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

**`TAKE_TWO_LLM=fake` is a labelled development stand-in, not a fallback.** The brief forbids substituting a heuristic for suggestions when no key is set, and the app obeys: without a key the button is disabled with a one-line reason. The fake exists only so the review UI (ghost marks, reasons, accept/reject, caps) can be exercised and demoed without spending on a model; the UI names the provider "fake (development stand-in, not a real model)".

**Live pace is opt-in and warns about where the audio goes.** The Web Speech API in Chrome sends audio to Google. That contradicts "audio stays local", so the live pace checkbox is off by default, carries the warning inline, and the whole panel is hidden where the API does not exist. The measured report never depends on it.

**Coaching gets measurements and history, never audio.** The coaching prompt receives a compacted JSON of marks and outcomes (plus the same marks' outcomes in earlier takes of the same script) and must cite a number in every suggestion; code drops suggestions without one and caps at three. If every mark was met, the model is not even called.

**Takes are grouped by a whitespace-insensitive hash of the script text.** Comparison therefore works across takes of the same script even after cosmetic edits, and stops working after a real edit, which is the right behaviour: the marks moved.

**Emphasis uses Praat (parselmouth) when installed, else librosa's pyin, else loudness only.** All three are optional so a minimal install still runs; the status is labelled experimental in the UI and the thresholds (+3 dB or +10 % pitch over the line's median) are deliberately coarse.

**Conventions preset nudges Whisper with a filler-laden prompt only when the preset is on.** Whisper suppresses "um"/"uh" by default; an `initial_prompt` containing fillers makes it transcribe them more often. Doing that always would change transcripts for users who never asked for filler counts.

## Improvise

**Improvise is a deliberate exception to "no universal defaults", handled as bands, not scores.** Without a script there are no marks to compare against, so each measure gets a reference band (pace 130–170 wpm, ≤ 2 fillers per 100 words, ≥ 5 semitones of pitch range, …) that lives in Settings next to everything else and travels with the request. Statuses read "within / close to / outside your band"; there is no overall confidence or engagement score, because a single number hides which thing to practise.

**Clarity is a proxy, not pronunciation scoring.** Real pronunciation assessment needs a phoneme-level reference model (for example a cloud pronunciation API), which would send audio off the machine. Whisper already returns a per-word confidence; words below a threshold are shown as "hard to catch", labelled as a proxy for mumbling or swallowed endings. A cloud phoneme scorer can be added later behind the same banner as cloud transcription.

**Pitch comes from Praat (parselmouth), now a runtime dependency.** Uptalk, monotone and opening energy are central to Improvise rather than an experimental extra, so `praat-parselmouth` moved from the `emphasis` extra into the main dependencies. librosa's pyin and "not measurable" remain as fallbacks. Uptalk is the last 40 % of a statement-final word's voiced frames against its first 60 %, in semitones; sentences ending in "?" are excluded. Monotone is the 10th–90th percentile pitch spread over the take.

**Hesitation vs. deliberate pauses depends on where the silence falls.** A VAD silence after a word ending in `. ? !` and under 3 s is a deliberate pause between sentences, which the engagement card counts in your favour; the same silence mid-sentence, or over 3 s between sentences, is a hesitation. This uses Whisper's punctuation, which is imperfect, but the alternative (no distinction) would penalise the pauses Take Two encourages elsewhere.

**"kind of" and "sort of" are hedges in Improvise, fillers in the conventions preset.** Counting them twice would inflate both; Improvise skips them as fillers and drops noun uses ("a kind of tree").

**Whisper is always nudged to keep fillers in Improvise.** Fillers are the point of the mode, so the filler-laden `initial_prompt` is always sent, unlike script takes where it is tied to the conventions preset.

**Drills are written by code, coaching by the model.** Up to three drills are generated from the measures furthest outside their bands, each citing the number, so the mode coaches without a key. The model's delivery coaching follows the same rules as script coaching (numbers only, cite one per suggestion, cap three) with its own prompt, which is allowed to talk about fillers and energy because the user chose this mode for that.

**Content review is opt-in per take and quote-verified.** The model reads the transcript text (never audio) and judges hook, topic, suspense and ending, each with a verbatim quote; code finds the quote and attaches timestamps or drops the item, as with `[DEFINE]`. The suggested opening line is capped at 30 words in code.

**Audio examples of engaging delivery are deferred.** Showing what a hook or a suspense pause sounds like needs recorded or generated examples; the drills describe the technique in words for now.

**Improvise takes share the take folder format** with an extra `improv.json` (topic, goal, content choice) and `mode: "improv"` in the analysis. Script-only routes (re-analysis with a script, coaching, comparison) refuse them with a 400; `/api/improv` has its own re-analysis and coaching.

## Demo safety (M8)

**A take folder is created before any processing, and a failure keeps it.** The upload, the script (or Improvise topic), the requested settings and the label go into `takes/<id>/` first, with a `take.json` recording status, the current stage and any error. Processing then resumes from the first stage whose output is missing: decoding is skipped if `audio.wav` exists, speech-to-text if `transcript.json` loads. Alternatives: keep the upload only in the browser (lost on reload, and the server already had it), or re-upload on retry (slow on a long take, and the first failure might have been the upload). This way a retry costs nothing extra, and a crash mid-transcription does not re-decode.

**"Finished" means `analysis.json` exists; `take.json`'s status only describes an unfinished take.** This keeps every older take (which has no `take.json`) working, removes a window where the two files disagree, and means a failed re-analysis of a finished take can never hide it. A take is `processing` only while this server process is working on it or has it queued; anything else left in that state (a crash, Ctrl+C, a `--reload` restart mid-take) is reported as interrupted and can be retried at once. A first version gave a take started by a different process 30 minutes' grace in case a second server shared the folder; review showed that a restarted server *is* a different process, so every interrupted take sat unretryable for half an hour. Two servers on one takes folder are not supported (the dev server uses its own folder). Status is computed when reading; listing takes never writes.

**JSON is written to a temp file and renamed into place, with retries.** With progress polling, a reader could otherwise catch half-written JSON, and on Windows OneDrive or an antivirus scan briefly holds files open, which makes the rename fail. Alternatives: a lock file (does not help a reader in another process) or a database (against the "takes are plain files" decision).

**Delete is offered only for unfinished takes in this milestone.** A failed take whose recording is gone can only be deleted; one with its recording can be retried or deleted. Deleting finished takes needs a confirmation that names the take, which comes with take management.

**The model's `[DEFINE]` judgements are cached per take, raw, and re-validated on every read.** Every Settings change re-analyzes the take, which used to cost a model call each time. The cache key is a hash of the terms, the transcript text, the provider and model, and a hash of the prompt, so any of those changing asks again. Only the model's raw answer is cached; the code that checks its quotes against the transcript runs on every read, so the cache saves the call and never skips a check. A failed call is not cached. The heuristic path needs no cache. Alternative: cache the finished rows (would bake in line numbers and skip validation).

**The example take ships a transcript produced by the real local speech-to-text, not a hand-written one.** `examples/coral/transcript.json` is one faster-whisper `small.en` run on the synthetic fixture, committed as produced, including Whisper's real mistakes ("leaching" for "bleaching", an extra "Thanks."). A hand-cleaned transcript would make the demo look better than the product is. The take is labelled "Example take (synthetic voice)" wherever it appears, and examples are left out of take comparisons, coaching history and the "your median from your latest take" estimate used by Suggest marks: a synthetic voice says nothing about the speaker.

**The run scripts rebuild the frontend when any source is newer than the build.** Comparing modification times of `frontend/src/**`, `index.html` and `package.json` against `dist/index.html` costs nothing and catches the case that bit before (a pulled or edited UI served from an old build). Alternative: always rebuild (adds a few seconds to every start).

**A fresh browser opens the newest finished take on disk.** The Report tab used to say "No take yet" whenever localStorage was empty, even with takes on disk. It now falls back to the newest finished real take, then to an example; drills are never picked.

**Recordings live wherever `TAKE_TWO_TAKES_DIR` points; the default is not moved.** On this machine the project, and so `takes/`, sits inside OneDrive, which means the sync client uploads recordings. That conflicts with "audio stays on the machine", but moving the default would hide every existing take, so the README now says so and names the variable that keeps audio local.


## Teleprompter (M9)

**The highlight follows the plan, never the voice.** Each section's budget is spread across its lines by word count, and the line whose planned window contains the elapsed time is highlighted and scrolled to about a third of the way down. The label says so: "Highlight follows your plan, not your voice." Alternatives: follow the voice with in-browser speech recognition (Chrome sends audio to Google, which breaks "audio stays local", and it is unreliable on technical vocabulary), or a fully local streaming recognizer (a large new piece of work). A plan-based highlight is honest about what it knows and matches the existing planned-section line.

**Keys re-anchor the plan instead of fighting it.** Space, ↓ and → (and PageDown, which presentation clickers send) move the highlight on; ↑, ← and PageUp move it back. The plan then continues from the chosen line at its planned pace, and the label says how far that line is from the plan ("0:12 behind your plan"), in the speaker's own budget's terms. Alternative: snap back to the plan a few seconds after a key press, which would drag the highlight away from where the speaker actually is. The clock and the planned-section line stay on real time.

**Keys work while recording unless focus is in a text field, and both halves of the key press are swallowed.** A focused button acts on Space at keyup, so stopping only keydown would let Space stop the take. The record button also gives up focus when a take starts. Enter still activates a focused Stop button.

**Scrolling by hand pauses the auto-scroll for 4 seconds, then it returns to the current line.** Wheel, touch, pointer and Home/End count as manual; programmatic scrolling cannot be told apart from user scrolling by `scroll` events, so those are not used.

**No budgets, no auto-scroll.** If any section that has lines lacks a budget, the plan is undefined, so the highlight only moves with the keys, and a note says how to turn the plan on. Partial plans were considered and rejected: the lines after an unbudgeted section would have no honest planned time.

**The client mirrors the server's parser exactly.** The teleprompter needs the same lines the report will use, so `scriptinfo.parseScript` blanks comments keeping their newlines, splits lines the way Python's `splitlines()` does, strips `[KEY]`, splits on `[DEFINE: …]` and counts words as `marks.py` does. A `[DEFINE]` term is underlined at its first occurrence in its line; if the term is not in the line, it stays a small chip where the tag was written.
