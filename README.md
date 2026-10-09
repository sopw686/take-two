# Take Two

**A rehearsal coach for anyone who needs to land an idea out loud. It checks your delivery against your own marks, not a universal standard.**

> One-page writeup: [WRITEUP.md](WRITEUP.md)

You mark up the script the way a performer marks a poem (slow down here, pause here, explain this aloud), rehearse out loud, and get a report showing line by line where the take met or diverged from what *you* intended. There is no overall score. The same few marks cover talks, toasts, poems and pitches: `[KEY]` for the line that has to land, `/` and `//` for the pauses you mean, `[DEFINE: term]` for anything your audience may not know, and section time budgets.

- **Measured, not judged:** every mark comes back as met, close to, or diverged from *your* mark, with the number behind it and the moment a click away.
- **Local-first:** speech-to-text (faster-whisper) and pause detection (Silero VAD) run on your machine. Audio leaves it only if you add a cloud key, and the UI says so.
- **Optional LLM features** (Claude): suggest marks, check whether a `[DEFINE]` term was explained, coaching notes. The model sees text and numbers, never audio, and code verifies its output (e.g. quotes not found in the transcript are dropped).
- **Stack:** Python / FastAPI backend, TypeScript / Vite frontend. 345 Python unit tests and 18 frontend tests, a synthetic recording with known ground truth, and browser tests that record through Chrome's fake microphone, including a full spoken-examiner session.

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
cd frontend; npm test       # the frontend's pure logic (cue plan -> utterances) under Node's test runner (Node 22+)
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
| `[SAY: word = KOH-ral \| ˈkɔːrəl]` | How you say a word (a respelling, optional IPA), used by Hear it | Not measured: the report does not check pronunciation |

All thresholds are yours to change in **Settings**. Wording in the report is "met your mark" / "diverged from your mark"; there is no score.

**Settings that travel with the script.** A first line such as

```
<!-- take-two: short_pause_s=0.9 key_slower_pct=15 conventions_enabled=true -->
```

sets those thresholds for every take of that script, over the Settings dialog, so a script shared with a colleague or recorded on another machine is measured the same way. The names are the Settings field names (`short_pause_s`, `long_pause_s`, `pause_near_ratio`, `key_slower_pct`, `key_pause_after_s`, `section_tolerance_pct`, `line_min_coverage`, `baseline_min_words`, `min_silence_s`, `fuzzy_match_ratio`, `fuzzy_min_chars`, `paraphrase_min_words_pct`, `conventions_enabled`, `conventions_wpm_min`, `conventions_wpm_max`, `conventions_filler_per_100`, `emphasis_enabled`, `hear_baseline_wpm`, `hear_register`, `coach_slow_pct`, `coach_pause_s`, `clarity_prob`, `clarity_context_words`, the `examiner_…` settings, and the `improv_…` bands). Only the first non-blank line counts; it is a comment, so it moves no line numbers. The editor says what the line sets (or what is wrong with it) as you type, the Settings dialog marks those fields, and the report lists the values that came from the script. A take with an invalid line is refused before anything is saved.

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
- **Words that may not have been clear**: script words the recognizer heard as another word ("The script says “bleaching”; the recognizer heard “leaching” (confidence 0.57).") or was less sure of than your threshold, each with its time (click to hear it), **Hear it** (the word slowly, then at an ordinary pace) and **Drill this word** (say just that word; the result is what the recognizer heard, with its confidence). A recognizer can miss a word because of an accent, a noisy microphone, a rare word or a quiet moment, and the card says so; **I said it fine** leaves a word out of later reports.
- **Hear it** on each `[KEY]` line (see below), with **Try it** opening that line's drill.
- **Drill** a `[KEY]` line or a section from the report: record just that part, judged against the median of the full take it came from ("This try: 18% slower than your median from the full take; pause after 0.9 s: met your mark"). Drills are listed under their take.
- **Load example take** (Report and Takes tabs): a synthetic-voice take of a short coral-reef script, analyzed instantly from a committed transcript. It needs no microphone and no speech model, so you can see a full report on any machine. It is labelled as synthetic and left out of comparisons.
- A failed analysis never loses the recording: the take stays in Takes as "Not analyzed" with Retry (re-runs from the copy on disk) and Delete, and the page offers Download recording.
- Optional, only when switched on in Settings: a "conference conventions" preset (overall pace band, filler words per 100) and an experimental emphasis check for `*word*`.
- With an API key: "Suggestions based on your measurements", at most three, each citing a measured number and the mark it concerns.

