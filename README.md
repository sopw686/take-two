# Take Two

Take Two is a rehearsal coach for science talks that checks your delivery against **your own marks**, not a universal standard. You mark up the script the way performers mark a poem: slow down here, pause here, define this term aloud. Then you rehearse out loud and the report shows, line by line, where the take diverged from what you intended.

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
| `OPENAI_API_KEY` + `TAKE_TWO_STT=openai` | Transcribe with OpenAI's Whisper API instead of locally. The UI shows a banner when audio leaves the machine. |
| `TAKE_TWO_STT_MODEL` | Local model: `base.en` (faster), `small.en` (default), `medium.en`, … |
| `TAKE_TWO_STT_DEVICE` | `auto` (default), `cuda`, or `cpu`. |
| `TAKE_TWO_TAKES_DIR` | Where takes are saved (default `takes/` next to the app). If that folder is inside a cloud-synced folder (OneDrive, Dropbox, iCloud), the sync client uploads your recordings; point this at a local folder to keep audio on the machine. |
| `TAKE_TWO_LLM=fake` | Development only: a labelled stand-in model so the suggestion UI can be tried without a key. Not a fallback; without it and without a key, suggestions stay off. |

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

## Rehearsing

The Rehearse tab shows the script as a **teleprompter**: large type (A−/A+, remembered), `[KEY]` lines tinted, `/` and `//` as visible gaps, defined terms underlined, section headers with their budgets. The highlight follows your plan (each section's budget spread over its lines by word count), not your voice. Space / ↓ and ↑ (or a clicker's page keys) move it when you are ahead or behind, and scrolling by hand pauses the auto-scroll for a few seconds. Without budgets it is manual only. The clock, the planned-section line, the loudness meter, calibration and the upload path sit around it.

## What the report shows

- A timeline strip over the whole take: silences found by the voice-activity detector, when each line was spoken, and where each mark was measured. Click to hear that moment.
- A short summary: "2 of 3 key lines met your marks. Methods ran 0:12 over budget. 'Convolution' was never defined."
- **Focus for the next take**: at most three marks to work on, written by the app from your numbers (no model, no key): marks that diverged in two or more takes first, then this take's largest divergences.
- Section bars: budget vs. spoken time, and for a section that ran over, **cut to fit** in words at your own median ("Methods ran 0:22 over: about 55 words at your 150 wpm"), plus the same for the whole talk.
- The script itself with every mark marked met ✓ / close ~ / diverged ✗ / not measured –; hover, focus or click a mark for the numbers in plain words (a click also plays that moment); click any line to hear it. Optionally, **what you said vs. the script**: dropped words struck through, ad-libs boxed in place, "N words differ" per line.
- While a take is analyzed, the page shows each stage: decoding, transcribing, aligning, definition check.
- Takes tab: every take you recorded, and a mark-by-mark comparison across takes of the same script ("you rushed this key line in 3 of 4 takes").
- **Load example take** (Report and Takes tabs): a synthetic-voice take of a short coral-reef script, analyzed instantly from a committed transcript. It needs no microphone and no speech model, so you can see a full report on any machine. It is labelled as synthetic and left out of comparisons.
- A failed analysis never loses the recording: the take stays in Takes as "Not analyzed" with Retry (re-runs from the copy on disk) and Delete, and the page offers Download recording.
- Optional, only when switched on in Settings: a "conference conventions" preset (overall pace band, filler words per 100) and an experimental emphasis check for `*word*`.
- With an API key: "Suggestions based on your measurements", at most three, each citing a measured number and the mark it concerns.

## Improvise

A second mode with no script and no marks: pick a topic (shuffle a built-in list by category, or type your own), a time goal (30 s to 5 min, or custom), and optional thinking time. Speak; a countdown shows the time left and turns to overtime. The report covers what a listener picks up on:

| Group | What is measured |
|---|---|
| Time | Spoken time vs. your goal |
| Pace | Words per minute, overall and per 15-second stretch |
| Fillers and hesitation | um / uh / "you know" / "like,"; silences of 1.2 s+ inside a sentence; restarts ("I I", cut-off words) |
| Confidence | Hedges ("I think", "maybe", "kind of"); statements whose last word rises in pitch (uptalk); sentences that fade on the last word |
| Clarity (proxy) | Words the recognizer was unsure of; a sign of mumbling or swallowed endings, not a pronunciation score |
| Engagement | Pitch range (monotone vs. varied), loudness variation, pace variation, deliberate pauses between sentences, opening energy |

Every measure is compared with a **reference band you can edit** in Settings → *Improvise reference bands*; there is no overall score. The transcript is shown with fillers, hedges, restarts, unclear words, hesitations, and rising or fading endings marked in place; click any word to hear it. Up to three practice drills are written by the app from your numbers, with no model involved.

Before recording, choose **Delivery only** (fully local) or **Delivery + content**. With an API key, content mode also asks the model to review the hook, staying on topic, suspense and the ending from the transcript text; every judgement must quote your words, and code drops any quote it cannot find. The model also proposes one more gripping opening line. Improvise takes appear in Takes with a badge, and the report shows your recent Improvise numbers side by side.

## Tests

```bash
uv run pytest            # unit tests, about a second
uv run pytest -m slow    # the synthetic fixture through real local speech-to-text
```

See `TESTING.md` for what is covered, what was checked by hand, and known weak spots.

## Layout

```
take_two/           FastAPI backend: parser, STT adapters, VAD, alignment, analysis, LLM features, Improvise (improv*.py, prosody.py, topics.py)
frontend/         Vite + TypeScript UI, built into frontend/dist and served by the backend
tests/            unit tests + a synthetic TTS fixture with known ground truth (uv run pytest; -m slow for STT)
takes/            your recordings and analyses, one folder per take (not committed)
examples/         the example take (synthetic voice, script, committed transcript)
sample_script.md  a placeholder talk to try the marks on
```

See `DECISIONS.md` for design choices, `TESTING.md` for what is and is not verified, `DEMO.md` for a demo walkthrough (with `demo_speech.md`, a marked talk about Take Two), `PITCH.md` for the pitch outline, and `WRITEUP.md` for the one-page submission write-up.

## Known limitations

- Word timestamps from Whisper drift by up to ~0.2 s; pauses are measured with a separate voice-activity detector, but line boundaries inherit that noise.
- Words the recognizer gets wrong lower a line's "matched" coverage; a line under 50 % coverage is reported as not found rather than scored.
- Whisper usually drops "um" and "uh"; the opt-in filler count is a lower bound.
- The emphasis check is experimental and sensitive to microphone distance.
- Mobile layouts are not a goal; use a laptop.
- Improvise's clarity measure is the recognizer's confidence, not phoneme-level pronunciation scoring. Pitch measures need `praat-parselmouth` (installed by default); without it they show as not measurable.
