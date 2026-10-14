# Demo: the speech about Take Two (recommended)

This is a demo speech about the app. I give the talk, and then the report shows how I did on it, compared to how I wanted to do. /



## Before the demo

1. Keep the takes outside OneDrive. The repo sits in a OneDrive folder, so the default `takes\` is synced and every recording is uploaded, which would make "the audio never left this laptop" false. Start with `.\run.ps1 -TakesDir "$env:LOCALAPPDATA\TakeTwo\takes"` (same thing without the parameter: `$env:TAKE_TWO_TAKES_DIR = "$env:LOCALAPPDATA\TakeTwo\takes"; .\run.ps1`). Open http://127.0.0.1:8765 and load the speech on the Script tab (**Start from an example** → *The demo speech*, or paste `demo_speech.md`).
2. Do one practice take and adjust the section time budgets to fit my actual pace.
3. Record a backup take with the planned mistakes below and leave it in Takes, in case the live one fails. A backup recorded earlier under the repo's `takes\` is not in the new folder: copy its folder into `$env:LOCALAPPDATA\TakeTwo\takes`.
4. Takes tab: delete any development leftovers, so the list holds only the backup take and the toast take (below).
5. Voices: in the Hear it panel and in the Spoken examiner setup, check that each voice picker shows a voice under "Natural voices (on this computer)" with no "downloading" note (`models\` must hold both Kokoro files).
6. Warm up Hear it: open the toast take's report and play **Hear it** on its `[KEY]` line once as marked and once as the **Coach's version**. The first render takes a few seconds; after that both are cached in the server's memory, so don't restart the server before going on stage.
7. Pre-download the faster speech model for the "Transcription is slow" fallback (only `small.en` is cached, and the venue may have no internet): `uv run python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"`.
8. Set the teleprompter text size (A−/A+) and close any other tabs using the microphone.
9. If the thresholds were tuned on another machine, put them in the script's first line (for example `<!-- take-two: short_pause_s=0.8 -->`) so the demo laptop measures the same way. On a fresh browser, dismiss the one-minute tour on the Script tab before going on stage.

## Planned mistakes

I deliver the speech normally except in two places, so the report has something to flag:

1. I rush the line "A coach that rewards even pace cannot tell a deliberate pause from dead air" and skip the long pause after it. That flags its `KEY` chip (faster than my median, no pause after) and the `//` after "dead air".
2. I skip the short pause in "right now is marked up, / and Take Two is listening".

Everything else, including both defined terms and the other two key lines, should come out met.

## Lead with the examiner (60–90 s, before the speech)

This is the beat that shows why voice: a Q&A is oral, unscripted and timed, and the speaker's hands are on their notes. Plan to answer one question (plus its follow-up with a key), not the whole session: each answer is transcribed and measured before the examiner moves on.

