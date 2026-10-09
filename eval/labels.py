"""File formats of an evaluation recording: Audacity label tracks, human statuses and mark ids.

labels.txt is Audacity's label export, one label per line: start<TAB>end<TAB>label, in seconds.
Two labels mean something here: `line N` spans script line N (counted from 1), `pause` spans a
silence the labeller hears. statuses.csv holds `mark,status` rows in the app's own status words.

A mark id names one mark the way a person can read it off the script:

    KEY:L6                       the [KEY] mark on line 6
    /:L3:W4                      the / after word 4 of line 3
    //:L6:W8                     the // after word 8 of line 6
    section:Methods              the Methods section's budget
    DEFINE:degree heating weeks  the [DEFINE] of that term

Lines are counted the way the app counts them: blank lines, `##` headers and comments do not
count. W is the number of the line's words before the pause, marks not counted, which is the
app's own word_index for that pause. Section names and terms match ignoring case.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from take_two.marks import Script

# The statuses the app can give each kind of mark (analysis.py, define.py).
STATUSES: dict[str, set[str]] = {
    "KEY": {"met", "near", "diverged", "not_found"},
    "/": {"met", "short", "missing", "unmeasurable"},
    "//": {"met", "short", "missing", "unmeasurable"},
    "section": {"met", "over", "under", "not_found", "no_budget"},
    "DEFINE": {"defined", "undefined", "never_spoken"},
}

LINE_LABEL_RE = re.compile(r"^line\s*(\d+)$", re.IGNORECASE)
KEY_ID_RE = re.compile(r"^KEY:L(\d+)$", re.IGNORECASE)
PAUSE_ID_RE = re.compile(r"^(//?):L(\d+):W(\d+)$", re.IGNORECASE)
NAMED_ID_RE = re.compile(r"^(section|DEFINE):(.+)$", re.IGNORECASE)


# ---- labels.txt -----------------------------------------------------------------

@dataclass(frozen=True)
class Label:
    start: float
    end: float
    text: str
    line_no: int  # line in labels.txt, for messages


@dataclass
class HumanLabels:
    lines: dict[int, tuple[float, float]] = field(default_factory=dict)  # 0-based script line -> (start, end)
    pauses: list[tuple[float, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _seconds(raw: str) -> float:
    # Some Audacity locales export a decimal comma; tabs separate the fields, so a comma is never a separator.
    return float(raw.strip().replace(",", "."))


def parse_labels(text: str, source: str = "labels.txt") -> list[Label]:
    """Parse an Audacity label export. Point labels (start == end) are kept; interpret_labels decides."""
    out: list[Label] = []
    for no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split("\t") if "\t" in raw else raw.split(None, 2)
        if parts[0].strip() == "\\":
            continue  # the frequency range Audacity writes after a label made with a spectral selection
        if len(parts) < 2:
            raise ValueError(f"{source} line {no}: expected start<TAB>end<TAB>label, got {raw!r}")
        try:
            start, end = _seconds(parts[0]), _seconds(parts[1])
        except ValueError:
            raise ValueError(f"{source} line {no}: start and end must be seconds, got {parts[0]!r} and {parts[1]!r}") from None
        if end < start:
            raise ValueError(f"{source} line {no}: the label ends ({end}) before it starts ({start})")
        out.append(Label(start=start, end=end, text="\t".join(parts[2:]).strip(), line_no=no))
    return out


def interpret_labels(labels: list[Label], source: str = "labels.txt") -> HumanLabels:
    """`line N` regions become line spans, `pause` regions become pauses; anything else is reported and ignored."""
    out = HumanLabels()
    seen: dict[int, int] = {}
    for lab in labels:
        name = " ".join(lab.text.split())
        m = LINE_LABEL_RE.match(name)
        is_pause = name.lower() == "pause"
        if not m and not is_pause:
            out.warnings.append(f"{source} line {lab.line_no}: label {lab.text!r} is neither `line N` nor `pause`; ignored.")
            continue
        if lab.end <= lab.start:
            out.warnings.append(f"{source} line {lab.line_no}: `{name}` is a point label at {lab.start:.3f} s; "
                                "select the whole region before adding the label. Ignored.")
            continue
        if is_pause:
            out.pauses.append((lab.start, lab.end))
            continue
        n = int(m.group(1))
        if n < 1:
            raise ValueError(f"{source} line {lab.line_no}: lines are counted from 1, got `{name}`")
        if n - 1 in seen:
            raise ValueError(f"{source} line {lab.line_no}: line {n} is labelled twice (also on line {seen[n - 1]})")
        seen[n - 1] = lab.line_no
        out.lines[n - 1] = (lab.start, lab.end)
    out.pauses.sort()
    return out


def format_labels(rows: list[tuple[float, float, str]]) -> str:
    """Rows in Audacity's export format, sorted by start time as Audacity writes them."""
    return "".join(f"{s:.6f}\t{e:.6f}\t{text}\n" for s, e, text in sorted(rows, key=lambda r: (r[0], r[1])))


