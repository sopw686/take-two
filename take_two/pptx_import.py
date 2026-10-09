"""PowerPoint speaker notes -> a Take Two script.

One section per slide, in presentation order, with the notes as lines:

    ## Slide 1: Why reefs turn white
    Good morning.
    Today I'll show you what bleaching does to a reef.

    ## Slide 2: Methods
    <!-- no notes -->

No budgets: the speaker fills those in. A hidden slide keeps its section (and PowerPoint's
numbering) with a `<!-- hidden slide -->` line under the header, so the speaker can delete
it if they will skip it. Standard library only (zipfile + ElementTree):
python-pptx needs lxml and Pillow, compiled packages, for what is a read of three kinds
of XML part. python-pptx is a dev dependency that the tests use to build real decks.

Notes are prose, not marks, so text the mark parser would misread is changed as little as
possible, keeping every word:
  - a notes line starting with ## (a Markdown heading habit) loses its leading #s, so it
    stays a line instead of starting a section;
  - a standalone / or // loses the spaces around it ("heat / light" becomes "heat/light",
    which the parser already reads as the two words), so it is not a pause mark; a line
    holding nothing but slashes is dropped;
  - "<!--" becomes "< !--" in notes and titles, so it cannot open a comment that would
    blank everything up to the next placeholder;
  - a title ending in [m:ss] gets round brackets, so it is not read as a budget.
[KEY], [DEFINE: term] and *word* pass through: they never appear in prose by accident, and
a speaker who already writes marks in their notes keeps them.

Zip bombs: the upload, the number of members, each XML part's declared size (checked
before it is read; zipfile also stops at the declared size) and the total XML read are all
capped. A part with a DOCTYPE is refused; PowerPoint never writes one, and ElementTree does
not fetch external entities anyway.
"""

from __future__ import annotations

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from urllib.parse import unquote

from take_two.marks import PAUSE_RE

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_PART_BYTES = 5 * 1024 * 1024
MAX_TOTAL_XML_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 2000

PRESENTATION = "ppt/presentation.xml"
NO_NOTES = "<!-- no notes -->"
HIDDEN = "<!-- hidden slide -->"
TITLE_TYPES = ("title", "ctrTitle")
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # compound file: an encrypted .pptx or an old .ppt
BUDGET_TAIL_RE = re.compile(r"\[(\d+:\d{1,2})\]$")
ENCRYPTED = "This presentation is password-protected. Remove the password in PowerPoint and import it again."


class PptxError(Exception):
    """A file that cannot be imported; `message` is shown to the user as is."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def too_large_message() -> str:
    return (f"The file is over the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB import limit. "
            "Save a copy without embedded videos and import that.")


class _NoDoctype(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise _DoctypeFound()


class _DoctypeFound(Exception):
    pass


class _Package:
    """Read access to the zip's XML parts, with the size guards applied to every read."""

    def __init__(self, zf: zipfile.ZipFile) -> None:
        self.zf = zf
        self.members = {i.filename.lower(): i for i in zf.infolist()}  # part names are case-insensitive
        self.read_total = 0

    def xml(self, name: str) -> ET.Element | None:
        info = self.members.get(name.lower())
        if info is None:
            return None
        if info.flag_bits & 0x1:
            raise PptxError(ENCRYPTED)
        if info.file_size > MAX_PART_BYTES:
            raise PptxError(f"The file was not opened: {name} would be larger than "
                            f"{MAX_PART_BYTES // (1024 * 1024)} MB once uncompressed, far more than slide text needs.")
        self.read_total += info.file_size
        if self.read_total > MAX_TOTAL_XML_BYTES:
            raise PptxError(f"The import stopped: the slides' text adds up to more than "
                            f"{MAX_TOTAL_XML_BYTES // (1024 * 1024)} MB once uncompressed.")
        try:
            with self.zf.open(info) as fh:
                raw = fh.read(MAX_PART_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error) as exc:
            raise PptxError(f"The file is damaged: {name} could not be read.") from exc
        if len(raw) > MAX_PART_BYTES:  # cannot happen with an honest size, but cheap to check
            raise PptxError(f"The file was not opened: {name} is larger than it says.")
        parser = ET.XMLParser(target=_NoDoctype())
        try:
            parser.feed(raw)
            return parser.close()
        except _DoctypeFound:
            raise PptxError(f"The file was not opened: {name} contains a DOCTYPE declaration, "
                            "which PowerPoint never writes.") from None
        except ET.ParseError as exc:
            raise PptxError(f"The file is damaged: {name} is not valid XML.") from exc

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """{relationship id: (type, target part name)} for the internal relationships of `part`."""
        folder, base = posixpath.split(part)
        root = self.xml(posixpath.join(folder, "_rels", base + ".rels"))
        out: dict[str, tuple[str, str]] = {}
        if root is None:
            return out
        for rel in root.findall("{*}Relationship"):
            target = rel.get("Target") or ""
            if rel.get("TargetMode") == "External" or not target:
                continue
            target = unquote(target)
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(folder, target))
            if path.startswith(".."):
                continue
            out[rel.get("Id") or ""] = (rel.get("Type") or "", path)
        return out


