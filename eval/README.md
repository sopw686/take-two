# Evaluation harness

This folder checks the app's measurements against a person's labels. For each recorded talk it reports:

- **Pause length error:** how far each measured `/` and `//` is from the pause a person hears there.
- **Line start and end error:** how far the app's line boundaries are from where a person hears each line start and end.
- **Status agreement:** how often the app's status for a mark (met, short, over, ...) matches the status a person gives it, with a confusion table.

Results go to `eval/RESULTS.md`. That file is written by the harness only. Do not type numbers into it.

**So far the only recording is `synthetic-coral`.** It is the synthetic test voice, and its labels come from the generator, not from a person. Its numbers show that the pipeline and the harness agree with a known construction. They say nothing about real speakers. Real labelled recordings still need to be added.

## Commands

```powershell
uv run python -m eval.run                         # every recording -> eval/RESULTS.md (runs local speech-to-text)
uv run python -m eval.run my-talk                 # only some recordings
uv run python -m eval.run --save-transcripts      # also keep each transcript as transcript.json in its folder
uv run python -m eval.run --reuse-transcripts     # use those transcript.json files; no speech-to-text, much faster
uv run python -m eval.run --list-marks my-talk > eval/recordings/my-talk/statuses.csv   # a statuses template
uv run python -m eval.retest --same-script <take_id>   # the noise floor (see below)
uv run python -m eval.make_synthetic              # rebuild eval/recordings/synthetic-coral/
```

On a machine with an NVIDIA GPU, add `--extra gpu` after `uv run` (or run `uv sync --extra gpu` once). The run scripts do this for the app. Without it, speech-to-text runs on the CPU, which is slower but gives the same kind of result.

Each recording goes through the real pipeline (`take_two.pipeline`) in a temporary takes folder, so your own takes are never read or changed. Speech-to-text is always local. If cloud transcription is configured (`TAKE_TWO_STT=openai`), the harness refuses to run. If `ANTHROPIC_API_KEY` is set, the `[DEFINE]` check uses the model, as the app does; `RESULTS.md` records which method was used.

## Folder layout

```
eval/recordings/<name>/
  audio.wav        the recording (any format the app accepts: wav, webm, m4a, mp3, ...), or instead:
  audio.ref        one line: the path of the audio file, relative to the repository root (an absolute path also works)
  script.md        the script with its marks, exactly as rehearsed
  labels.txt       the Audacity label export (see below)
  statuses.csv     optional: the statuses a person gives each mark
  settings.json    optional: thresholds, if the talk was judged against non-default ones
  info.json        optional: {"synthetic": false, "speaker": "...", "labels": "who labelled it, and how"}
  transcript.json  optional: written by --save-transcripts, read by --reuse-transcripts
```

## 1. Record a talk

- The easiest way is to rehearse in the app as usual and copy the take out of the takes folder: `takes/<take_id>/audio.wav` becomes `audio.wav` and `takes/<take_id>/script.md` becomes `script.md`.
- You can also record with any other recorder. Use the microphone and room the speaker will really use, and leave a second of silence at the start and end.
- Use the script exactly as it was rehearsed. If you edit it later, the line numbers and marks move, and old labels no longer fit.
- Ask the speaker's permission before you record, and before you commit audio of anyone but yourself. This repository may be synced (on the dev machine it sits in OneDrive). To keep the audio out of the repository, store it elsewhere and put its absolute path in `audio.ref`.
- In `info.json`, describe the speaker without naming them unless they agreed to it (for example "PhD student, second rehearsal, laptop microphone").

## 2. Label lines and pauses in Audacity

The harness needs two kinds of region labels:

- `line N`: from the first sound of script line N to the end of its last sound. N counts from 1.
- `pause`: a silence you hear, from the end of one word's sound to the start of the next.

Count lines the way the app does: blank lines and `## Section` headers do not count, and `<!-- comments -->` are ignored. `--list-marks` (below) prints the numbered lines in the terminal.

Steps:

1. Open the recording: **File > Open**.
2. Add a label track: **Tracks > Add New > Label Track**.
3. Label each script line:
   1. In the audio track, drag across the line, from the start of its first word to the end of its last word. Zoom in to place the edges (**Ctrl+1** zooms in, **Ctrl+3** zooms out), and press **Space** to listen to the selection.
   2. Press **Ctrl+B** (**Edit > Labels > Add Label at Selection**).
   3. Type `line 1` (then `line 2`, and so on) and press **Enter**.
4. Label each pause:
   1. Drag across the silence, from where the sound of one word stops to where the next starts.
   2. Press **Ctrl+B**, type `pause`, press **Enter**.
   3. Label every pause you hear at a `/` or `//` mark and after each `[KEY]` line. Pauses elsewhere do no harm: a pause only counts when it overlaps the place where the app measured a mark. Where you hear no pause at a mark, add no label. The harness then compares the app's value with 0 s.
   4. A label inside a line's region is fine. Line and pause regions may overlap.
