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

## Checked manually only

- Recording in the browser with a real microphone, the elapsed clock, the planned-section indicator, the loudness meter, calibration, and the opt-in live pace. The automated browser used for verification has no microphone; the "microphone unavailable" path was exercised and shows the upload alternative.
- Uploading a file through the page (verified by posting the fixture through the page's own `FormData` path), the report rendering, tooltips, section bars, click-to-play seeking to a line's start, Takes list and comparison card, Settings changes triggering re-analysis.
- The suggestion review UI (ghost marks, reasons, accept/reject/accept-all, apply) was exercised with `MARKED_LLM=fake`, a labelled development stand-in. A real Anthropic call has **not** been exercised (no key on the build machine); the request shape follows the SDK's structured-output API and the response is validated by the same code the tests cover.
- The OpenAI Whisper API adapter is implemented but untested (no key).

## Known weak spots

- **Whisper timestamp drift.** Word boundaries can be off by 0.1–0.3 s, more on long takes; line boundaries inherit this. Pauses are measured by the voice-activity detector instead, which is why `/` reads 0.36 s on a 0.30 s gap (VAD padding), not 0.46 s (Whisper's gap).
- **Misrecognized words** reduce a line's matched coverage. Rate uses the script's word count across the aligned span, so a wrong word does not read as slower speech, but a line under 50 % coverage is reported as not found.
- **Numbers and names.** Years ("2019" vs "twenty nineteen") and unusual proper nouns often do not align.
- **Fillers.** Whisper usually omits "um" and "uh"; with the conventions preset on, the transcriber is nudged with a prompt, but the count stays a lower bound.
- **Emphasis** is experimental: loudness depends on microphone distance and head movement; pitch estimation fails on breathy or very low voices.
- **Heuristic `[DEFINE]`** can be fooled by cue words used for something else ("that is" as a plain phrase) and misses definitions by example that use none of the cue phrases.
- **Suggestions** are only as good as the model; caps limit over-marking but cannot make a weak reason good. The reasons are shown precisely so the user can judge them.
- **Section tolerance floor** of 3 s means very short sections are rarely reported over or under.
