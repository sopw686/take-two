# Take Two

**A rehearsal coach for anyone who needs to land an idea out loud. It checks your delivery against your own marks, not a universal standard.**

> One-page writeup: [WRITEUP.md](WRITEUP.md)

You mark up the script the way a performer marks a poem (slow down here, pause here, explain this aloud), rehearse out loud, and get a report showing line by line where the take met or diverged from what *you* intended. There is no overall score. The same few marks cover talks, toasts, poems and pitches: `[KEY]` for the line that has to land, `/` and `//` for the pauses you mean, `[DEFINE: term]` for anything your audience may not know, and section time budgets.

- **Measured, not judged:** every mark comes back as met, close to, or diverged from *your* mark, with the number behind it and the moment a click away.
- **Local-first:** speech-to-text (faster-whisper) and pause detection (Silero VAD) run on your machine. Audio leaves it only if you add a cloud key, and the UI says so.
- **Optional LLM features** (Claude): suggest marks, check whether a `[DEFINE]` term was explained, coaching notes. The model sees text and numbers, never audio, and code verifies its output (e.g. quotes not found in the transcript are dropped).
- **Stack:** Python / FastAPI backend, TypeScript / Vite frontend. 295 unit tests, a synthetic recording with known ground truth, and a browser test that records through Chrome's fake microphone.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Node 18+ (one-time frontend build). An NVIDIA GPU is used automatically if present; CPU works too.

```powershell
# Windows
.\run.ps1
```

```bash
# macOS / Linux / Git Bash
./run.sh
```

Then open <http://127.0.0.1:8765>. The first run installs the Python environment, builds the frontend, and downloads the `small.en` speech model (~500 MB).

**No microphone, model or key needed:** open the **Report** tab and click **Load example take** to see a full report from a synthetic-voice take.

**To try it yourself:** on the Script tab, **Start from an example**, paste your own script, or import the speaker notes of a PowerPoint deck; then go to Rehearse, record, and read the report.

## Run the tests

```bash
uv run pytest            # unit tests, about 20 seconds
uv run pytest -m slow    # synthetic fixture through real local speech-to-text
uv run pytest -m browser # record, stop and read the report in Chrome with a fake microphone (needs Google Chrome, ~90 s)
uv run python -m eval.run   # evaluation against labelled recordings -> eval/RESULTS.md (see eval/README.md)
uv run python scripts/writeup_pdf.py           # WRITEUP.md -> WRITEUP.pdf; fails if over one page or a required section is missing
uv run python scripts/writeup_pdf.py --watch   # rebuild the PDF every time WRITEUP.md is saved
```

More detail: [TESTING.md](TESTING.md), [DECISIONS.md](DECISIONS.md), [eval/README.md](eval/README.md).

---

# Reference

## Mark syntax