5. Export: **File > Export > Export Labels...** (in newer Audacity versions **File > Export Other > Export Labels...**). Save the file as `labels.txt` in the recording's folder.

Audacity writes one label per line as `start<TAB>end<TAB>label`, in seconds. A label made with a single click (a point label, where start = end) has no length. The harness reports it in `RESULTS.md` and ignores it, so always select a region before pressing Ctrl+B.

## 3. Give each mark a status (optional)

`statuses.csv` has one row per mark, `mark,status`. Write it **before** you look at the app's report for this recording, so the app's answer does not sway you.

```powershell
uv run python -m eval.run --list-marks my-talk > eval/recordings/my-talk/statuses.csv
```

This writes a template with every mark of the script and an empty status. Fill in what you hear and delete rows you cannot judge. Mark ids:

| Mark id | Means |
|---|---|
| `KEY:L6` | the `[KEY]` mark on line 6 |
| `/:L3:W4` | the `/` after word 4 of line 3 (W = how many of the line's words come before the pause; marks are not words) |
| `//:L6:W8` | the `//` after word 8 of line 6 |
| `section:Methods` | the Methods section's time budget |
| `DEFINE:degree heating weeks` | the `[DEFINE: degree heating weeks]` mark |

Use the app's own status words and judge them against the same thresholds the app uses: the defaults below, or `settings.json`.

| Mark | Statuses | How to decide (defaults) |
|---|---|---|
| `/`, `//` | `met`, `short`, `missing` | Length of the pause you hear at the mark: `met` at 0.7 s or more for `/` (1.5 s for `//`), `short` at 40 % of that or more, `missing` below. |
| `KEY` | `met`, `near`, `diverged`, `not_found` | `met`: clearly slower than the talk's usual pace (the app asks for 10 % slower than the speaker's median) **and** a pause of 0.7 s or more after it. `diverged`: faster than usual, or a pause after it under 40 % of 0.7 s. `near`: anything in between. `not_found`: the line was not said. |
| `section` | `met`, `over`, `under`, `not_found`, `no_budget` | From your line labels: the first line's start to the last line's end, against the budget, with a tolerance of 10 % or 3 s, whichever is larger. |
| `DEFINE` | `defined`, `undefined`, `never_spoken` | `defined`: the term is explained at or just before its first use. `undefined`: it is used first and explained later, or never explained. `never_spoken`: it is never said. |

`settings.json` takes the same keys as the app's Settings, for example `{"short_pause_s": 0.8, "key_slower_pct": 15}`. Keys you leave out keep the app's defaults.

## What the numbers mean

- **Pause length.** Each `/` or `//` the app measured is matched to the `pause` label that overlaps the app's measurement window. That window runs from the end of the word before the mark to the start of the word after it, as stored in the analysis. If several labels overlap, the one with the largest overlap wins, then the longest. Error = |app's length − labelled length|. With no overlapping label, the labelled length is 0 s.
- **Line start and end.** |app − label| for each line the app found and you labelled. Lines you labelled that the app did not find are listed separately. They are not counted as errors in seconds.
- **Status agreement.** The share of marks where the app's status equals yours, plus a confusion table (rows: your status, columns: the app's status).
- **Aggregate.** All marks and lines of all recordings are pooled before averaging (a micro-average). A long talk therefore counts more than a short one.
- Signed errors are app − label. A positive value means the app put the boundary later, or measured a longer pause.

## The noise floor: `eval/retest.py`

The same speaker reading the same script twice will not produce identical numbers. To see how much the measurements move on their own, record the same script several times in the app (three to five takes), then run:

```powershell
uv run python -m eval.retest --same-script <take_id>     # every real take sharing that take's script
uv run python -m eval.retest <take_id> <take_id> ...     # or name the takes
```

It prints, as Markdown, the spread of the median wpm and of each pause mark's measured length across the takes: n, min, max, max − min and the population standard deviation. A change between two takes that is smaller than this spread cannot be told apart from noise. It reads takes from `TAKE_TWO_TAKES_DIR` (default `takes/`) and writes nothing.

## The synthetic recording

`eval/recordings/synthetic-coral/` is generated by `uv run python -m eval.make_synthetic` from `tests/fixtures/fixture_truth.json` and `fixture_script.md`. Its `labels.txt` comes from the generator's line timings and inserted silences, and its `statuses.csv` from the statuses the fixture was built to produce. `audio.ref` points at `tests/fixtures/fixture.wav`. Its `transcript.json` is one run of the local speech-to-text, saved with `--save-transcripts`.
