# Take Two: next milestones (M7–M14)

You are continuing work on **Take Two**, a local rehearsal coach for science talks. It is in this repository (Windows 11, PowerShell, `uv`, Node 18+). The app works and has 88 passing unit tests. Your job is to get it to a state that can be demoed live and defended in front of skeptical judges. The milestones below are in priority order. Finish each one completely (tests, build, browser check, docs, commit) before you start the next. A half-built later milestone is worth less than a finished earlier one.

## Read first

1. `README.md`, `DECISIONS.md`, `TESTING.md`, `DEMO.md`, `WRITEUP.md`. They hold the design rules and the reasoning behind them.
2. Skim `take_two/` (backend: `pipeline.py`, `analysis.py`, `align.py`, `marks.py`, `define.py`, `improv*.py`, `takes.py`, `app.py`) and `frontend/src/` (vanilla TypeScript, built with the `h()` helper in `dom.ts`).
3. Get a baseline: run `uv run pytest` (expect 88 passed) and `cd frontend; npm run build`.

## Non-negotiable product rules

These rules are the product. A judge will probe them, so every feature must follow them.

- **No score, no grades, no streaks.** Use the wording "met your mark", "close to your mark", "diverged from your mark", and "faster/slower than *your* median". Improvise uses "within / close to / outside your band". The existing tests check that summaries contain no grading words. Keep that true for every new piece of text.
- **The user sets the targets.** Every new threshold goes into `config.Settings` with a sensible default and bounds. It appears in the Settings dialog, travels with each request, and is stored in the analysis JSON. Conventions stay opt-in presets that are off by default.
- **Audio stays on the machine by default.** Add no new path that sends audio anywhere. Any feature that would need a cloud service sits behind the same banner as cloud speech-to-text.
- **A language model reads only text and measured numbers. It never hears audio.** Code validates every model output: indexes are checked, quotes must appear verbatim in the transcript or script or the item is dropped, every coaching item must cite a number, and results are capped. Without `ANTHROPIC_API_KEY`, a model-backed feature is disabled with a one-line reason. Never substitute a heuristic for it silently. `TAKE_TWO_LLM=fake` is a labelled development stand-in for exercising the UI only.
- **Measure, don't guess.** If a value cannot be measured, report it as "not measurable" or "not found" with a reason. Never show a guessed value as if it were measured. Each number in the report must trace back to timestamps that are in the analysis JSON.
- **No clinical or therapeutic claims.**
- **Match the codebase.** Use vanilla TypeScript with no UI framework and no new runtime frontend dependencies. Dev-only dependencies are fine. Match the existing comment density and naming. A small pure-Python backend dependency is acceptable if you justify it in `DECISIONS.md`.

## Working rules

- Add unit tests for every backend behaviour, using the style of the existing tests (hand-built transcripts, mocked LLM). Keep `uv run pytest` green and keep `npm run build` (which runs `tsc --noEmit`) green.
- Check every UI change in the browser through the preview tools. The `.claude/launch.json` config is named `take-two` and uses port 8765. If 8765 is already taken by the user's own server, navigate to it instead of starting another. The automated browser has **no microphone**, so use the upload path, the example take (M8), or Chrome's fake audio capture (M14). Rebuild the frontend before you check: FastAPI serves `frontend/dist`.
- For each milestone, update the docs:
  - `DECISIONS.md`: each entry states what was decided, what else was considered, and why.
  - `TESTING.md`: say honestly what is verified automatically and what was checked by hand only.
  - `README.md`: features and the marks table.
  - `DEMO.md`: when the demo flow changes.
  - Do **not** edit the `TODO (Sophie)` parts of `PITCH.md`. Those are hers to write.
