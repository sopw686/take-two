"""Build transcripts with chosen timings so analysis logic can be tested without audio."""

from __future__ import annotations

from take_two.audio import Silence
from take_two.stt.base import Transcript, Word

WORD_S = 0.3   # default spoken length of a word
GAP_S = 0.1    # default gap after a word  -> 150 wpm


def make_transcript(text: str, start: float = 0.0, gaps: dict[int, float] | None = None,
                    durs: dict[int, float] | None = None) -> Transcript:
    """Lay out words left to right. gaps[i] / durs[i] override the gap after / length of word i."""
    gaps = gaps or {}
    durs = durs or {}
    t = start
    words: list[Word] = []
    for i, w in enumerate(text.split()):
        d = durs.get(i, WORD_S)
        words.append(Word(text=w, start=round(t, 3), end=round(t + d, 3)))
        t += d + gaps.get(i, GAP_S)
    return Transcript(words=words, text=text, backend="fake", model="fake", device="test", duration_s=t + 1.0)


def silences_from_gaps(transcript: Transcript, min_s: float = 0.15) -> list[Silence]:
    out = []
    for a, b in zip(transcript.words, transcript.words[1:]):
        if b.start - a.end >= min_s:
            out.append(Silence(a.end, b.start))
    last = transcript.words[-1].end
    if transcript.duration_s - last >= min_s:
        out.append(Silence(last, transcript.duration_s))
    return out
