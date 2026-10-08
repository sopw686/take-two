# Marked

Marked is a rehearsal coach for science talks that checks your delivery against **your own marks**, not a universal standard. You mark up the script the way performers mark a poem: slow down here, pause here, define this term aloud. Then you rehearse out loud and the report shows, line by line, where the take diverged from what you intended.

## Run it

Requirements: [uv](https://docs.astral.sh/uv/), Node 18+ (for the one-time frontend build). An NVIDIA GPU is used automatically if present; CPU works too.

```powershell
.\run.ps1
```

```bash
./run.sh
```

Then open http://127.0.0.1:8765. The first run installs the Python environment, builds the frontend, and downloads the `small.en` speech model (~500 MB) if it is not cached.

Everything runs locally by default. Audio never leaves your computer unless you configure a cloud key (below), and the app says so at the top of the page.

## Optional keys

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables **Suggest marks** and LLM-checked `[DEFINE]` terms. Without it, suggestions are disabled with a one-line note and definitions use a heuristic, labelled as such. |
| `OPENAI_API_KEY` + `MARKED_STT=openai` | Transcribe with OpenAI's Whisper API instead of locally. The UI shows a banner when audio leaves the machine. |
| `MARKED_STT_MODEL` | Local model: `base.en` (faster), `small.en` (default), `medium.en`, … |
| `MARKED_STT_DEVICE` | `auto` (default), `cuda`, or `cpu`. |
| `MARKED_LLM=fake` | Development only: a labelled stand-in model so the suggestion UI can be tried without a key. Not a fallback; without it and without a key, suggestions stay off. |

## Mark syntax

| Mark | Meaning | What is measured |
|---|---|---|
| `## Section name [2:00]` | Section with a time budget (m:ss) | Spoken duration vs. budget |
| `[KEY]` at the start of a line | Key line: slower than your median, then a pause | Line rate vs. your median line rate in this take; silence after the line |
| `word / word` | Deliberate short pause (default ≥ 0.7 s) | Silence at that point (voice-activity detector) |
| `word // word` | Deliberate long pause (default ≥ 1.5 s) | Same |
| `[DEFINE: term]` | The term must be explained aloud at or before its first use | Where the term was first spoken and whether a definition precedes it |
| `*word*` | Emphasis (experimental, off by default) | Loudness and pitch of the word vs. the rest of its line |

All thresholds are yours to change in **Settings**. Wording in the report is "met your mark" / "diverged from your mark"; there is no score.

## What the report shows

- A short summary: "2 of 3 key lines met your marks. Methods ran 0:12 over budget. 'Convolution' was never defined."
- Section bars: budget vs. spoken time.
- The script itself with every mark colored met / close / diverged; hover for the numbers in plain words; click any line or mark to hear that moment.
- Takes tab: every take you recorded, and a mark-by-mark comparison across takes of the same script ("you rushed this key line in 3 of 4 takes").
- Optional, only when switched on in Settings: a "conference conventions" preset (overall pace band, filler words per 100) and an experimental emphasis check for `*word*`.
- With an API key: "Suggestions based on your measurements", at most three, each citing a measured number and the mark it concerns.

## Tests

```bash
uv run pytest            # unit tests, about a second
uv run pytest -m slow    # the synthetic fixture through real local speech-to-text
```

See `TESTING.md` for what is covered, what was checked by hand, and known weak spots.

## Layout

```
marked/           FastAPI backend: parser, STT adapters, VAD, alignment, analysis, LLM features
frontend/         Vite + TypeScript UI, built into frontend/dist and served by the backend
tests/            unit tests + a synthetic TTS fixture with known ground truth (uv run pytest; -m slow for STT)
takes/            your recordings and analyses, one folder per take (not committed)
sample_script.md  a placeholder talk to try the marks on
```

See `DECISIONS.md` for design choices, `TESTING.md` for what is and is not verified, `DEMO.md` for a demo walkthrough, and `PITCH.md` for the pitch outline.

## Known limitations

- Word timestamps from Whisper drift by up to ~0.2 s; pauses are measured with a separate voice-activity detector, but line boundaries inherit that noise.
- Words the recognizer gets wrong lower a line's "matched" coverage; a line under 50 % coverage is reported as not found rather than scored.
- Whisper usually drops "um" and "uh"; the opt-in filler count is a lower bound.
- The emphasis check is experimental and sensitive to microphone distance.
- Mobile layouts are not a goal; use a laptop.
