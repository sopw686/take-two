# Demo script (3–4 minutes)

Before the demo: run `.\run.ps1`, open http://127.0.0.1:8765, load the sample script, and record one take in which you **rush the first `[KEY]` line in Results**, skip the `/` in "deploy shading, to pause tourism, / and to collect", never explain "degree heating weeks", and talk through Methods slowly enough to run it over 0:50. Keep that take open on the Report tab. (If you cannot record live, upload `tests/fixtures/fixture.wav` with `tests/fixtures/fixture_script.md` as the script; it was built to show the same four things.)

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

Rehearse tab.

> "Then I rehearse against the marks I chose. Audio stays on this machine; the banner says so. The targets are mine, the conventions are an opt-in preset, and the report tells me where I diverged from my own intent, line by line."

Stop.

## If something goes wrong

- Transcription slow: `MARKED_STT_MODEL=base.en` and restart.
- Microphone blocked: use the upload path with a phone recording.
- No API key: the Suggest button is disabled with a one-line note; everything else works. Say so and skip to Rehearse.