# ---- mark ids -------------------------------------------------------------------

def mark_id(key: tuple) -> str:
    """The id of a mark given its key in compare._key_marks: ("KEY", line), (kind, line, word_index),
    ("section", name) or ("DEFINE", term), with 0-based lines."""
    kind = key[0]
    if kind == "KEY":
        return f"KEY:L{key[1] + 1}"
    if kind in ("/", "//"):
        return f"{kind}:L{key[1] + 1}:W{key[2]}"
    if kind in ("section", "DEFINE"):
        return f"{kind}:{key[1]}"
    raise ValueError(f"unknown mark kind {kind!r}")


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


def canonical(key: tuple) -> tuple:
    """A _key_marks key in the form used for matching: names and terms compared ignoring case and spacing."""
    return (key[0], _fold(key[1])) if key[0] in ("section", "DEFINE") else tuple(key)


def parse_mark_id(text: str) -> tuple:
    """A mark id -> its matching key (as canonical() gives for the app's marks). Raises ValueError."""
    s = text.strip()
    if m := KEY_ID_RE.match(s):
        line = int(m.group(1))
        if line >= 1:
            return ("KEY", line - 1)
    elif m := PAUSE_ID_RE.match(s):
        line = int(m.group(2))
        if line >= 1:
            return (m.group(1), line - 1, int(m.group(3)))
    elif (m := NAMED_ID_RE.match(s)) and m.group(2).strip():
        kind = "section" if m.group(1).lower() == "section" else "DEFINE"
        return (kind, _fold(m.group(2)))
    raise ValueError(f"{text!r} is not a mark id (expected KEY:L6, /:L3:W4, //:L6:W8, section:Name or DEFINE:term; "
                     "lines count from 1)")


def script_mark_ids(script: Script) -> list[str]:
    """Every mark the app will report for this script, in script order (sections before their lines)."""
    out: list[str] = []
    defined: set[str] = set()
    for sec in script.sections:
        out.append(mark_id(("section", sec.name or "Untitled")))
        for ln in script.section_lines(sec):
            if ln.is_key:
                out.append(mark_id(("KEY", ln.index)))
            out.extend(mark_id((p.kind, ln.index, p.word_index)) for p in ln.pauses)
            for d in script.defines:
                if d.line == ln.index and _fold(d.term) not in defined:
                    defined.add(_fold(d.term))
                    out.append(mark_id(("DEFINE", d.term)))
    return out


# ---- statuses.csv ---------------------------------------------------------------

@dataclass(frozen=True)
class HumanStatus:
    mark: str     # the id as written
    status: str   # normalized: lower case, spaces as underscores


def parse_statuses(text: str, source: str = "statuses.csv") -> dict[tuple, HumanStatus]:
    """`mark,status` rows -> {matching key: HumanStatus}. A header row and `#` comment rows are skipped."""
    out: dict[tuple, HumanStatus] = {}
    reader = csv.reader(io.StringIO(text))
    first = True
    for row in reader:
        no = reader.line_num
        if not row or not "".join(row).strip() or row[0].lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in row]
        if first and [c.lower() for c in cells] == ["mark", "status"]:
            first = False
            continue
        first = False
        if len(cells) != 2:
            raise ValueError(f"{source} line {no}: expected mark,status (put a mark id that contains a comma in "
                             f"double quotes), got {row!r}")
        try:
            key = parse_mark_id(cells[0])
        except ValueError as exc:
            raise ValueError(f"{source} line {no}: {exc}") from None
        status = "_".join(cells[1].lower().split())
        allowed = STATUSES[key[0]]
        if status not in allowed:
            raise ValueError(f"{source} line {no}: {cells[1]!r} is not a status of a {key[0]} mark; "
                             f"use one of {', '.join(sorted(allowed))}")
        if key in out:
            raise ValueError(f"{source} line {no}: {cells[0]} already has a status ({out[key].mark})")
        out[key] = HumanStatus(mark=cells[0], status=status)
    return out


def format_statuses(rows: list[tuple[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["mark", "status"])
    w.writerows(rows)
    return buf.getvalue()
