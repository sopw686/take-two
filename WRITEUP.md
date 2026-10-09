# Take Two

Take Two is a rehearsal coach for science talks. You mark up your script with what you're going for (slow down here, pause there, define this term), rehearse out loud, and it shows you where your delivery matched those marks and where it didn't.

## The problem

Tools like PowerPoint's Speaker Coach and Yoodli compare everyone to the same idea of a good speaker: steady pace, few filler words, varied pitch. They don't know anything about your talk, so they can't tell a deliberate pause after your main result from just losing your place. The mistakes that hurt science talks are usually more specific: rushing the sentence with the finding in it, using jargon nobody knows, or letting methods run long until the conclusion gets squeezed.

## Who it's for

Grad students and researchers preparing conference talks, thesis defenses, or three-minute-thesis pitches. Most rehearse alone, many are nervous or presenting in a second language, and nearly all have a strict time limit.

## Why voice

What Take Two checks only exists in how you say things: pace, pauses, timing. A transcript loses all of it. It's also hard to notice yourself while you're talking, because you're reading, maybe holding a clicker, and focused on the words. So the app does the listening during the take. Marking up a script and reviewing results are easier with a keyboard and screen, so those parts stay that way.

## How it works

You add a few marks to the script: a time budget per section, `[KEY]` for lines to slow down on, `/` and `//` for short and long pauses, and `[DEFINE: term]` for jargon. You rehearse from a teleprompter view. Afterwards you get your script back with each mark labelled met, close, or diverged, the actual measurement (like "19% faster than your median"), and a click to hear that moment. There's no overall score. An Improvise mode handles unscripted speaking, tracking pace, filler words and hedging against ranges you set.

## How it's built

FastAPI and TypeScript, running locally. faster-whisper transcribes with word timestamps, and Silero's voice activity detector measures pauses straight from the audio. Pace is compared to your own median for that take, not a fixed target. Audio stays on your computer unless you add a cloud key. There are 133 unit tests, plus a synthetic recording with known pauses and speed changes that runs through the full pipeline.

## AI tools

I built it with Claude Code, in milestones, from a spec and product rules I wrote first (commits M1 to M10). In the app, Whisper and Silero handle audio. Claude handles optional features: suggesting marks, checking whether jargon was defined, coaching notes, and Improvise content feedback. It only sees text and numbers, never audio, and the code checks its output, for example dropping any quote that isn't actually in the transcript. These features have only been tested against a mocked model so far, so a real API run is next.

## What's next

Practicing single lines, handling paraphrasing and misheard names, Q&A practice with questions generated from your script, importing PowerPoint speaker notes, and testing with real students.
