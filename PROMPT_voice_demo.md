# Take Two: "any speaker" reframe, Hear It, spoken examiner (M15–M17)

You are continuing work on **Take Two**, a local rehearsal coach, in this repository (Windows 11, PowerShell, `uv`, Node 18+). The app works and its tests pass. Three jobs, in this order. Finish each completely (tests, build, browser check, docs, commit) before starting the next. M17 depends on the `Speaker` interface from M16, so do not start it until M16 is committed.

- **M15: Reframe.** Take Two is no longer "a coach for science talks". It is a rehearsal coach for **anyone who needs to land an idea out loud**: a conference talk, a thesis defense, a wedding toast, a eulogy, a startup pitch, a poetry slam piece. Science talks become one example among several.
- **M16: Hear It.** An AI voice coach demonstrates a single line two ways: as the user marked it, and as the coach would deliver it (the coach decides which word to stress, which to slow down, where the voice rises or falls, where to pause, and how the hard words are pronounced). It also tells the user, from measured recognizer confidence, which words may not have come across clearly. The user hears it, then records their own try of that line and gets measured against the same marks.
- **M17: Spoken examiner.** A hands-free Q&A session: the AI examiner asks questions aloud, the speaker answers aloud, and the examiner asks one short spoken follow-up. This is the milestone that makes Take Two a voice agent in the conversational sense, so the demo should lead with it.

## Read first

1. `README.md`, `DECISIONS.md`, `TESTING.md`, `DEMO.md`, `WRITEUP.md`, `PITCH.md`. They hold the design rules and the reasoning behind them.
2. Backend: `take_two/marks.py` (mark parsing), `config.py` (Settings), `analysis.py`, `prosody.py` (pitch/loudness), `emphasis.py`, `suggest.py`, `questions.py`, `app.py`. Frontend: `frontend/src/` (vanilla TypeScript, `h()` helper in `dom.ts`; see `drill.ts`, `prompter.ts`, `player.ts`, `editor.ts`).
3. Baseline: `uv run pytest` and `cd frontend; npm run build` must both pass before you change anything.

## Non-negotiable product rules (unchanged, and they apply to everything below)

- **No score, no grades, no streaks.** Wording stays "met / close to / diverged from *your* mark". New text must pass the existing no-grading-words tests.
- **The user sets the targets.** The demo is built from the user's marks first. Anything that adds a target goes in `config.Settings` with a default and bounds, shows in the Settings dialog, and travels with the request.
- **Universal standards are opt-in.** The product's whole premise is that there is no single correct way to speak. "Good presentation principles" therefore enter only as an opt-in, user-picked **register** (see M16), off by default, never applied silently, never used to judge a take.
- **Audio stays on the machine by default.** The user's recorded audio goes nowhere new. Synthesising a demo needs only script *text*; if a provider other than the browser's built-in voice receives that text, it sits behind the same consent banner as cloud speech-to-text, and the banner says exactly what is sent (script text, no audio).
- **A language model reads only text and measured numbers.** Code validates all model output (indexes checked, quotes verbatim, results capped). Without `ANTHROPIC_API_KEY` model-backed features are disabled with a one-line reason. Never silently substitute a heuristic. `TAKE_TWO_LLM=fake` stays a labelled stand-in.
- **Measure, don't guess.** Do not present an unmeasured thing as verified. A cue the app can check (pause length, line rate vs the user's median, emphasis loudness/pitch via `prosody.py`) is labelled "checked in your report". A cue it cannot check (e.g. rising intonation if pitch is unavailable) is labelled "demonstration only, not checked".
- **No clinical or therapeutic claims.** No claims that a style is proven to persuade. Do not cite studies you have not read.
- **Match the codebase.** Vanilla TypeScript, no UI framework, no new runtime frontend dependencies. A small pure-Python backend dependency is acceptable if justified in `DECISIONS.md`. Match existing comment density and naming.

## Working rules