def notes_to_script(data: bytes) -> tuple[str, int]:
    """Return (script text, slide count) for a .pptx file's bytes. Raises PptxError."""
    if not data:
        raise PptxError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PptxError(too_large_message())
    if data.startswith(OLE_MAGIC):
        raise PptxError("This file is password-protected or is an old .ppt file. Remove the password, or save it "
                        "as .pptx in PowerPoint, and import it again.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as exc:
        raise PptxError("This is not a PowerPoint (.pptx) file.") from exc
    with zf:
        if len(zf.infolist()) > MAX_MEMBERS:
            raise PptxError(f"The file was not opened: it holds more than {MAX_MEMBERS} parts, "
                            "far more than a real presentation.")
        pkg = _Package(zf)
        pres = pkg.xml(PRESENTATION)
        if pres is None:
            raise PptxError("This file is not a PowerPoint presentation (it has no ppt/presentation.xml).")
        slide_rels = pkg.rels(PRESENTATION)
        ids = pres.findall("{*}sldIdLst/{*}sldId")
        if not ids:
            raise PptxError("The presentation has no slides.")
        sections = []
        for n, sld_id in enumerate(ids, start=1):
            rel = slide_rels.get(_rel_id(sld_id) or "")
            slide = pkg.xml(rel[1]) if rel else None
            if rel is None or slide is None:
                raise PptxError(f"The file is damaged: slide {n} is listed but missing.")
            notes: list[str] = []
            for rel_type, target in pkg.rels(rel[1]).values():
                if rel_type.endswith("/notesSlide"):
                    notes_slide = pkg.xml(target)
                    notes = _notes(notes_slide) if notes_slide is not None else []
                    break
            sections.append(_section(n, _title(slide), notes, hidden=slide.get("show") in ("0", "false")))
    return "\n\n".join(sections) + "\n", len(ids)


def _rel_id(el: ET.Element) -> str | None:
    """The r:id attribute (namespaced, unlike the numeric `id` next to it)."""
    return next((v for k, v in el.attrib.items() if k.endswith("}id")), None)


def _placeholder_type(sp: ET.Element) -> str | None:
    ph = sp.find("{*}nvSpPr/{*}nvPr/{*}ph")
    return None if ph is None else ph.get("type")


def _paragraphs(sp: ET.Element) -> list[str]:
    """Each a:p of a shape as one string: its a:t texts in order, a:br as a space, whitespace collapsed."""
    out = []
    for p in sp.findall("{*}txBody/{*}p"):
        parts = []
        for el in p.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "t":
                parts.append(el.text or "")
            elif tag == "br":
                parts.append(" ")
        out.append(" ".join("".join(parts).split()))
    return out


def _title(slide: ET.Element) -> str:
    for sp in slide.iterfind(".//{*}sp"):
        if _placeholder_type(sp) in TITLE_TYPES:
            title = " ".join(p for p in _paragraphs(sp) if p)
            if title:
                return BUDGET_TAIL_RE.sub(r"(\1)", _no_comment(title))
    return ""


def _notes(notes_slide: ET.Element) -> list[str]:
    lines = []
    for sp in notes_slide.iterfind(".//{*}sp"):
        if _placeholder_type(sp) == "body":
            lines.extend(line for line in map(neutralize_line, _paragraphs(sp)) if line)
    return lines


def _no_comment(text: str) -> str:
    return text.replace("<!--", "< !--")


def neutralize_line(text: str) -> str:
    """One notes paragraph as a script line that the mark parser reads as plain words ("" to drop it)."""
    s = re.sub(r"^#{2,}[#\s]*", "", _no_comment(" ".join(text.split())))
    words: list[str] = []
    pending = ""  # slash tokens waiting to be joined: "heat / light" -> "heat/light"
    for w in s.split():
        if PAUSE_RE.match(w):
            pending += w
        elif pending and words:
            words[-1] += pending + w
            pending = ""
        else:
            words.append(pending + w)
            pending = ""
    if pending and words:
        words[-1] += pending
    return " ".join(words)


def _section(n: int, title: str, notes: list[str], hidden: bool) -> str:
    lines = [f"## Slide {n}: {title}" if title else f"## Slide {n}"]
    if hidden:
        lines.append(HIDDEN)
    lines.extend(notes or [NO_NOTES])
    return "\n".join(lines)
