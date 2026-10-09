"""Mark syntax parser.

    ## Section name [2:00]   section with a time budget (m:ss)
    [KEY] ...                key line: slower than the speaker's median, pause after
    /  //                    short / long deliberate pause (whitespace-delimited)
    [DEFINE: term]           term must be explained aloud at or before first use
    *word*                   emphasis (experimental)

Marks are stripped before alignment. Lines are non-blank, non-header lines.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_RE = re.compile(r"^\s*##\s*(?P<name>.*?)\s*(?:\[(?P<m>\d+):(?P<s>\d{1,2})\])?\s*$")
KEY_RE = re.compile(r"^\s*\[KEY\]\s*", re.IGNORECASE)
DEFINE_RE = re.compile(r"\[DEFINE:\s*(?P<term>[^\]]+?)\s*\]", re.IGNORECASE)
PAUSE_RE = re.compile(r"^(?P<kind>//?)$")
EMPH_RE = re.compile(r"^\*(?P<word>[^\s*]+)\*(?P<punct>[^\w\s*]*)$")  # *word*, keeps trailing punctuation
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def blank_comments(text: str) -> str:
    """Remove <!-- comments --> but keep their newlines so line numbers stay stable."""
    return COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
         "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def num_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (" " + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + num_to_words(r) if r else "")
    if n < 1_000_000:
        k, r = divmod(n, 1000)
        return num_to_words(k) + " thousand" + (" " + num_to_words(r) if r else "")
    m, r = divmod(n, 1_000_000)
    return num_to_words(m) + " million" + (" " + num_to_words(r) if r else "")


def normalize_word(raw: str) -> list[str]:
    """Normalize one whitespace-delimited word to a list of comparison tokens.

    Lowercases, strips punctuation, expands digits and '%' so that the script
    and the transcript agree whichever way numbers were written.
    """
    w = raw.lower().replace("’", "'").replace("‘", "'")
    w = w.replace("%", " percent ")
    out: list[str] = []
    for piece in re.split(r"[\s\-–—/]+", w):
        if re.fullmatch(r"[\d,]+(\.\d+)?", piece):
            piece = piece.replace(",", "")
        if re.fullmatch(r"\d+", piece):
            n = int(piece)
            out.extend(num_to_words(n).split() if n < 1_000_000_000 else [piece])
            continue
        if re.fullmatch(r"\d+\.\d+", piece):
            a, b = piece.split(".")
            out.extend(num_to_words(int(a)).split() + ["point"] + [_ONES[int(d)] for d in b])
            continue
        cleaned = re.sub(r"[^a-z0-9']", "", piece).replace("'", "")
        if cleaned:
            out.append(cleaned)
    return out


@dataclass
class Token:
    line: int            # line index
    index: int           # index within the line
    text: str            # original word as written (marks removed)
    norm: list[str]      # normalized comparison tokens (may be several, may be empty)


@dataclass
class PauseMark:
    line: int
    word_index: int      # pause sits before token `word_index` of the line
    kind: str            # "/" or "//"


@dataclass
class DefineMark:
    term: str
    line: int
    section: int


@dataclass
class Line:
    index: int
    section: int
    raw: str             # as typed, including marks
    text: str            # marks stripped, for display
    is_key: bool
    tokens: list[Token] = field(default_factory=list)
    pauses: list[PauseMark] = field(default_factory=list)
    emphasis: list[int] = field(default_factory=list)   # token indexes
    raw_line_no: int = 0  # 0-based line number in the original text

    @property
    def word_count(self) -> int:
        return len(self.tokens)


@dataclass
class Section:
    index: int
    name: str
    budget_s: float | None
    line_start: int      # first line index (inclusive)
    line_end: int        # last line index (exclusive)
    raw_line_no: int | None = None


@dataclass
class Script:
    sections: list[Section]
    lines: list[Line]
    defines: list[DefineMark]

    @property
    def tokens(self) -> list[Token]:
        return [t for ln in self.lines for t in ln.tokens]

    def section_lines(self, sec: Section) -> list[Line]:
        return self.lines[sec.line_start:sec.line_end]


def is_section_header(raw: str) -> bool:
    return raw.lstrip().startswith("##") and SECTION_RE.match(raw) is not None


def strip_line_marks(raw: str) -> tuple[str, bool, list[str], list[PauseMark], list[int]]:
    """Return (display_text, is_key, define_terms, pauses, emphasis_token_indexes)."""
    is_key = bool(KEY_RE.match(raw))
    s = KEY_RE.sub("", raw, count=1) if is_key else raw
    terms = [m.group("term").strip() for m in DEFINE_RE.finditer(s)]
    s = DEFINE_RE.sub(" ", s)

    pauses: list[PauseMark] = []
    emphasis: list[int] = []
    words: list[str] = []
    for piece in s.split():
        pm = PAUSE_RE.match(piece)
        if pm:
            pauses.append(PauseMark(line=-1, word_index=len(words), kind=pm.group("kind")))
            continue
        em = EMPH_RE.match(piece)
        if em:
            emphasis.append(len(words))
            words.append(em.group("word") + em.group("punct"))
            continue
        words.append(piece)
    return " ".join(words), is_key, terms, pauses, emphasis


def parse_script(text: str) -> Script:
    text = blank_comments(text)
    sections: list[Section] = []
    lines: list[Line] = []
    defines: list[DefineMark] = []

    for raw_no, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        if is_section_header(raw):
            sm = SECTION_RE.match(raw)
            assert sm is not None
            budget = None
            if sm.group("m") is not None:
                budget = int(sm.group("m")) * 60 + int(sm.group("s"))
            if sections and sections[-1].line_start == sections[-1].line_end and sections[-1].name == "":
                sections.pop()  # drop the empty implicit section
            sections.append(Section(index=len(sections),
                                    name=sm.group("name").strip() or f"Section {len(sections) + 1}",
                                    budget_s=float(budget) if budget is not None else None,
                                    line_start=len(lines), line_end=len(lines), raw_line_no=raw_no))
            continue
        if not sections:
            sections.append(Section(index=0, name="", budget_s=None, line_start=0, line_end=0))
        sec = sections[-1].index
        display, is_key, terms, pauses, emphasis = strip_line_marks(raw)
        li = len(lines)
        line = Line(index=li, section=sec, raw=raw, text=display, is_key=is_key, raw_line_no=raw_no)
        for wi, w in enumerate(display.split()):
            line.tokens.append(Token(line=li, index=wi, text=w, norm=normalize_word(w)))
        for p in pauses:
            p.line = li
        line.pauses = pauses
        line.emphasis = emphasis
        lines.append(line)
        sections[sec].line_end = li + 1
        for t in terms:
            defines.append(DefineMark(term=t, line=li, section=sec))
    return Script(sections=sections, lines=lines, defines=defines)


def strip_marks(text: str) -> str:
    """Plain prose: no section headers, no marks. One line per script line."""
    out = []
    for raw in blank_comments(text).splitlines():
        if not raw.strip() or is_section_header(raw):
            continue
        out.append(strip_line_marks(raw)[0])
    return "\n".join(out)


def format_budget(seconds: float | None) -> str:
    if seconds is None:
        return ""
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"
