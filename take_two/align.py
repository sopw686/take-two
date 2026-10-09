"""Script <-> transcript alignment.

Both sides are normalized to comparison tokens (see marks.normalize_word), then
aligned with difflib.SequenceMatcher (longest-common-block matching). Spoken
years and hundreds are rewritten into the words digits normalize to, so "2019"
matches "twenty nineteen". Inside each gap between exact matches, a misheard
word ("leaching" for "bleaching") can be paired with its script word by
character similarity, never across an exact match. Ad-libs show up as
unmatched transcript words; skipped script lines get zero coverage and are
reported as "not found in this take" rather than scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from take_two.config import Settings
from take_two.marks import Script, Token, normalize_word, num_to_words
from take_two.stt.base import Transcript


@dataclass
class TokenAlignment:
    token: Token
    start: float | None = None
    end: float | None = None
    transcript_indexes: list[int] = field(default_factory=list)  # indexes into transcript.words
    fuzzy: bool = False          # matched only by character similarity (a misheard word)
    heard: str | None = None     # what the transcript said instead, for a fuzzy match

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
    transcript_norm: list[tuple[str, int, int]]   # (norm word, first and last transcript word index)
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


_ONES = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])}
_TEENS = {w: 10 + i for i, w in enumerate(["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                                           "seventeen", "eighteen", "nineteen"])}
_TENS = {w: 10 * i for i, w in enumerate(["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]) if w}
NUMBER_WORDS = set(_ONES) | set(_TEENS) | set(_TENS) | {"hundred", "thousand", "million", "billion", "point", "percent", "oh"}
_NEGATIONS = ("un", "in", "im", "ir", "il", "non", "dis")

# One comparison token and the range of owners (script token positions or transcript word indexes) it stands for.
Entry = tuple[str, int, int]


def _small(stream: list[Entry], i: int) -> tuple[int, int] | None:
    """A number 1..99 written as words at stream[i:]: (value, tokens used)."""
    if i >= len(stream):
        return None
    w = stream[i][0]
    if w in _TEENS:
        return _TEENS[w], 1
    if w in _TENS:
        if i + 1 < len(stream) and stream[i + 1][0] in _ONES and stream[i + 1][0] != "zero":
            return _TENS[w] + _ONES[stream[i + 1][0]], 2
        return _TENS[w], 1
    if w in _ONES and w != "zero":
        return _ONES[w], 1
    return None


def canonical_numbers(stream: list[Entry]) -> list[Entry]:
    """Rewrite spoken years and hundreds into the cardinal words that digits normalize to.

    "twenty nineteen", "nineteen oh five", "nineteen hundred", "fifteen hundred" and
    "two thousand and nineteen" become num_to_words(value), so they match "2019", "1905",
    "1900", "1500" written in the script (and the other way round). Only a maximal run of
    number words is rewritten, so "twenty five percent" or "1,200" are left alone. Each new
    token keeps the owner range of the words it replaces, so timestamps stay right.
    """
    out: list[Entry] = []
    i, n = 0, len(stream)
    while i < n:
        w, lo, hi = stream[i]
        prev_is_num = i > 0 and stream[i - 1][0] in NUMBER_WORDS
        # "two thousand and nineteen": drop the "and" (its word joins the next token's range).
        if w == "and" and out and out[-1][0] in ("hundred", "thousand") and _small(stream, i + 1):
            nxt = stream[i + 1]
            stream[i + 1] = (nxt[0], lo, nxt[2])
            i += 1
            continue
        lead = _TEENS.get(w) if w in _TEENS else (20 if w == "twenty" else None)
        if lead is not None and lead >= 11 and not prev_is_num:
            j, value = i + 1, None
            if j < n and stream[j][0] in ("oh", "o", "zero") and j + 1 < n and stream[j + 1][0] in _ONES:
                value, j = lead * 100 + _ONES[stream[j + 1][0]], j + 2
            elif j < n and stream[j][0] == "hundred":
                value, j = lead * 100, j + 1
            else:
                y = _small(stream, j)
                if y and y[0] >= 10:
                    value, j = lead * 100 + y[0], j + y[1]
            if value is not None and not (j < n and stream[j][0] in NUMBER_WORDS):
                end = stream[j - 1][2]
                out.extend((t, lo, end) for t in num_to_words(value).split())
                i = j
                continue
        # "twenty five hundred" -> 2500 (a two-word multiple of a hundred, 21..99).
        if w in _TENS and not prev_is_num:
            x = _small(stream, i)
            if x and x[1] == 2 and i + 2 < n and stream[i + 2][0] == "hundred" and not (
                    i + 3 < n and stream[i + 3][0] in NUMBER_WORDS):
                out.extend((t, lo, stream[i + 2][2]) for t in num_to_words(x[0] * 100).split())
                i += 3
                continue
        out.append((w, lo, hi))
        i += 1
    return out


_SENTENCE_END = (".", "!", "?")


def flatten_transcript(transcript: Transcript) -> list[Entry]:
    """Comparison tokens of the transcript; numbers are rewritten sentence by sentence, never across a full stop."""
    out: list[Entry] = []
    sentence: list[Entry] = []
    for i, w in enumerate(transcript.words):
        sentence.extend((n, i, i) for n in normalize_word(w.text))
        if w.text.rstrip("\"')”’").endswith(_SENTENCE_END):
            out.extend(canonical_numbers(sentence))
            sentence = []
    return out + canonical_numbers(sentence)


def _similar(a: str, b: str, threshold: float, min_chars: int) -> float:
    """Character similarity of two different words, or 0 when they must not be matched loosely."""
    if threshold >= 1.0 or len(a) < min_chars or len(b) < min_chars or a in NUMBER_WORDS or b in NUMBER_WORDS:
        return 0.0
    short, long_ = sorted((a, b), key=len)
    if any(long_ == p + short for p in _NEGATIONS):  # possible / impossible flips the meaning
        return 0.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
        return 0.0
    r = sm.ratio()
    return r if r >= threshold else 0.0


def _fuzzy_pairs(a: list[str], b: list[str], threshold: float, min_chars: int) -> list[tuple[int, int]]:
    """Order-preserving pairs inside one gap between exact matches: most pairs, then the most similar."""
    n, m = len(a), len(b)
    if not n or not m or n * m > 4000:
        return []
    sim = [[_similar(a[i], b[j], threshold, min_chars) for j in range(m)] for i in range(n)]
    best = [[(0, 0.0)] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            cand = max(best[i + 1][j], best[i][j + 1])
            if sim[i][j]:
                c, s = best[i + 1][j + 1]
                cand = max(cand, (c + 1, s + sim[i][j]))
            best[i][j] = cand
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if sim[i][j] and best[i][j] == (best[i + 1][j + 1][0] + 1, best[i + 1][j + 1][1] + sim[i][j]):
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def align(script: Script, transcript: Transcript, settings: Settings | None = None) -> Alignment:
    settings = settings or Settings()
    tokens = script.tokens
    script_norm: list[Entry] = []                 # (norm word, first and last token position)
    pos = 0
    for ln in script.lines:                       # numbers are rewritten per sentence, never across lines
        stream: list[Entry] = []
        for k, tok in enumerate(ln.tokens):
            stream.extend((n, pos + k, pos + k) for n in tok.norm)
            if tok.text.rstrip("\"')”’").endswith(_SENTENCE_END):
                script_norm.extend(canonical_numbers(stream))
                stream = []
        script_norm.extend(canonical_numbers(stream))
        pos += len(ln.tokens)
    trans_norm = flatten_transcript(transcript)

    a = [n for n, _, _ in script_norm]
    b = [n for n, _, _ in trans_norm]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    pairs: list[tuple[int, int, bool]] = []       # (script entry, transcript entry, exact)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            pairs.extend((i1 + k, j1 + k, True) for k in range(i2 - i1))
        elif tag == "replace":
            # A misheard word ("leaching" for "bleaching") only fills a gap between exact matches, so it can never cross one.
            pairs.extend((i1 + i, j1 + j, False) for i, j in
                         _fuzzy_pairs(a[i1:i2], b[j1:j2], settings.fuzzy_match_ratio, settings.fuzzy_min_chars))

    talign = [TokenAlignment(token=t) for t in tokens]
    exact_hit: set[int] = set()
    matched_transcript: set[int] = set()
    for si, tj, exact in pairs:
        _, p_lo, p_hi = script_norm[si]
        _, w_lo, w_hi = trans_norm[tj]
        for tok_pos in range(p_lo, p_hi + 1):
            ta = talign[tok_pos]
            for w_idx in range(w_lo, w_hi + 1):
                w = transcript.words[w_idx]
                ta.start = w.start if ta.start is None else min(ta.start, w.start)
                ta.end = w.end if ta.end is None else max(ta.end, w.end)
                if w_idx not in ta.transcript_indexes:
                    ta.transcript_indexes.append(w_idx)
                matched_transcript.add(w_idx)
            if exact:
                exact_hit.add(tok_pos)
            else:
                ta.heard = " ".join(transcript.words[k].text for k in range(w_lo, w_hi + 1))
    for k, ta in enumerate(talign):
        ta.fuzzy = ta.aligned and k not in exact_hit

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
    comparable = {w for _, lo, hi in al.transcript_norm for w in range(lo, hi + 1)}
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
