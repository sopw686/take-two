# Demo: the speech about Take Two (recommended)

`demo_speech.md` is a two-minute talk about Take Two, marked up with Take Two's own marks. I perform it into the app, and then the report shows how I did on it. So the pitch and the demo are the same thing.

## Before the demo

1. Run `.\run.ps1`, open http://127.0.0.1:8765, and paste `demo_speech.md` into the Script tab.
2. Do one practice take and adjust the section time budgets to fit my actual pace.
3. Record a backup take with the planned mistakes below and leave it in Takes, in case the live one fails.
4. Set the teleprompter text size (A−/A+) and close any other tabs using the microphone.

## Planned mistakes

I deliver the speech normally except in two places, so the report has something to flag:

1. I rush the line "A coach that rewards even pace cannot tell a deliberate pause from dead air" and skip the long pause after it. That gets the line about missed pauses flagged for a missed pause.
2. I skip the short pause in "right now is marked up, / and Take Two is listening".

Everything else, including both defined terms and the other two key lines, should come out met.

## Live demo (about 3½ minutes)

- **0:00, perform the speech (about 2:10).** I record from the Rehearse tab and read from the teleprompter. The highlight follows my planned timing, not my voice, so if I get ahead or behind I nudge it with the arrow keys or a clicker.
- **2:10, while it analyzes:** "That was the pitch. Now here's how I did against my own marks."
- **2:20, the rushed line.** Hover its KEY mark: faster than my median and no pause after. Click it to play it back.
- **2:35, pauses.** Hover the skipped short pause and show the measured silence next to the 0.7 s target, then a long pause that was met. The timeline at the top shows where each measurement came from.
- **2:50, definitions and timing.** The "voice activity detector" mark shows the quote where I defined it. The section bars show time against budget, and how many words to cut if a section ran over.
- **3:05, Focus for the next take.** The app picks up to three marks to work on next time, from the numbers alone.
- **Optional, 30 s: drill it.** Click **Drill** on the rushed `[KEY]` line, say just that line again, slowly, with the pause, and stop. The result appears under the line: "This try: …% slower than your median from the full take; pause after … s: met your mark." It is compared with the full take's median because one line has none of its own.
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
- **Microphone is blocked:** open the backup take, or click Load example take and switch to the coral demo below. Mention that the example uses a synthetic voice.
- **Transcription is slow:** restart with `TAKE_TWO_STT_MODEL=base.en`.

---

# Alternate demo: coral reef sample (3–4 minutes)

Before the demo: run `.\run.ps1`, open http://127.0.0.1:8765, load the sample script, and record one take in which you **rush the first `[KEY]` line in Results**, skip the `/` in "deploy shading, to pause tourism, / and to collect", never explain "degree heating weeks", and talk through Methods slowly enough to run it over 0:50. Keep that take open on the Report tab. (If you cannot record live, click **Load example take** on the Report or Takes tab: a synthetic-voice take of the fixture script, built to show the same four things, analyzed instantly with no microphone and no speech model. It is labelled "Example take (synthetic voice)"; say so on stage.)

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

Script tab. Click **Clear**, paste an unmarked paragraph or two (any talk), click **Suggest marks…**, pick *Persuasive / land the main finding*, Suggest.

> "If you don't know how to mark a script yet, you describe what you want the talk to do and get a handful of proposed marks, each with a reason. They're dashed: nothing is applied until I accept it."

Hover two reasons, read one aloud, accept it. Reject one. Click **Apply**.

> "Code enforces restraint: at most one key line per section, about one pause per forty words. Over-marking would just recreate the generic advice we're trying to escape. And the honesty line stays on screen: marks can check pace and pauses; whether the take *sounded* moving is my call."

## 3:15 – Close

Rehearse tab: the script is on screen as a teleprompter, marks drawn in.

> "Then I rehearse against the marks I chose, reading from my own marked script. Audio stays on this machine; the banner says so. The targets are mine, the conventions are an opt-in preset, and the report tells me where I diverged from my own intent, line by line."

Stop.

## If something goes wrong

- Transcription slow: `TAKE_TWO_STT_MODEL=base.en` and restart.
- Microphone blocked: use the upload path with a phone recording, or **Load example take** (no microphone, no speech model, labelled as a synthetic voice).
- Analysis failed after a take: the recording is not lost. Click **Retry** (it re-runs from the copy saved on disk) or **Download recording**. The take also stays in Takes as "Not analyzed" with Retry and Delete.
- Fresh browser on the demo laptop: the Report tab opens the newest finished take on disk, so it never starts on "No take yet" if you recorded earlier.
- No API key: the Suggest button is disabled with a one-line note; everything else works. Say so and skip to Rehearse.