- Commit after each milestone with a message like `M8: …`, in the style of the existing history. Never amend and never force. There is no git remote, so do not try to push.
- Leave `PROMPT_next_milestones.md` (this file) untracked.
- Never fabricate results. No invented evaluation numbers, user quotes, competitor claims, or "verified" labels for things you did not run. The real Anthropic API has never been called (there is no key on this machine), so keep labelling LLM paths as exercised only with the fake.
- If something blocks you (a dependency won't install, a design rule conflicts with a task), write down the conflict, choose the option that keeps the product rules, and keep going. Report it at the end.

---

## M7: Commit the existing work

A large amount of finished work is uncommitted: Improvise mode, prosody, topics, new tests, and doc updates. Run the tests and the build. If they pass, commit everything currently modified or untracked, except this prompt file, as `M7: Improvise mode …`, with a message that summarizes what is in the diff. Read the diff before you write the message.

## M8: Demo safety

1. **Recover failed takes.**
   - Today `submit()` in `frontend/src/rehearse.ts` (and the matching code in `improvise.ts`) resets the button when analysis fails, which throws away the recording. The server is left with a take folder that holds only `audio.orig.*` (see `takes/20261008-004237-3698`) and no way to retry.
   - Server: when analysis fails, keep the folder and write the error, the script, the settings, the mode and the label into it. `list_takes` returns unfinished takes with a status. Add a retry endpoint that re-runs ingest and analysis from the saved upload, and a delete endpoint for unfinished takes.
   - Client: on failure, keep the blob and offer **Retry** and **Download recording**. The Takes list shows unfinished takes with Retry and Delete buttons.
2. **Startup fallback.** `boot()` in `frontend/src/main.ts` only loads the take id saved in localStorage, so a fresh browser shows "No take yet" even when takes exist on disk. Fall back to the newest finished take.
3. **Rebuild when stale.** `run.ps1` (line 25) and `run.sh` only build the frontend when `dist` is missing. Rebuild when anything under `frontend/src`, `frontend/index.html` or `frontend/package.json` is newer than `frontend/dist/index.html`.
4. **Cache the `[DEFINE]` LLM result.** `pipeline.reanalyze` calls `check_defines(…, get_llm())` on every re-analysis, including every Settings save, which costs a model call each time. Cache the result in the take folder, keyed by a hash of the define terms, the transcript text and the LLM provider/model. Reuse it when the key matches. The heuristic path needs no cache.
5. **Example take.**
   - Ship `examples/coral/` containing the synthetic fixture (`tests/fixtures/fixture.wav`, its script, and a `transcript.json` produced once by running the real local speech-to-text on it, then committed).
   - Add an endpoint that copies the example into a new take and re-analyzes it. This uses no speech-to-text, so it is instant.
   - Label the result in the UI: "Example take (synthetic voice)".
   - Add a **Load example take** button to the Report empty state and the Takes tab. It must work with no microphone and no model loaded. Add a test.

## M9: Teleprompter on the Rehearse tab

The Rehearse tab does not show the script, so today the speaker has to read it from somewhere else. While rehearsing, show the script in large type with the marks drawn visually:

- `[KEY]` lines highlighted.
- `/` and `//` shown as visible gaps of different widths.
- `[DEFINE: term]` shown as an underlined term.
- Section headers with their budgets.

Behaviour:

- Highlight the **planned** position and scroll it smoothly. Spread each section's budget across its lines by word count. Label it honestly: "follows your plan, not your voice". This matches the existing planned-section indicator.
- Manual scrolling pauses auto-scroll for a few seconds.
- Space and the arrow keys move the highlight while recording, unless focus is in a text field.
- Add a font-size control, remembered in localStorage.
- Without budgets, there is no auto-scroll, only manual control.
- Keep the clock, the planned-section line, the meter, the label field and the upload path. Lay the page out so the script is the main thing on screen during a take.
- Update `DEMO.md` so the live demo reads from the teleprompter.

## M10: A report you can trust at a glance

1. **Timeline strip** at the top of the report: an SVG covering the whole take that shows line spans, mark positions colored by status, and the voice-activity-detector silences (already in `analysis["silences"]`), with a playhead. Click to seek. This shows where the numbers come from.
2. **What you said vs. the script.** For each line, show dropped script words (struck through and muted), and show ad-libbed transcript words that matched no script word between two script words (inline, in a different style). The backend must emit the ad-lib spans; the per-token alignment already exists in `align.py`. Show a line-level "N words differ" hint, and keep this view toggleable so the report stays calm.
3. **Cut to fit.** For each section over budget, convert the overrun into words at the speaker's measured median, e.g. "Methods ran 0:22 over: about 55 words at your 150 wpm." Do the same for the total. Use plain arithmetic, no model.
4. **Focus for the next take (no model needed).** Script mode has no code-written drills, while Improvise does (`improv.drills`). Add at most three items, each citing a number and naming the mark. Rank marks that diverged in 2 or more takes of the same script first (from `compare.compare_takes`), then the largest divergence in this take. If everything met its mark, say so and list nothing. Test the cap, the ranking and the wording.
5. **Accessibility.**
   - Status is currently shown by color only. Add a glyph to every status chip: met ✓, close ~, diverged ✗, not measured –.
   - Tooltips (`data-tip`) only appear on hover. Make chips focusable, show the tip on focus, and let a click pin it open. Clicking still plays the audio (decide how to combine the two and record the decision).
   - Use `aria-live` for status messages.
6. **Analysis progress.** Replace the single "Analyzing…" message with stages: decoding → transcribing → aligning → definition check. Prefer a small job/poll design over adding WebSockets. Keep the existing synchronous endpoints working for the tests, or migrate the tests.

## M11: Practice loop

1. **Line drill.**
   - From the report, the **Drill** button on a `[KEY]` line or a section records just that line or section.
   - Judge it against the median wpm of the **parent full take**, because a one-line take has no median of its own.
   - Store the drill as a take linked to its parent (`drill_of`, plus the line or section range) and show it under its parent in Takes.
   - Show the result inline: e.g. "This try: 18% slower than your median from the full take; pause after 0.9 s: met".
   - Record the median-source decision in `DECISIONS.md` and test it.
2. **A/B playback across takes.** In the comparison card (`frontend/src/takes.ts`), each cell gets a small play button that plays that take's audio at that mark: the line start for KEY lines, the pause window for pauses. Switching between takes must not leave two audio elements playing.

## M12: Alignment that survives real speakers

People working from slides paraphrase, and Whisper mishears names, so lines drop below 50% coverage and become "not found".

1. **Fuzzy token matching.** A transcript token matches a script token at a high character-similarity ratio (a "bleaching"/"leaching"-type mishearing), with the threshold in Settings. Add year normalization: "2019" matches "twenty nineteen" and "two thousand nineteen".
2. **A `paraphrased` status.** Use it for a line whose verbatim coverage is below the threshold but whose position is bracketed by found neighbours and contains speech. Report its time span and duration; it counts toward section timing. Do not score its rate against the median, because the word counts don't correspond. Say so in the tooltip.
3. **Keep every existing alignment and fixture test passing.** Add tests for mishearings, years, a paraphrased line, and a truly skipped line that must stay "not found".

## M13: Defense Q&A practice

Questions after the talk are where thesis defenses are decided. Build this on top of Improvise.

- **Improvise setup: "Questions about my script".** The model reads the script text only and proposes 5–8 likely audience questions. Each question is tagged (clarification, methods challenge, limitation, implication) and must cite the script line index it concerns; code drops invalid indexes and caps the count.
- **The user picks a question or types their own.** Typing your own works without a key. Generating questions needs a key, otherwise the button is disabled with a one-line reason.
- **The take is an Improvise take** whose topic is the question.
- **Content review (opt-in, as now) adds one criterion: "answered the question".** It needs a verbatim quote from the transcript or the item is dropped. Code checks the quote, the same way the existing content review does.
- **Extend `FakeLLM`** so the UI can be exercised.
- **Tests:** validation, caps, the dropped-quote path, and the no-key behaviour.

## M14: Script import, portable settings, export, and evidence tooling

1. **PowerPoint speaker notes import.** On the Script tab, an "Import from PowerPoint notes" button uploads a `.pptx`. The server extracts each slide's title and notes (`python-pptx` is pure Python, so justify it in `DECISIONS.md`) and returns a script with a `## Slide N: title` section per slide and the notes as lines. Slides without notes get a `<!-- no notes -->` placeholder. Budgets are left empty for the user to fill. Test it with a small `.pptx` generated in the test.
2. **Settings carried in the script.** An optional first-line comment like `<!-- take-two: short_pause_s=0.8 key_slower_pct=15 -->` overrides the global settings for that script. Validate it with `Settings` and reject unknown keys with a clear message. The report and the Settings dialog show which values came from the script. The parser already blanks comments, so line numbers stay stable. Test the precedence and the validation errors.
3. **Export the report** as one self-contained HTML file (inline CSS, audio embedded as a data URI, tooltip text visible) for sharing with an advisor. It must open offline. Estimate the size and warn if it is over ~20 MB.
4. **Take management.**
   - Rename a take's label.
   - Delete a take, with a confirm dialog that names the take and says the audio will be removed from disk.
   - Export a take's folder as a zip.
   - Export "my mark outcomes as CSV" (statuses and numbers only, no audio or transcript) for a small user study.
5. **Evaluation harness** in `eval/`, written so Sophie can add real recordings later:
   - `eval/README.md` explains how to record, and how to label pause regions and line boundaries in Audacity (label tracks exported as `labels.txt`).
   - `uv run python -m eval.run` reports per recording and in aggregate: pause-length error, line start/end error, and agreement between the app's mark statuses and human statuses. It writes `eval/RESULTS.md`.
   - Convert the synthetic fixture's ground truth into the same format, so the harness runs end to end today. Its results are the only ones you may write down.
   - Add `eval/retest.py`: given several takes of the same script, report the spread of median wpm and of each pause measurement. This is the noise floor.
   - Write no numbers you did not compute.
6. **Automated browser test of the recording path.** Use Chrome's `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<fixture.wav>` with Playwright, as a dev-only dependency (Python or Node, your choice; justify it). Record → stop → report renders, in both script mode and Improvise. Mark the test as slow/opt-in, and move these items from "checked manually only" to "verified automatically" in `TESTING.md`.
7. **Small cleanups.**
   - Replace the deprecated `@app.on_event("startup")` with a lifespan handler.
   - Add dark mode: the colors are already CSS variables, so add `prefers-color-scheme: dark`.
   - Add a 60-second first-run walkthrough on the Script tab that marks two lines of the sample. It can be dismissed and is remembered in localStorage.

---

## When you finish (or stop)

Report:

- each milestone completed, with its commit hash;
- anything you skipped and why;
- any design decision where a product rule pushed you away from the literal task;
- what still needs Sophie:
  - an `ANTHROPIC_API_KEY` run of every LLM feature;
  - real labelled recordings for `eval/`;
  - a user study;
  - the `PITCH.md` TODOs;
  - a git remote.
