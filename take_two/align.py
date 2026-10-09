"""Script <-> transcript alignment.

Both sides are normalized to comparison tokens (see marks.normalize_word), then
aligned with difflib.SequenceMatcher (longest-common-block matching). Ad-libs
show up as unmatched transcript words and are ignored; skipped script lines get
zero coverage and are reported as "not found in this take" rather than scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from take_two.marks import Script, Token, normalize_word
from take_two.stt.base import Transcript


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


def adlib_spans(al: Alignment, transcript: Transcript, found: set[int], claimed: frozenset[int] = frozenset()) -> dict[int, list[dict]]:
    """Transcript words that matched no script word, placed between the script words they were said between.

    Walks the aligned tokens of found lines in script order (which is also time order).
    Each span gets the line it belongs to and `word_index`, the token it sits before
    (len(tokens) = end of the line). A span between two lines goes to the line it is
    closer to in time; one before the first or after the last aligned word goes to that
    word's line. Words already matched (to any line) or claimed by another use are skipped.
    """
    words = transcript.words
    comparable = {i for _, i in al.transcript_norm}
    taken = set(al.matched_transcript) | set(claimed)
    anchors = [t for t in al.tokens if t.aligned and t.token.line in found and t.transcript_indexes]
    out: dict[int, list[dict]] = {}
    prev: TokenAlignment | None = None
    prev_w = -1
    for cur in anchors + [None]:
        nxt_w = min(cur.transcript_indexes) if cur is not None else len(words)
        gap = [w for w in range(prev_w + 1, nxt_w) if w in comparable and w not in taken]
        # Words between two lines with an unfound line in between belong to that line, which is not compared.
        skipped = prev is not None and cur is not None and any(
            ln not in found for ln in range(prev.token.line + 1, cur.token.line))
        if gap and not skipped and (prev is not None or cur is not None):
            if prev is None:
                line, k = cur.token.line, cur.token.index
            elif cur is None or prev.token.line == cur.token.line:
                line, k = prev.token.line, prev.token.index + 1
            else:
                before = words[gap[0]].start - (prev.end if prev.end is not None else words[gap[0]].start)
                after = (cur.start if cur.start is not None else words[gap[-1]].end) - words[gap[-1]].end
                line, k = (prev.token.line, prev.token.index + 1) if before <= after else (cur.token.line, cur.token.index)
            near = [t.token.norm for t in (prev, cur) if t is not None]
            # One span per run of consecutive words, so every span's text is a verbatim slice of the transcript.
            runs: list[list[int]] = []
            for w in gap:
                if runs and w == runs[-1][-1] + 1:
                    runs[-1].append(w)
                else:
                    runs.append([w])
            for run in runs:
                said = [n for i in run for n in normalize_word(words[i].text)]
                out.setdefault(line, []).append({
                    "word_index": k, "text": " ".join(words[i].text for i in run),
                    "start": round(words[run[0]].start, 3), "end": round(words[run[-1]].end, 3), "words": run,
                    "repeat": said in near,  # a restart such as "the the model"
                })
        if cur is not None:
            prev, prev_w = cur, max(prev_w, max(cur.transcript_indexes))
    return out
