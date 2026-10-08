"""Script <-> transcript alignment.

Both sides are normalized to comparison tokens (see marks.normalize_word), then
aligned with difflib.SequenceMatcher (longest-common-block matching). Ad-libs
show up as unmatched transcript words and are ignored; skipped script lines get
zero coverage and are reported as "not found in this take" rather than scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from marked.marks import Script, Token, normalize_word
from marked.stt.base import Transcript


@dataclass
class TokenAlignment:
    token: Token
    start: float | None = None
    end: float | None = None
    transcript_indexes: list[int] = field(default_factory=list)  # indexes into transcript.words

    @property
    def aligned(self) -> bool:
        return self.start is not None


@dataclass
class LineTiming:
    line: int
    start: float | None
    end: float | None
    matched: int
    total: int
    span_words: int = 0   # script words between the first and last matched token, inclusive

    @property
    def coverage(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def duration(self) -> float | None:
        if self.start is None or self.end is None:
            return None
        return self.end - self.start

    def wpm(self) -> float | None:
        """Words per minute over the aligned span.

        Uses the script's word count inside the span rather than the number of
        matched words, so a mis-transcribed word does not read as slower speech.
        """
        d = self.duration
        if d is None or d <= 0.0 or self.matched < 2:
            return None
        return self.span_words / (d / 60.0)


@dataclass
class Alignment:
    tokens: list[TokenAlignment]
    lines: list[LineTiming]
    transcript_norm: list[tuple[str, int]]   # (norm word, transcript word index)
    matched_transcript: set[int]

    def line_tokens(self, line: int) -> list[TokenAlignment]:
        return [t for t in self.tokens if t.token.line == line]

    def first_aligned(self, line: int) -> TokenAlignment | None:
        for t in self.line_tokens(line):
            if t.aligned:
                return t
        return None

    def last_aligned(self, line: int) -> TokenAlignment | None:
        for t in reversed(self.line_tokens(line)):
            if t.aligned:
                return t
        return None


def flatten_transcript(transcript: Transcript) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for i, w in enumerate(transcript.words):
        for n in normalize_word(w.text):
            out.append((n, i))
    return out


def align(script: Script, transcript: Transcript) -> Alignment:
    tokens = script.tokens
    script_norm: list[tuple[str, int]] = []       # (norm word, token position)
    for pos, tok in enumerate(tokens):
        for n in tok.norm:
            script_norm.append((n, pos))
    trans_norm = flatten_transcript(transcript)

    a = [n for n, _ in script_norm]
    b = [n for n, _ in trans_norm]
    sm = SequenceMatcher(None, a, b, autojunk=False)

    talign = [TokenAlignment(token=t) for t in tokens]
    matched_transcript: set[int] = set()
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            _, tok_pos = script_norm[blk.a + k]
            _, w_idx = trans_norm[blk.b + k]
            ta = talign[tok_pos]
            w = transcript.words[w_idx]
            ta.start = w.start if ta.start is None else min(ta.start, w.start)
            ta.end = w.end if ta.end is None else max(ta.end, w.end)
            if w_idx not in ta.transcript_indexes:
                ta.transcript_indexes.append(w_idx)
            matched_transcript.add(w_idx)

    lines: list[LineTiming] = []
    for ln in script.lines:
        lt = [talign[i] for i, t in enumerate(tokens) if t.line == ln.index]
        matched_idx = [i for i, t in enumerate(lt) if t.aligned]
        matched = [lt[i] for i in matched_idx]
        starts = [t.start for t in matched if t.start is not None]
        ends = [t.end for t in matched if t.end is not None]
        lines.append(LineTiming(line=ln.index,
                                start=min(starts) if starts else None,
                                end=max(ends) if ends else None,
                                matched=len(matched), total=len(lt),
                                span_words=(matched_idx[-1] - matched_idx[0] + 1) if matched_idx else 0))
    return Alignment(tokens=talign, lines=lines, transcript_norm=trans_norm, matched_transcript=matched_transcript)
