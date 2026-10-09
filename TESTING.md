# Testing

## Run

```bash
uv run pytest            # fast: parser, alignment, thresholds, define heuristic, suggestions, stretch features (~1 s)
uv run pytest -m slow    # the synthetic fixture through real local speech-to-text (~5 s on GPU, ~30 s on CPU)
```

## Verified automatically

**Mark parser** (`tests/test_marks.py`): section headers with and without budgets, implicit section, `[KEY]`, `/` and `//` positions, `[DEFINE]` extraction, `*emphasis*`, `km/h` not treated as a pause, number and punctuation normalization, comment stripping that keeps line numbers stable.

**Alignment** (`tests/test_align.py`): exact match gives full coverage and correct times; a skipped line gets zero coverage and no times; ad-libs ("um so basically…") are ignored; repeated words and restarts; partial lines get partial coverage; "30" matches "thirty", "1,200" matches "one thousand two hundred".

**Threshold logic** (`tests/test_thresholds.py`, hand-built transcripts, no audio): `[KEY]` met / near / diverged on rate, pause-after met / short / missing, overall status rule; `/` met / short / missing at 0.8 / 0.3 / 0 s; every threshold adjustable through `Settings`; section over / under / met with tolerance; a skipped line is "not found" and not scored; summary wording contains no grading words.

**`[DEFINE]` heuristic** (`tests/test_define.py`): "which is" after first use, "called" before it, never spoken, defined only much later (flagged with a note and the later evidence), plural/stem forms, evidence snippets carry timestamps. LLM path with a mocked model: a verifiable quote gets timestamps; an unverifiable quote falls back to the heuristic with a note; a model failure never breaks the report.

**Suggested marks** (`tests/test_suggest.py`, mocked over-marking model): out-of-range line and word indexes dropped, absent `[DEFINE]` terms dropped, ≤ 1 `[KEY]` per section and ≤ 3 total, ≤ 1 pause per 40 words, ≤ 4 defines, no section proposals when sections exist, an opening section is added when the model's first proposed section is not line 0, budgets computed in code (proportional to words, at the measured median or 140 wpm, labelled estimate; scaled to a target length when given), existing marks not duplicated, reasons capped at 20 words, `apply_marks` rewrites only accepted lines and preserves `*emphasis*`, `km/h`, and section headers.

**Stretch** (`tests/test_stretch.py`): conventions report only when enabled, counts "um" and "you know" with timestamps, pace band editable; coaching validator drops suggestions without a measured number and caps at three, skips the model when every mark was met, sends measurements plus history and never audio; emphasis detects a synthetic loud word; take comparison counts outcomes per mark across takes.

**End to end on synthetic audio** (`tests/test_fixture_pipeline.py`, marked `slow`): `tests/fixtures/fixture.wav` is 33.7 s of Windows text-to-speech built by `make_fixture.py`. Nine lines, three sections, silences of chosen lengths, one `[KEY]` line time-stretched 1.3× faster and one 0.8× slower. Asserted against `fixture_truth.json`:

| Check | Tolerance | Result on the dev machine |
|---|---|---|
| Every line found; start/end times | ± 0.4 s | all 9 lines, max error ≈ 0.25 s |
| Section durations and over/under status | ± 0.6 s | Opening met, Methods over (budget set 6 s short), Results met |
| `/` inside a line with no silence | status | missing (0.00 s) |
| `//` after a key line, 1.6 s inserted | ± 0.15 s | met, measured 1.57 s |
| `/` with only 0.3 s inserted | ± 0.15 s | short, measured 0.36 s |
| `[KEY]` stretched 1.3× faster | status | rate diverged (+19 % vs median), pause after met |
| `[KEY]` stretched 0.8× slower | status | rate met (−20 %), pause after met |
| `[DEFINE: degree heating weeks]` with "which is" | status | defined (heuristic), evidence at 11.6 s |

Regenerate the fixture with `uv run python tests/fixtures/make_fixture.py` (needs a system TTS voice; the committed WAV means tests do not).

**Improvise** (`tests/test_improv.py`, hand-built transcripts and synthetic harmonic tones): "kind of" counted as a hedge and not a filler, noun use ("a kind of tree") ignored; hedges map to word indexes and times; restarts ("I I", "the the", "th-") detected and "very very" ignored; a long silence mid-sentence is a hesitation while the same silence after a full stop is a deliberate pause; sentence splitting; time goal met / under with the 5 s floor; overall and windowed pace, band editable; clarity flags only low-confidence non-filler words and is "not measurable" without word confidence; uptalk detected on rising statement endings and not on falling ones; monotone vs. varied pitch range; trailing off from final-word loudness; opening energy; summary has no grading words; drills cite numbers and cap at three; delivery coaching drops number-less suggestions and caps at three; content review drops unverifiable quotes and caps the suggested opening at 30 words; coaching sends numbers and history, and the transcript only when content review is on. Routes through FastAPI's test client with a stub transcriber: topics list, creating a take (filler prompt sent, word confidence kept), script routes refuse Improvise takes, Improvise re-analysis honours new bands, validation of topic and goal.

