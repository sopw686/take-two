# Pitch outline: Marked

> TODO (Sophie): opening line. One sentence about the moment at a slam when a marked-up page became a performance.

## The problem

Every speech coach on the market grades you against one universal standard: even pace, no filler, don't be monotone. PowerPoint's Speaker Coach, Yoodli, Orai all do it. The standard is not wrong, it is just not *yours*. None of these tools know what you meant to do. They cannot tell a deliberate pause from dead air, or the sentence your whole talk exists to deliver from a transition. So the feedback a scientist gets on a thesis defense rehearsal is the same feedback a wedding toast gets.

Good speakers vary on purpose. They slow down for the key result. They stop and let it land. A coach that scores "even pace" penalizes exactly that.

And the failures that actually sink science talks are specific: rushing the one sentence with the finding in it, never pausing after it, saying jargon aloud without defining it, and letting methods run over until the conclusion is squeezed into thirty seconds. Generic tools miss all four.

## How marking solves it

Performers mark their scripts. Slam poets, actors, singers: *slow here*, *breathe here*, *hit this word*. Marked brings that to talks with six marks a user can learn in a minute: a section with a time budget, a `[KEY]` line, a short or long pause, a term that must be defined aloud, and an experimental emphasis mark.

You mark the script with your intent. You rehearse out loud. The report shows the script itself, with every mark colored met, close, or diverged *from your own mark*, with the measured number behind each one and the audio a click away. "18 % slower than your median: met." "0.2 s of silence against your 0.7 s mark." "'Convolution' was first spoken at 1:05 and not defined before that." There is no score.

For people who don't yet know how to mark, there is a draft: pick a goal (clear, persuasive, somber, warm), get a handful of suggested marks, each with a one-line reason to learn from, and accept or reject every one. Restraint is enforced in code so the draft never turns into the generic advice we're escaping.

> TODO (Sophie): the story of where the marking idea came from (slam poet and judge; what marking does for a performer that notes do not).

## Why voice is essential

The slides are not the talk. The spoken delivery is the talk. And nobody can accurately hear their own pace and pauses while speaking; the attention needed to speak is the attention needed to listen. Marked supplies the listener you cannot be for yourself: a measurement of what you actually did, laid over what you intended.

Everything is measured, not judged. Word timestamps from local speech recognition, pauses from a voice-activity detector on the raw audio, rates relative to the speaker's own median in the same take. Where a language model is used at all, it reads text and measured numbers; it never hears the audio and never judges how a take "sounded".

## Who it is for

Students and researchers presenting science: conference talks, thesis defenses, poster pitches, three-minute-thesis competitions. They rehearse alone, often anxious, often in a second language, with dense content and a hard time limit. They know what they want the talk to do; they need to know whether their mouth did it.

> TODO (Sophie): real user feedback, if any. Do not invent quotes.

## Values

- **The user sets the targets.** Nothing is judged against a universal norm by default. Every threshold is editable and travels with the report.
- **Conventions are opt-in presets, never defaults.** A "conference talk" preset adds a pace band and a filler count when the user switches it on, the way someone chooses to code-switch for a job talk. It is off until they do.
- **Non-judgmental language.** Met your mark, close, diverged. Faster or slower than *your* median. No scores, no streaks, no badges.
- **No clinical or therapeutic claims.** This is a rehearsal tool.
- **Audio stays local by default.** Transcription runs on the user's machine. The app says so on screen, and says so again if a cloud key is configured.

## Where it goes next

> TODO (Sophie): roadmap in your words. Candidates from the build: take-over-take comparison is in; emphasis is experimental; alignment could use a fuzzier matcher for names and numbers; a shared "marked script" format could let advisors mark a student's script.

> TODO (Sophie): the ask (what you want from the audience of this pitch).