| Mark | Meaning | What is measured |
|---|---|---|
| `## Section name [2:00]` | Section with a time budget (m:ss) | Spoken duration vs. budget |
| `[KEY]` at the start of a line | Key line: slower than your median, then a pause | Line rate vs. your median line rate in this take (a drill uses its full take's median; a paraphrased line is not rate-checked); silence after the line |
| `word / word` | Deliberate short pause (default ≥ 0.7 s) | Silence at that point (voice-activity detector) |
| `word // word` | Deliberate long pause (default ≥ 1.5 s) | Same |
| `[DEFINE: term]` | A term your audience may not know (technical term, in-joke, reference) must be explained aloud at or before its first use | Where the term was first spoken and whether a definition precedes it |
| `*word*` | Emphasis (experimental, off by default) | Loudness and pitch of the word vs. the rest of its line |

All thresholds are yours to change in **Settings**. Wording in the report is "met your mark" / "diverged from your mark"; there is no score.

**Settings that travel with the script.** A first line such as

```
<!-- take-two: short_pause_s=0.9 key_slower_pct=15 conventions_enabled=true -->
```

sets those thresholds for every take of that script, over the Settings dialog, so a script shared with a colleague or recorded on another machine is measured the same way. The names are the Settings field names (`short_pause_s`, `long_pause_s`, `pause_near_ratio`, `key_slower_pct`, `key_pause_after_s`, `section_tolerance_pct`, `line_min_coverage`, `baseline_min_words`, `min_silence_s`, `fuzzy_match_ratio`, `fuzzy_min_chars`, `paraphrase_min_words_pct`, `conventions_enabled`, `conventions_wpm_min`, `conventions_wpm_max`, `conventions_filler_per_100`, `emphasis_enabled`, and the `improv_…` bands). Only the first non-blank line counts; it is a comment, so it moves no line numbers. The editor says what the line sets (or what is wrong with it) as you type, the Settings dialog marks those fields, and the report lists the values that came from the script. A take with an invalid line is refused before anything is saved.

**Import from PowerPoint notes** (Script tab): each slide becomes a `## Slide N: title` section and its speaker notes become the lines, ready for budgets and marks. A slide without notes stays as an empty section, shown as "no script lines" in the report. The file is read by this app on your machine and not kept.

## Rehearsing

The Rehearse tab shows the script as a **teleprompter**: large type (A−/A+, remembered), `[KEY]` lines tinted, `/` and `//` as visible gaps, defined terms underlined, section headers with their budgets. The highlight follows your plan (each section's budget spread over its lines by word count), not your voice. Space / ↓ and ↑ (or a clicker's page keys) move it when you are ahead or behind, and scrolling by hand pauses the auto-scroll for a few seconds. Without budgets it is manual only. The clock, the planned-section line, the loudness meter, calibration and the upload path sit around it.

## What the report shows

- A timeline strip over the whole take: silences found by the voice-activity detector, when each line was spoken, and where each mark was measured. Click to hear that moment.
- A short summary: "2 of 3 key lines met your marks. Methods ran 0:12 over budget. 'Convolution' was never defined."
- **Focus for the next take**: at most three marks to work on, written by the app from your numbers (no model, no key): marks that diverged in two or more takes first, then this take's largest divergences.
- Section bars: budget vs. spoken time, and for a section that ran over, **cut to fit** in words at your own median ("Methods ran 0:22 over: about 55 words at your 150 wpm"), plus the same for the whole talk.
- The script itself with every mark marked met ✓ / close ~ / diverged ✗ / not measured –; hover, focus or click a mark for the numbers in plain words (a click also plays that moment); click any line to hear it. Optionally, **what you said vs. the script**: dropped words struck through, ad-libs boxed in place, "N words differ" per line.
- While a take is analyzed, the page shows each stage: decoding, transcribing, aligning, definition check.
- Takes tab: every take you recorded, and a mark-by-mark comparison across takes of the same script ("you rushed this key line in 3 of 4 takes"), with a ▶ in each cell to hear that take at that mark (A/B listening). Each take can be renamed, deleted (with its drills; the confirmation names the folder that will be removed) or downloaded as its folder (.zip). **Download outcomes (CSV)** gives every mark's status and numbers across your takes for a spreadsheet or a study, with no names, script text, transcript or audio in it.
- **Export report** (report and Takes tab): the report as one HTML file with the recording inside, every number and tooltip printed, click a line to hear it. It opens offline, so you can send it to an advisor; the app asks first if it would be over 20 MB.
- **Drill** a `[KEY]` line or a section from the report: record just that part, judged against the median of the full take it came from ("This try: 18% slower than your median from the full take; pause after 0.9 s: met your mark"). Drills are listed under their take.
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

**Questions about my script (Q&A practice).** Instead of a topic, practise the questions that follow a talk, a defense, a pitch or an interview: with an API key, the model reads the script on your Script tab and proposes five to eight likely audience questions, each tagged (clarification, methods challenge, limitation, implication) and tied to a script line; code drops any it cannot check. Or type a question you expect (no key needed). Your answer is an Improvise take on that question, and the content review adds "Answered the question", backed by a quote from your answer.

Before recording, choose **Delivery only** (fully local) or **Delivery + content**. With an API key, content mode also asks the model to review the hook, staying on topic, suspense and the ending from the transcript text; every judgement must quote your words, and code drops any quote it cannot find. The model also proposes one more gripping opening line. Improvise takes appear in Takes with a badge, and the report shows your recent Improvise numbers side by side.

## Optional keys

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables **Suggest marks** and LLM-checked `[DEFINE]` terms. Without it, suggestions are disabled with a one-line note and definitions use a heuristic, labelled as such. |
| `OPENAI_API_KEY` + `TAKE_TWO_STT=openai` | Transcribe with OpenAI's Whisper API instead of locally. The UI shows a banner when audio leaves the machine. |
| `TAKE_TWO_STT_MODEL` | Local model: `base.en` (faster), `small.en` (default), `medium.en`, … |
| `TAKE_TWO_STT_DEVICE` | `auto` (default), `cuda`, or `cpu`. |
| `TAKE_TWO_TAKES_DIR` | Where takes are saved (default `takes/` next to the app). If that folder is inside a cloud-synced folder (OneDrive, Dropbox, iCloud), the sync client uploads your recordings; point this at a local folder to keep audio on the machine. |
| `TAKE_TWO_LLM=fake` | Development only: a labelled stand-in model so the suggestion UI can be tried without a key. Not a fallback; without it and without a key, suggestions stay off. |

## Project layout

```
take_two/           FastAPI backend: parser, STT adapters, VAD, alignment, analysis, LLM features, Improvise (improv*.py, prosody.py, topics.py)
frontend/         Vite + TypeScript UI, built into frontend/dist and served by the backend
tests/            unit tests + a synthetic TTS fixture with known ground truth (uv run pytest; -m slow for STT)
takes/            your recordings and analyses, one folder per take (not committed)
examples/         the example take (synthetic voice, script, committed transcript)
eval/             evaluation harness: labelled recordings, eval.run -> RESULTS.md, eval.retest (noise floor)
sample_script.md  a placeholder science talk to try the marks on
examples/scripts/ a wedding toast and a slam poem (offered under "Start from an example")
```

## How it differs from other tools

Speech coaches like PowerPoint Speaker Coach, Yoodli and Orai grade everyone against one idea of a good speaker: even pace, no dead air. But a deliberate pause is the point of a toast's punchline, a poem's line break, or the sentence a talk exists to deliver, and a coach that rewards even pace cannot tell that pause from losing your place. Take Two measures against the marks you wrote, so the same take can be right for a slam poem and wrong for a conference talk.

What "landing it" means, by kind of speech:

- **Technical and academic talks:** the key result said slower than the rest and followed by silence, every unfamiliar term explained before it is used, and methods kept inside their time.
- **Celebratory speeches:** the pause after the punchline, and a sincere last line that isn't rushed.
- **Performance poetry and slam:** the breath at each line break, and the drop before the last line.
- **Pitches and interviews:** the number and the ask said slowly enough to be heard, inside a hard time limit.

## Known limitations

- Word timestamps from Whisper drift by up to ~0.2 s; pauses are measured with a separate voice-activity detector, but line boundaries inherit that noise.
- Words the recognizer gets slightly wrong ("leaching" for "bleaching") still match, and spoken years match digits. A line said in very different words is **paraphrased** (timed, counted in its section, but not rate-checked) when the lines around it were found and some of its own words were heard; otherwise it is reported as not found rather than scored. The thresholds are in Settings.
- Whisper usually drops "um" and "uh"; the opt-in filler count is a lower bound.
- The emphasis check is experimental and sensitive to microphone distance.
- Mobile layouts are not a goal; use a laptop. Dark mode follows your system setting; exported reports stay light, for printing.
- Improvise's clarity measure is the recognizer's confidence, not phoneme-level pronunciation scoring. Pitch measures need `praat-parselmouth` (installed by default); without it they show as not measurable.