## Hear it

A synthetic voice demonstrates one line, so you can hear what your marks ask for before you try it. It is on every line of the Script tab (**Hear your lines**), on the report's `[KEY]` lines and in a line drill. Two versions, back to back:

- **As I marked it**: only what you wrote, read the way the report reads it. `/` and `//` are timed silences of your own short- and long-pause settings; a `[KEY]` line is said your `key_slower_pct` slower than your median from that take (or your latest take), then your pause; a `*word*` is louder and higher; a `[SAY]` word is said your way. Before your first take there is no median, so a typical 150 wpm baseline is used and labelled as a baseline, never as your rate. A line with no marks is spoken plainly.
- **Coach's version**: your marks, plus a delivery the coach invents: which word to stress, which to slow down, a rising, falling or held end on each phrase, extra pauses, softer and lower for a sincere line, a build toward a turn, an overall pace. With an API key a model invents it from the line and the register you picked; code keeps only cues whose words are copied verbatim from the line, clamps every number, caps the count and requires a reason for each. Without a key it comes from the register's plain rules, labelled "heuristic, not a model"; with neither a key nor a register it is off and says why. Your written marks are never removed or shortened, only added to.

Under the button is the plan in words: "slower: 10% below your median (150 wpm → 135)", "0.7 s pause after “result” (your short-pause setting)". Each cue says whether the report **checks** it or it is a **demonstration only**. The coach's cues are labelled **coach's suggestion**; **Accept into script** turns the ones that have a mark (a pause, a stressed word) into real marks, so the next take checks them. A contour, a slowed word or a pace change has no mark and stays a demonstration. **Try it** opens the line drill: you say the line and it is measured against the same marks and the same median.

A **register** is a starting point you pick in Settings (off until you do). It tells the coach what landing it means for this speech, and it is never used to judge a take:

| Register | The coach's rules |
|---|---|
| Conversational / technical talk | Phrases of about 3–5 s; slow down for numbers, definitions and the main result; pause before and after the point; one or two stressed words per sentence at most; a falling end on statements, so a claim sounds finished |
| Celebratory (toast, tribute) | Warmth over speed, slightly slower overall; a pause after the punchline for the room to react; lower and slower for the sincere line; the last line slowest, a clear falling end, then silence |
| Performance poetry / slam | The line break is a breath; build pace and volume toward the turn, drop just before it; contrast; end lines on a held or falling note; the last line gets the longest pause |
| Pitch / interview | Lead with the claim; slow down on the number and the ask; no trailing off |

How much slower a slowed word is and how long an added pause is are yours too (Settings → Hear it).

**Voices.** By default your browser's own voice speaks (local, no key, no network). It gives coarse control of pace and pitch and none of tone, so a rising or falling end is approximated by saying the last word a little higher or lower; the panel says so. Pick a voice (remembered). Optionally, with `TAKE_TWO_TTS=azure` and an Azure Speech key, a server voice speaks SSML (real breaks, prosody, pitch contours, IPA pronunciations); it receives the text of the line you play and nothing else, only after you choose it and confirm what it sends. The synthetic audio is never saved with a take or analyzed. On screen: "Synthetic demonstration of your marks. It shows one way to do it, not the way."