- Unit tests for every backend behaviour (hand-built inputs, mocked LLM/TTS). Keep `uv run pytest` and `npm run build` green.
- Check every UI change in the browser with the preview tools (`.claude/launch.json` config `take-two`, port 8765; if the user's own server is on 8765, use it). The automated browser has **no microphone and may have no speech voices**: test the cue plan and the UI state from the DOM, and say plainly in `TESTING.md` that audible output was not heard by you. Rebuild the frontend first (FastAPI serves `frontend/dist`).
- Update docs per milestone: `DECISIONS.md` (decided / considered / why), `TESTING.md` (what is verified automatically vs by hand), `README.md`, `DEMO.md` if the flow changes. Do **not** edit the `TODO (Sophie)` parts of `PITCH.md`.
- Commit after each milestone (`M15: …`, `M16: …`), never amend, never force, no remote. Leave this file untracked.
- Never fabricate results, user quotes, competitor claims, or "verified" labels. The real Anthropic API has not been called from this machine unless a key is present; keep labelling LLM paths accordingly.
- If a rule conflicts with a task, write down the conflict, pick the option that keeps the rules, report it at the end.

---

## M15: Reframe for any speaker

Goal: someone who writes toasts or slam poems should read the README and think "that's for me", and a scientist should still find everything they had.

1. **Copy.** Rewrite the intro in `README.md`, `WRITEUP.md`, and the non-TODO parts of `PITCH.md` / `DEMO.md`:
   - Lead problem: generic coaches (PowerPoint Speaker Coach, Yoodli, Orai) grade everyone against one idea of a good speaker, but a deliberate pause is the whole point of a toast punchline, a poem's line break, or the sentence a talk exists to deliver. Nobody can hear their own pace while speaking.
   - Name the audiences concretely, in this order of emphasis: technical or academic talks, celebratory speeches, performance poetry / slam, pitches and interviews. One sentence each on what "landing it" means there (e.g. toast: the pause for the room to react; slam: the breath at the line break, the drop before the last line; technical: the key result slowed and followed by silence).
   - Keep the mechanism claims accurate: measured not judged, no score, local by default.
   - Do not invent usage, testimonials, or comparisons that are not in the repo.
2. **App text.** Replace science-specific wording that is user-visible or sent to the model: `take_two/__init__.py` docstring, system prompts in `define.py`, `suggest.py`, `questions.py` (e.g. "science talk", "scientist", "general scientific audience"), UI labels, empty states, tour text. `[DEFINE: term]` becomes "a term your audience may not know" and works for a technical term, a family in-joke a toast must explain, or a reference in a poem. `questions.py` (Q&A) should say audience questions, not only thesis-defense questions. Keep behaviour identical; this is wording. Update any test that pins the old wording.
3. **Examples.** Keep `demo_speech.md` and `sample_script.md`. Add two short scripts using the existing mark syntax, each under 90 seconds: a **toast** (uses `/` for the room's reaction, `//` before the last line, one `[KEY]` line) and a **slam poem** (line breaks as `/`, a long `//` before the turn, emphasis on a few words). Offer them in the Script tab next to the existing sample (a small "Start from an example" picker). Mark these as "written for the demo".
4. Topics: `topics.py` already has Everyday/Stories/Opinions; add a "Toasts & occasions" category with a few prompts. Do not change existing ones.
5. Docs: a `DECISIONS.md` entry saying what changed in the positioning and why `[KEY]`, pauses and `[DEFINE]` generalise without new mechanics.

## M16: Hear It: the voice demonstrates a line

Goal: next to any script line (Script tab, report, drill, prompter) a **Hear it** button speaks that line with the delivery the user's marks call for. The point is a voice agent that *shows* instead of only measuring.

### 1. Cue plan (pure backend, no audio, fully testable)

Add `take_two/delivery.py` with a function that turns one script line + the user's Settings + (optionally) the user's measured median rate into a **cue plan**: an ordered list of segments, each `{text, rate, pitch, volume, pause_after_s, checked: bool, source}`.

Derive it **deterministically from the marks**, the same way analysis reads them, so the demo and the report can never disagree:
- `word / word` → split there; `pause_after_s = short_pause_s` (default 0.7). `//` → `long_pause_s`. These are the user's thresholds from Settings.
- `[KEY]` → rate = the user's median line rate × (1 − `key_slower_pct`/100); `pause_after_s = key_pause_after_s`. If there is no measured median (no take yet), use a labelled default speaking rate and say so ("no take yet: using a typical 150 wpm baseline"). Never present the baseline as the user's own rate.
- `*word*` → the word becomes its own segment with raised volume and a pitch lift. Checked only when `emphasis_enabled` and pitch/loudness are measurable.
- This is the **"As I marked it"** version. It uses only what the user wrote, and a line with no marks is spoken plainly with a note "no marks on this line".

The agent's job is the second version, **"Coach's version"**: it *invents* a full delivery for the line (see section 2) on top of the user's marks. The user's written marks always win; the coach fills everything else. Hear-it offers both and lets the user switch between them, so they can hear the difference between what they planned and what the coach would do.

Each segment carries `source` (`mark:/`, `mark:KEY`, `mark:emphasis`, `coach`, `register:<name>`) and `checked` so the UI can show *why* each cue is there and whether the report will check it.

Extend the segment so it can express a real delivery, not just pauses: per-word or per-phrase `rate`, `pitch` shift and `contour` (`rise` / `fall` / `hold` / `none`), `volume`, `stress`, a `slow_word` flag (stretch one word, e.g. rate 0.6), and an optional `say_as` pronunciation (respelling or IPA).

### 2. Coach's version: the agent invents the delivery

This is the voice-agent core. For a chosen line (or a whole section), the coach decides *how it should be said* and then says it. It chooses, and explains in one short reason each:
- which word(s) to stress, and how (louder, higher, held);
- which word to **slow down** (e.g. the number, the name, the turn of the poem) and by how much;
- the pitch contour of each phrase: a falling end on a claim so it sounds finished, a rise on an open question or a suspended thought, a drop in pitch and volume for the sincere line;
- extra pauses (where the user wrote none) and where a pause the user wrote should be longer or shorter;
- the overall pace of the line relative to the user's median.

Model-backed when `ANTHROPIC_API_KEY` is set: send the line, its section, the user's marks, the register (below), and the user's measured median rate; get structured JSON back. Code validates it as `suggest.py` does: segment text must be a verbatim span of the line, numeric values clamped to safe ranges, count capped, every item has a reason, anything invalid is dropped. Without a key, fall back to the register heuristics below, **labelled as heuristic, not as the coach's model** (do not pass heuristic output off as model output). `TAKE_TWO_LLM=fake` stays a labelled stand-in.

Rules:
- Coach-invented cues are **suggestions, never measured facts**. Label them "coach's suggestion" in the UI and the plan text. Measured things stay labelled "checked in your report".
- The user's written marks are never overridden, only added to.
- An **Accept into script** button turns the suggestions that map to existing marks (`/`, `//`, `[KEY]`, `*word*`) into real marks, so the next report checks them. Cues with no mark equivalent (contour, a stretched word, pitch) are kept as "demonstration only, not checked" unless they can be measured with `prosody.py` (loudness and pitch of a word vs its line already are, for emphasis).
- A **register** (conversational/technical, celebratory, slam, pitch) is picked by the user and tells the coach what "landing it" means for this speech. Registers are not a universal standard: they are a user-chosen starting point and are off until picked.

Register heuristics (the no-key fallback, and the guidance the model prompt includes). Presets are data, editable in Settings, and each rule is a plain, defensible heuristic:

- **Conversational / technical talk:** chunk into phrases of roughly 3–5 seconds; slow down for new or dense information (numbers, definitions, the main result); pause before the point and after it; one or two stressed words per sentence at most; a falling end on statements, so a claim sounds finished instead of like a question.
- **Celebratory (toast, tribute):** warmth over speed: slightly slower overall; a pause after the punchline for the room to react; lower and slower for the sincere line near the end; the last line is slowest with a clear falling end, then silence.
- **Performance poetry / slam:** the line break is a breath; build pace and volume toward the turn, a drop in pace or volume just before it; deliberate contrast (fast/loud against slow/quiet); end lines on a held or falling note; the last line gets the longest pause.
- **Pitch / interview:** lead with the claim; slow down on the number and the ask; no trailing off.

Each suggestion shows its one-line reason ("pause before the result so it lands"). No claim that it is "correct".

### 2b. Pronunciation: the coach says the hard words correctly

- **Flag words worth checking.** From the script text, find proper names, foreign or loanwords, acronyms, and technical or rare terms (model-backed when a key is present; otherwise a heuristic using capitalisation, a word-frequency list, and a pronunciation dictionary such as CMUdict if you can justify the dependency in `DECISIONS.md`).
- **Propose a pronunciation** for each: a plain respelling ("KOH-ral", "ZHAH-vay") and IPA where useful, with syllable stress. Label it "proposed pronunciation: confirm it". A model can be wrong about names; the UI must say so and let the user edit it. Never state a pronunciation as authoritative.
- **User-owned lexicon.** Let the user confirm or edit a pronunciation and store it with the script (a `[SAY: word = respelling]` mark, parsed in `marks.py` and ignored by alignment, or a lexicon block; choose and document it). Hear-it uses the lexicon (`say_as`); SSML uses `<phoneme>`; the browser voice uses the respelling text.
- **Hear one word.** Every flagged word has a button that says it slowly, syllable by syllable, then at normal speed.

### 2c. Clarity: telling the user which words were not clear (measured)

The app already has per-word recognizer confidence (`Word.prob` in `take_two/stt/base.py`) and misheard-word matches from the alignment (`fuzzy` / `heard` in `align.py`). Use them; do not guess from audio.

- In the report, add **"Words that may not have been clear"**: script words where the recognizer was unsure (probability below a user-set threshold in Settings) or heard a different word (show what it heard: "you said 'bleaching', it heard 'leaching'"), each with the number and a timestamp, the ordinary click-to-play of that moment, **Hear it** (the correct pronunciation, slowly), and **Drill this word** (record just that word or phrase).
- Wording is strictly measured and kind: "the recognizer was unsure of these words (confidence 0.41)". Never "poor enunciation", never a grade, never a statement about accent. A recognizer can fail on an accent, a noisy microphone, a rare word or a quiet moment, so say so in one line, and let the user dismiss a word as "I said it fine" (remembered per word).
- No clinical or speech-therapy claims. This is about being understood by a listener, not diagnosing anything.
- Skip words the recognizer is unsure of only because they are inside a correctly matched span at high confidence; the threshold and the minimum count live in Settings.

### 3. Speech engine (frontend, interface + two providers)

Define a small `Speaker` interface in `frontend/src/` (`speak(plan): Promise<void>`, `stop()`, `available(): {ok, reason}`), so providers are swappable.

- **Default: browser `speechSynthesis`.** Local, no key, no network, audio never leaves the machine. Play each segment as its own utterance with `rate`/`pitch`/`volume`, and implement `pause_after_s` as a timed gap between utterances (not by relying on punctuation). Let the user pick the voice from `speechSynthesis.getVoices()` (remember it). Handle `voiceschanged`, a missing voice list, and cancel-on-click. Be honest in the UI help: browser voices give coarse control of pace and pitch and none of tone, so a rising or falling end is approximated by a short pitch shift on the final segment.
- **Optional: an SSML-capable provider** (`<break time>`, `<prosody rate pitch>`, `<emphasis>`), for better intonation. Pick one (Azure Speech, Amazon Polly, or Google Cloud TTS), justify the choice in `DECISIONS.md`, implement it server-side behind an endpoint, and gate it behind the cloud consent banner and an env var for the key. It receives script text only. Compile the cue plan to SSML in a pure, unit-tested function. Without a key it is disabled with a one-line reason; no silent fallback to a different provider without telling the user which voice is playing. Include a `fake` provider (labelled) so the UI and tests run offline.

The synthesised audio is **not** the user's voice and is never stored in the take folder or mixed into analysis. Label it in the UI: "Synthetic demonstration of your marks. It shows one way to do it, not the way."

### 4. UI

- A **Hear it** button on each script line in the Script tab (preview of the marks you wrote), the report's key-line rows, and drill: the demo for the line currently being drilled.
- A two-way switch on the button, **As I marked it / Coach's version**, so the user hears their plan and the coach's invented delivery back to back.
- A small panel under the button lists the cue plan in words: "slower: 22% below your median (150 wpm → 117)", "0.7 s pause after 'result' (your short-pause setting)", "'sequence' stressed (checked in report)". Each cue shows `checked` vs "demonstration only".
- **Try it** next to **Hear it**: starts the existing line drill (see `drill.ts`) so the user records their own version and the report judges it against the same marks and the median of the take it came from. This closes the loop: hear → say → measured.
- Keyboard accessible; the spoken text is also on screen; a Stop control; respect `prefers-reduced-motion`. No autoplay.
- If no voice is available, show the cue plan in text anyway and say why audio is unavailable.

### 5. Stretch, in this order, only if everything above is finished and green

1. **Spoken debrief.** After a take, the coach reads the "Focus for the next take" items aloud, one at a time, each followed by Hear it for the line in question. The text comes from the existing app-written focus items (measured numbers), not from a model.
Keep it behind a toggle. Do not add it if it is not finished. (Spoken Q&A is now its own milestone, M17.)

### 6. Tests and docs

- Unit tests: cue plan from each mark type; `/` and `//` use the user's thresholds; `[KEY]` with and without a measured median (baseline labelled); "As I marked it" on an unmarked line is plain; "Coach's version" adds cues and never overrides or removes a written mark; heuristic fallback is labelled as heuristic; pronunciation lexicon (`[SAY: …]`) parses, round-trips, and reaches the plan as `say_as`; the clarity list contains exactly the words below the threshold or fuzzy-matched, with their numbers, and omits dismissed words; the clarity text contains no grading or accent words; SSML compilation escapes text and bounds values; model-proposed cues dropped when text is not verbatim; provider disabled with a reason when the key is missing.
- Frontend: the only logic worth a test without a browser is the cue-plan-to-utterances scheduling; keep it a pure function and test it.
- Browser check: the buttons render, the cue plan text is right for the toast and slam examples, Stop works, and a missing voice list degrades to text. State in `TESTING.md` that audible quality was not judged by you.
- Docs: README (a "Hear it" section and a register table), DECISIONS (why browser voice by default; why registers are opt-in and do not conflict with "no universal standard"; why checked vs demonstration-only; the SSML provider choice), TESTING, DEMO (add a 20-second beat: hear the toast's punchline pause, try it, see "met your mark").

## M17: Spoken examiner: a hands-free Q&A session

Goal: the strongest "why voice" moment in the product. A defense, pitch or interview Q&A is oral, unscripted and under time pressure, and the speaker's hands and eyes are on their notes. Typing answers trains the wrong skill. Here an AI examiner **asks aloud, listens to the answer, and asks a short follow-up aloud**, with no keyboard needed once it starts. M13 already produces the questions and measures an answer as an Improvise take; this milestone makes it a spoken conversation.

### Session flow

1. **Set up (keyboard is fine here):** choose the question source (the M13 generated questions, typed questions, or a mix), how many (3–6), thinking time before each answer, and the maximum answer length. Settings live in `config.Settings` with defaults and bounds.
2. **Run (hands-free):** for each question the examiner speaks it with the `Speaker` from M16 (browser voice by default; examiner voice is a separate picker from the coach voice). When the speech ends, a short cue tone plays and the thinking time counts down visibly, then recording starts automatically. **Never record while the examiner is speaking** (the microphone would capture the synthetic voice; start the recorder only after `speak()` resolves).
3. **End of answer:** stop when the speaker has been silent longer than a user-set threshold (default about 3 s) after speaking, or at the maximum length, or when they press Space or click Done. Implement the silence detector as a pure, tested function over level samples; do not depend on a new library.
4. **Analyse:** each answer is submitted as an ordinary Improvise take whose topic is the question (reuse the M13 path and the Improvise report). Nothing about measurement changes.
5. **Follow-up:** after analysis, the examiner may speak **one** follow-up per question (at most one, so a session cannot run away). The follow-up is written by a model that reads **only the answer's transcript text and the measured numbers** (never audio), and must be answerable from what the speaker just said ("You said the effect doubled: compared with what?"). Code validates: it must be one short question, any quoted phrase must appear verbatim in the transcript or the script, and it is dropped if it does not. Without `ANTHROPIC_API_KEY` there are no follow-ups: the session just moves to the next question, and the UI says so in one line (as `questions.py` does; no heuristic stand-in). `TAKE_TWO_LLM=fake` stays a labelled stand-in.
6. **Skip or repeat:** the keyboard always works: Space to finish an answer early, `R` to hear the question again, `S` to skip, Esc to end the session. These are shown on screen. No spoken-command recognition is required, so the session does not depend on a new speech feature.
7. **Close:** the examiner says a short closing line built from the measured results (app-written text, no model), for example "You answered four questions. Two stayed within your pace band. The longest hesitation before an answer was 6 seconds." The same text is on screen with a link to each answer's report. No score, no grade, no streak. Wording follows the Improvise convention: within / close to / outside **your** band.

### Rules

- The examiner never judges how an answer "sounded" and never claims to hear tone. It reacts to words (transcript) and measured numbers only.
- Answers are saved as ordinary takes, so the existing Takes list, compare, drill and export work on them. A session is a labelled group of takes; do not invent a new storage format if the take label or a session id in the take folder is enough, and justify the choice in `DECISIONS.md`.
- If the browser has no speech voices or no microphone permission, say exactly what is missing and offer the typed-question path unchanged.
- A session that is interrupted keeps the answers already recorded (reuse the M8 failed-take recovery for an answer whose analysis fails).
- Keyboard-accessible, screen-reader labels on state changes ("Question 2 of 4. Listening."), no autoplay on page load, a visible Stop at all times.

### Tests and checks

- Unit tests: the session state machine as a pure function (idle → asking → thinking → recording → analyzing → follow-up or next → done, plus skip/repeat/abort); the silence detector (silence after speech stops; no stop before any speech; max-length stop); follow-up validation (non-verbatim quote dropped, multi-question output dropped, more than one per question dropped, no key → none); the closing line is built from numbers and contains no grading words.
- Browser check: the automated browser has no microphone. Use Chrome's fake audio capture if M14 set it up, otherwise the upload path for each answer, and say in `TESTING.md` exactly what that proves (state transitions, saved takes, closing text) and what it does not (that the microphone is not fed back the examiner's voice, how the voice sounds). Do not claim you heard it.
- Docs: README (a "Spoken examiner" section), DECISIONS (why start recording only after speech ends; why one follow-up; why keyboard control rather than voice commands; why no heuristic follow-ups), TESTING, DEMO (this is the 30-second beat that shows why voice: the speaker's hands are on their notes while they answer out loud).

## Report at the end

List what is finished, what is checked only by hand, which cues are measured vs demonstration only, any rule conflicts and how you resolved them, and anything you did not get to.