**Take lifecycle** (`tests/test_lifecycle.py`, FastAPI test client with a stub transcriber and one that raises): a failed take keeps its folder, script, settings and label and returns its id in the 500; it is listed as failed with the error; a failed Improvise take keeps its topic; retry resumes from the saved upload, keeps the label and creation time, and does not call speech-to-text again when the transcript was saved; retry and delete refuse finished and busy takes (409); a folder holding only `audio.orig.wav` (the shape of an older failed take) is listed with a reason, needs a script to retry, and succeeds with one; a take without its recording can only be deleted; "processing" is reported only while this process is working on it, and a take left by a stopped server is retryable at once; a failure while creating a take leaves nothing half-made or stuck; the upload's file suffix is sanitized (no NTFS alternate data streams); retry reuses the saved settings unless new ones are sent; re-analysis refuses unfinished and busy takes; coaching results are saved only if no re-analysis changed the numbers meanwhile (script and Improvise); stray folders and temp files are ignored; JSON writes survive a briefly locked file; an empty upload is refused before a folder exists. Example take: created while speech-to-text is made to fail (it is never called), labelled, kind `example`; re-analysis keeps kind and label; examples are left out of same-script comparison and of the latest median; the `[DEFINE]` model call happens once across repeated re-analyses.

**`[DEFINE]` cache** (`tests/test_define.py`): one model call for repeated checks; a new call when the transcript text, the terms, the model or the prompt changes; nothing cached when the model fails or is absent; a cached answer whose quote is not in the transcript still falls back to the heuristic.

## Checked manually only

- Demo safety, in the browser against a dev server with its own takes folder: **Load example take** from the Report empty state (it worked while the speech model was still loading); a deliberately broken upload on Rehearse and on Improvise shows the failure with Retry, Download recording and Start over; the Takes tab lists it as "Not analyzed" with the error, Retry (fails again, as it should for a broken file) and Delete (removed it); clearing localStorage and reloading opens the newest finished take; a real upload through the page's file input reaches the report. The run scripts' stale-build check was exercised by touching a source file (both the PowerShell and the bash form of the check); the full `run.ps1` / `run.sh` were not re-run end to end.

- Recording in the browser with a real microphone, the elapsed clock, the planned-section indicator, the loudness meter, calibration, and the opt-in live pace. The automated browser used for verification has no microphone; the "microphone unavailable" path was exercised and shows the upload alternative.
- Uploading a file through the page (verified by posting the fixture through the page's own `FormData` path), the report rendering, tooltips, section bars, click-to-play seeking to a line's start, Takes list and comparison card, Settings changes triggering re-analysis.
- The suggestion review UI (ghost marks, reasons, accept/reject/accept-all, apply) was exercised with `TAKE_TWO_LLM=fake`, a labelled development stand-in. A real Anthropic call has **not** been exercised (no key on the build machine); the request shape follows the SDK's structured-output API and the response is validated by the same code the tests cover.
- The OpenAI Whisper API adapter is implemented but untested (no key).
- Improvise in the browser: setup (shuffle, category filter, custom topic, goal chips, coaching choice), the prep countdown and cancel, the report from the fixture posted to `/api/improv` (cards, annotated transcript, pitch strip, drills, trend table), Settings changes re-analysing an Improvise take, and the content review with `TAKE_TWO_LLM=fake` (including an invented quote being dropped). Recording with a real microphone, the countdown during speech, overtime colouring and the 2× safety stop are not exercised automatically (no microphone).

## Known weak spots

- **Whisper timestamp drift.** Word boundaries can be off by 0.1–0.3 s, more on long takes; line boundaries inherit this. Pauses are measured by the voice-activity detector instead, which is why `/` reads 0.36 s on a 0.30 s gap (VAD padding), not 0.46 s (Whisper's gap).
- **Misrecognized words** reduce a line's matched coverage. Rate uses the script's word count across the aligned span, so a wrong word does not read as slower speech, but a line under 50 % coverage is reported as not found.
- **Numbers and names.** Years ("2019" vs "twenty nineteen") and unusual proper nouns often do not align.
- **Fillers.** Whisper usually omits "um" and "uh"; with the conventions preset on, the transcriber is nudged with a prompt, but the count stays a lower bound.
- **Emphasis** is experimental: loudness depends on microphone distance and head movement; pitch estimation fails on breathy or very low voices.
- **Heuristic `[DEFINE]`** can be fooled by cue words used for something else ("that is" as a plain phrase) and misses definitions by example that use none of the cue phrases.
- **Suggestions** are only as good as the model; caps limit over-marking but cannot make a weak reason good. The reasons are shown precisely so the user can judge them.
- **Improvise bands are conventions, not truths.** Defaults (pace 130–170 wpm, ≤ 2 fillers per 100 words, ≥ 5 semitones of pitch range, …) are starting points; uptalk and trailing-off depend on Whisper's sentence punctuation and on clean word timestamps.
- **Improvise clarity** is Whisper's word confidence: it also drops for rare names and technical terms said perfectly well.
- **Section tolerance floor** of 3 s means very short sections are rarely reported over or under.
