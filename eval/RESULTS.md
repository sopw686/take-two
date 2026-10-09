# Evaluation results

Written by `uv run python -m eval.run` on 2026-10-09. Every number below was computed by that run; re-run the command instead of editing this file.

> **Synthetic voice only.** The only recording so far, `synthetic-coral`, is a text-to-speech voice with planted pauses and rate changes, and its labels are the generator's own timings, not a person's. These numbers show that the pipeline and the harness agree with a known construction. They say nothing about how the app does on real speakers.

| Run | |
|---|---|
| Recordings | 1 evaluated: synthetic-coral |
| Speech-to-text | faster-whisper `small.en` on `cuda/float16` (local) |
| Transcripts | fresh speech-to-text run |
| `[DEFINE]` check | heuristic |
| Settings | app defaults |
| Pipeline | `take_two/` at commit ef8fb01 with uncommitted changes |

## Aggregate

Micro-averaged: every mark and line of the 1 evaluated recording(s) pooled.

| Measure | n | Mean abs. error (s) | Median abs. error (s) | Max abs. error (s) | Mean signed error, app − human (s) |
|---|---|---|---|---|---|
| Pause length (`/`, `//`) | 3 | 0.030 | 0.030 | 0.060 | 0.010 |
| Line start | 9 | 0.037 | 0.046 | 0.086 | 0.009 |
| Line end | 9 | 0.180 | 0.180 | 0.269 | -0.180 |

**Status agreement:** 9 of 9 marks (100.0 %).

| Mark kind | Marks | Agreed | Agreement |
|---|---|---|---|
| `KEY` | 2 | 2 | 100.0 % |
| `/` | 2 | 2 | 100.0 % |
| `//` | 1 | 1 | 100.0 % |
| `section` | 3 | 3 | 100.0 % |
| `DEFINE` | 1 | 1 | 100.0 % |

Confusion (rows: human status, columns: app status):

| Human \ App | defined | diverged | met | missing | over | short |
|---|---|---|---|---|---|---|
| defined | 1 | 0 | 0 | 0 | 0 | 0 |
| diverged | 0 | 1 | 0 | 0 | 0 | 0 |
| met | 0 | 0 | 4 | 0 | 0 | 0 |
| missing | 0 | 0 | 0 | 1 | 0 | 0 |
| over | 0 | 0 | 0 | 0 | 1 | 0 |
| short | 0 | 0 | 0 | 0 | 0 | 1 |

## synthetic-coral

- Speaker: **synthetic voice.** Windows text-to-speech voice (synthetic), built by tests/fixtures/make_fixture.py
- Labels: The generator's own timings and planted statuses from tests/fixtures/fixture_truth.json, not a human labeller. Pauses are the silences the generator inserted.
- Audio: `tests/fixtures/fixture.wav` (33.7 s)
- Speech-to-text: faster-whisper `small.en` on `cuda/float16` (local)
- Settings: app defaults

### Summary

| Measure | n | Mean abs. error (s) | Median abs. error (s) | Max abs. error (s) | Mean signed error, app − human (s) |
|---|---|---|---|---|---|
| Pause length (`/`, `//`) | 3 | 0.030 | 0.030 | 0.060 | 0.010 |
| Line start | 9 | 0.037 | 0.046 | 0.086 | 0.009 |
| Line end | 9 | 0.180 | 0.180 | 0.269 | -0.180 |

**Status agreement:** 9 of 9 marks (100.0 %).

| Mark kind | Marks | Agreed | Agreement |
|---|---|---|---|
| `KEY` | 2 | 2 | 100.0 % |
| `/` | 2 | 2 | 100.0 % |
| `//` | 1 | 1 | 100.0 % |
| `section` | 3 | 3 | 100.0 % |
| `DEFINE` | 1 | 1 | 100.0 % |

Confusion (rows: human status, columns: app status):

| Human \ App | defined | diverged | met | missing | over | short |
|---|---|---|---|---|---|---|
| defined | 1 | 0 | 0 | 0 | 0 | 0 |
| diverged | 0 | 1 | 0 | 0 | 0 | 0 |
| met | 0 | 0 | 4 | 0 | 0 | 0 |
| missing | 0 | 0 | 0 | 1 | 0 | 0 |
| over | 0 | 0 | 0 | 0 | 1 | 0 |
| short | 0 | 0 | 0 | 0 | 0 | 1 |

### Pause length

| Mark | App status | App window (s) | App measured (s) | Human pause (s) | Error (s) |
|---|---|---|---|---|---|
| `/:L3:W4` | missing | 8.27–8.27 | 0.00 | 0.00 (none overlaps) | 0.00 |
| `//:L6:W8` | met | 22.00–23.87 | 1.57 | 1.60 (22.22–23.82) | 0.03 |
| `/:L8:W5` | short | 28.86–29.32 | 0.36 | 0.30 (29.03–29.33) | 0.06 |

### Line start and end

| Line | App start (s) | Human start (s) | Error (s) | App end (s) | Human end (s) | Error (s) |
|---|---|---|---|---|---|---|
| 1 | 0.000 | 0.000 | 0.000 | 2.420 | 2.464 | 0.044 |
| 2 | 3.050 | 2.964 | 0.086 | 6.450 | 6.708 | 0.258 |
| 3 | 7.270 | 7.208 | 0.062 | 10.050 | 10.216 | 0.166 |
| 4 | 10.670 | 10.716 | 0.046 | 16.030 | 16.252 | 0.222 |
| 5 | 16.760 | 16.752 | 0.008 | 19.420 | 19.600 | 0.180 |
| 6 | 20.080 | 20.100 | 0.020 | 22.000 | 22.217 | 0.217 |
| 7 | 23.870 | 23.817 | 0.053 | 26.590 | 26.729 | 0.139 |
| 8 | 27.220 | 27.229 | 0.009 | 31.060 | 31.329 | 0.269 |
| 9 | 32.280 | 32.329 | 0.049 | 32.780 | 32.905 | 0.125 |

### Status agreement

| Mark | Human | App | Same |
|---|---|---|---|
| `KEY:L6` | diverged | diverged | yes |
| `KEY:L8` | met | met | yes |
| `/:L3:W4` | missing | missing | yes |
| `//:L6:W8` | met | met | yes |
| `/:L8:W5` | short | short | yes |
| `section:Opening` | met | met | yes |
| `section:Methods` | over | over | yes |
| `section:Results` | met | met | yes |
| `DEFINE:degree heating weeks` | defined | defined | yes |

## How the numbers are computed

- **Pause length.** Each `/` or `//` the app measured is matched to the human `pause` region that overlaps the app's window (end of the word before the mark to the start of the word after it, as stored in the analysis). If several overlap, the largest overlap wins, then the longest region. With no overlapping region the human value is 0 s. Error = |app measured − human duration|.
- **Line start and end.** |app − human| for lines the app found and the human labelled `line N`.
- **Status agreement.** The app's status equals the human's status in statuses.csv, for marks that have both.
- **Aggregate.** Rows from all recordings pooled before averaging (micro-average).
- Signed errors are app − human: positive means the app measured later or longer.