**Words worth checking** (Script tab) lists names, loanwords, acronyms and uncommon words (rarity is read from the speech recognizer's own vocabulary). With an API key each gets a proposed pronunciation, a respelling such as KOH-ral and IPA where useful, labelled "proposed pronunciation: confirm it", because a model can be wrong about names. Edit it, hear it syllable by syllable, and **Confirm** to write a `[SAY]` mark into your script. Without a key you type how you say it.

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

## Spoken examiner

A hands-free Q&A for a defense, a pitch or an interview, where the answers are oral, unscripted and timed, and your hands and eyes are on your notes. Improvise tab → **Spoken examiner**:

1. **Set up** (keyboard is fine here): the questions (proposed from your script with an API key, your own typed one per line, or a mix), how many (3–6), thinking time, the longest answer, and how much silence ends an answer (about 3 s by default). Pick the examiner's voice; it is separate from the coach's.
2. **Run**: the examiner asks each question aloud. When it has finished speaking, a short tone plays, the thinking time counts down on screen, and recording starts on its own. **The microphone is never open while the examiner speaks.** Your answer ends when you have been silent longer than your threshold after speaking, at the maximum length, or when you press **Space**.
3. Each answer is analyzed as an ordinary **Improvise take whose topic is the question**, with every Improvise measure, and is listed in Takes, ready to compare, drill or export.
4. **One follow-up per question**, with an API key: the model reads only that answer's transcript and its measured numbers (never audio) and asks one short question you can answer from what you just said ("You said the effect doubled: compared with what?"). Code drops it if it is more than one question, is not grounded in words you said, or quotes words you did not say. Without a key there are no follow-ups; the examiner moves on and says so.
5. **Close**: the examiner reads a line the app writes from your numbers, for example "You answered 4 questions. 2 stayed within your pace band, 2 were close to it. The longest hesitation before an answer was 6 seconds." The same text is on screen with a link to each answer's report. No score, no grade.

Keys at any time: **Space** finish the answer, **R** hear the question again, **S** skip, **Esc** end the session. Answers already recorded are kept if you stop, and an answer whose analysis fails keeps its recording and a Retry. Without speech voices or microphone permission the page says which is missing and points you to **Questions about my script**, where the same questions can be read and answered or uploaded.

## Optional keys

| Variable | Effect |
|---|---|
| `ANTHROPIC_API_KEY` | Enables **Suggest marks** and LLM-checked `[DEFINE]` terms. Without it, suggestions are disabled with a one-line note and definitions use a heuristic, labelled as such. |
| `OPENAI_API_KEY` + `TAKE_TWO_STT=openai` | Transcribe with OpenAI's Whisper API instead of locally. The UI shows a banner when audio leaves the machine. |
| `TAKE_TWO_STT_MODEL` | Local model: `base.en` (faster), `small.en` (default), `medium.en`, … |
| `TAKE_TWO_STT_DEVICE` | `auto` (default), `cuda`, or `cpu`. |
| `TAKE_TWO_TAKES_DIR` | Where takes are saved (default `takes/` next to the app). If that folder is inside a cloud-synced folder (OneDrive, Dropbox, iCloud), the sync client uploads your recordings; point this at a local folder to keep audio on the machine. |
| `TAKE_TWO_LLM=fake` | Development only: a labelled stand-in model so the suggestion UI can be tried without a key. Not a fallback; without it and without a key, suggestions stay off. |
| `TAKE_TWO_TTS=azure` + `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` | Offers an Azure Speech voice for Hear it (SSML). It is sent the text of the line you play, only after you pick it and confirm; the banner says so. `TAKE_TWO_AZURE_VOICE` picks the voice (default `en-US-JennyNeural`). Not yet run against Azure (no key on the development machine). |
| `TAKE_TWO_TTS=fake` | Development only: a labelled server "voice" that plays tones in place of speech, with the plan's timing. |

## Project layout

```
take_two/           FastAPI backend: parser, STT adapters, VAD, alignment, analysis, LLM features, Improvise (improv*.py, prosody.py, topics.py), Hear it (delivery.py, pronounce.py, clarity.py, tts.py)
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