- **Before the demo:** Improvise tab → **Spoken examiner**. Type three questions I expect, one per line (the session needs at least three; I answer only the first); or, with an API key, choose *Proposed from my script*. Set thinking time to 3 s, silence to 3 s and the longest answer to 30 s; pick the examiner voice and turn the laptop volume up. Close other tabs that use the microphone.
- **On stage, 0:00:** "After a talk come the questions. Watch my hands." Click **Start the session**, then put both hands on my printed notes and leave them there.
- The examiner asks the first question aloud. A tone, a three-second countdown on screen, and recording starts by itself; "Question 1 of 3. Listening." I answer in about 20 seconds, stop talking, and three seconds later the answer ends by itself and is measured (this takes a few seconds). With a key, the examiner then asks one short follow-up built on my own words; I answer it the same way. Without one, it goes on to the next question.
- **When the "Open its report" link appears under my last answer** (the follow-up's, with a key), press **Esc**. Not before: Esc while I'm still answering discards that answer, and an answer still being measured may be missing from the closing line. Point at the closing line on screen: "You answered 1 question. … The longest hesitation before an answer was … seconds." "No score: it counts what happened. The microphone is never on while the examiner talks, and every answer is a normal take I can open."
- **If the room is noisy:** the silence never comes, so press **Space** as soon as I finish each answer (otherwise it records until the 30 s limit).

The speech demo below then starts at about 1:30; the times in it are counted from its own start.

## Live demo (about 3½ minutes)

- **0:00, perform the speech (about 2:10).** I record from the Rehearse tab and read from the teleprompter. The highlight follows my planned timing, not my voice, so if I get ahead or behind I nudge it with the arrow keys or a clicker.
- **2:10, while it analyzes:** "That was the pitch. Now here's how I did against my own marks."
- **2:20, the rushed line.** Hover its KEY mark: faster than my median and no pause after. Click it to play it back.
- **2:35, pauses.** Hover the skipped short pause and show the measured silence next to my target (0.7 s unless the script's settings line changed it), then a long pause that was met. The timeline at the top shows where each measurement came from.
- **2:50, definitions and timing.** The "voice activity detector" mark shows the quote where I defined it. The section bars show time against budget, and how many words to cut if a section ran over.
- **3:05, Focus for the next take.** The app picks up to three marks to work on next time, from the numbers alone.
- **Optional, 30 s: drill it.** Click **Drill** on the rushed `[KEY]` line, click **Record**, say just that line again, slowly, then stay silent for a full two seconds before clicking **Stop and compare**: the drill keeps the `//` after "dead air", and both pauses are measured to the end of the recording. The result appears under the line in two sentences: "This try: …% slower than your median from the full take; pause after … s: met your mark." and one for the `//` against its 1.5 s mark. It is compared with the full take's median because one line has none of its own.
- **Optional, 20 s: hear it, then try it (the toast).** Before the demo: load the toast (Script tab → **Start from an example**), record one take of it, and set the register to *Celebratory* in Settings. On stage, open that take's report, click **Hear it** on the `[KEY]` line: the voice says the whole line slower than my median, stops for the 1.5 s `//` after "it wasn't", and pauses at the end; the panel lists each of those as "checked in your report". Switch to **Coach's version** and play it again: the end of the sincere line ("to come second") drops lower, quieter and a little slower and ends falling, each cue listed as "coach's suggestion; demonstration only, not checked". (That is the *Celebratory* register's rule set, used without a key; with a key a model writes the cues and they can differ.) Click **Try it**, then **Record**, say the line with the pause, and click **Stop and compare** after the pause: "pause after … s: met your mark." Say it out loud: "That was a synthetic voice showing one way to say it. The pause is my mark, and now it's measured on my voice."
- **Optional, 45 s: the questions after the talk.** Improvise tab → **Questions about my script**. With an API key, **Propose likely questions** lists five to eight tagged questions, each tied to a script line; without one, type a question you expect ("How does it tell a deliberate pause from a hesitation?"). Answer it out loud; the report shows your delivery numbers for the answer, and with **Delivery + content** (needs the API key; without one it is disabled and says so) a quote-backed "Answered the question".
- **Optional, 15 s: send it to an advisor.** Click **Export report**: one HTML file with the recording inside, every number and tooltip printed, click a line to hear it. It opens offline.
- **3:15, close:** "There's no score. Every mark is something I chose, the audio never left this laptop, and the report shows where I drifted from what I meant to do."

If there's extra time, I do a one-minute Improvise round: shuffle a topic, set a 30-second goal, choose Delivery only, talk, and show the pace, filler and hedging results.

## Video (2–3 minutes)

- **0:00–0:15:** one line to camera about what Take Two does.
- **0:15–0:30:** the marked speech in the Script tab.
- **0:30–1:10:** recording the first section, including the rushed line, then cut.
- **1:10–2:30:** the report walkthrough above.
- **2:30–2:50:** the closing line.

Record the screen and microphone together, so the take in the report is the one viewers just heard.

## If something breaks

- **Analysis fails:** the recording is kept. Click Retry, or open the backup take.
- **Microphone is blocked:** open the backup take, or Takes tab → **Load example take** and use the example-take script below (not the coral demo: the example is a different, shorter script). Mention that the example uses a synthetic voice.
- **Transcription is slow:** stop the server and restart with `.\run.ps1 -SttModel base.en` (keep `-TakesDir …` if I started with it), or `$env:TAKE_TWO_STT_MODEL = "base.en"; .\run.ps1`. This needs `base.en` pre-downloaded (Before the demo, step 7); otherwise it needs internet.

## Fallback: the example take (no microphone, about 2 minutes)

Takes tab → **Load example take** (the button is on the Report tab only when there are no takes at all). It is labelled "Example take (synthetic voice)": 33.7 s of a synthetic voice reading a short coral-reef script (`examples/coral/script.md`, not `sample_script.md`), analyzed from a committed transcript, so no microphone and no speech model. Say so first: "This is a synthetic voice, so it tells you nothing about a real speaker; it shows what the report measures."

- **0:00, the key line.** Hover the red `KEY` chip on "The model predicted bleaching three weeks in advance.": "I marked this as the line the talk exists for: say it slower, then pause. It came out 19% faster than this take's own median, 250 against 209 words a minute. The pause after it was taken, so only the rate diverged." Click the line to hear it.
- **0:30, pauses.** The `/` in "twenty years / of": 0.00 s against a 0.7 s mark, missing. The `//` after "advance.": 1.57 s against 1.5 s, met. The `/` in "not random. / They": 0.36 s, short. "A voice-activity detector on the audio measures these, so it's a number, not a feeling."
- **1:00, a term that was explained.** The `DEFINE: degree heating weeks` chip is met, "defined (heuristic)", with the quote "…degree heating weeks, which is the accumulated heat above the summer maximum…". "I asked myself to explain this before relying on it, and the explanation came right with it. Without an API key this is a labelled heuristic; with one, a model reads the transcript text. It never hears the audio."
- **1:20, timing.** The section bars: Methods 0:12 spoken against a 0:06 budget, "about 20 words at your 209 wpm" to cut. Opening and Results are within budget.
- **1:40, Focus for the next take.** The three items: the Methods overrun, the missing `/` and the rushed key line, written from the numbers alone. Then close as in the live demo.

---

# Alternate demo: coral reef sample (3–4 minutes)

Before the demo: run `.\run.ps1 -TakesDir "$env:LOCALAPPDATA\TakeTwo\takes"` (takes outside OneDrive, as above), open http://127.0.0.1:8765, load the sample script, and record one take in which you **rush the first `[KEY]` line in Results**, skip the `/` in "deploy shading, to pause tourism, / and to collect", never explain "degree heating weeks", and talk through Methods slowly enough to run it over 0:50. Keep that take open on the Report tab. The numbers below are what such a take of `sample_script.md` might show; read the real ones off the screen. (If you cannot record live, use the example-take fallback above instead: the example is a different, shorter script and shows different things.)

## 0:00 – The thing generic coaches cannot do

Report tab, already open.

> "This is my own script, and I marked this line `[KEY]`: it's the result the whole talk exists to deliver. I asked myself to slow down here and pause after it."

Hover the red `KEY` chip on *"The model predicted bleaching three weeks in advance…"*.

> "I didn't. 19 % faster than my own median this take. Not faster than some ideal pace: faster than *me*, on the sentence I said mattered most. PowerPoint's coach would have told me my pace was fine, because on average it was."

Click the line; it plays from that moment.

## 0:45 – A pause I asked for and didn't take

Scroll to the `/` chip in "to pause tourism, / and to collect". It is amber or red.

> "I put a short pause here. Measured: 0.2 seconds of silence between 'tourism' and 'and'. The target was 0.7, and I can change that target; it's mine. The number comes from a voice-activity detector on the raw audio, cross-checked with the transcript, so it's a measurement, not a feeling."

Hover the green `//` after the key line: "1.6 s, met your mark."

> "The pause I did take is marked met. No score, no grade. Each mark says met, close, or diverged from what I intended."

## 1:30 – A term I never defined

Point at the `DEFINE: degree heating weeks` chip.

> "I flagged this term as one I must define out loud before I use it. The report says it was first spoken at 1:05 and no definition was found at or before that point; the evidence snippet shows exactly what I said instead. With an API key the check is done by a model reading the transcript text; without one it's a labelled heuristic. The model never hears the audio."

## 2:00 – Methods ate the conclusion

Scroll up to the section bars.

> "Methods had a 0:50 budget and ran 1:12. Results got squeezed. This is the classic science-talk failure, and it's visible before the real talk."

## 2:30 – The novice path

Script tab. Click **Clear**, paste an unmarked paragraph or two (any talk), click **Suggest marks…**, pick *Persuasive / land the main point*, Suggest.

> "If you don't know how to mark a script yet, you describe what you want the talk to do and get a handful of proposed marks, each with a reason. They're dashed: nothing is applied until I accept it."

Hover two reasons, read one aloud, accept it. Reject one. Click **Apply**.

> "Code enforces restraint: at most one key line per section, about one pause per forty words. Over-marking would just recreate the generic advice we're trying to escape. And the honesty line stays on screen: marks can check pace and pauses; whether the take *sounded* moving is my call."

## 3:15 – Close

Rehearse tab: the script is on screen as a teleprompter, marks drawn in.

> "Then I rehearse against the marks I chose, reading from my own marked script. Audio stays on this machine; the banner says so. The targets are mine, the conventions are an opt-in preset, and the report tells me where I diverged from my own intent, line by line."

Stop.

## If something goes wrong

- Transcription slow: restart with `.\run.ps1 -SttModel base.en` (or `$env:TAKE_TWO_STT_MODEL = "base.en"; .\run.ps1`); `base.en` must be downloaded beforehand (see the first demo's Before the demo).
- Microphone blocked: use the upload path with a phone recording, or Takes tab → **Load example take** with the example-take fallback above (no microphone, no speech model, labelled as a synthetic voice).
- Analysis failed after a take: the recording is not lost. Click **Retry** (it re-runs from the copy saved on disk) or **Download recording**. The take also stays in Takes as "Not analyzed" with Retry and Delete.
- Fresh browser on the demo laptop: the Report tab opens the newest finished take on disk, so it never starts on "No take yet" if you recorded earlier.
- No API key: the Suggest button is disabled with a one-line note; everything else works. Say so and skip to Rehearse.
