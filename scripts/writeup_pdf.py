"""WRITEUP.md -> WRITEUP.pdf, one US Letter page, printed by the installed Google Chrome.

    uv run python scripts/writeup_pdf.py           # build once; fails if it is over one page or misses a section
    uv run python scripts/writeup_pdf.py --watch   # rebuild every time WRITEUP.md is saved (Ctrl+C to stop)

The submission allows one page and requires these sections: the problem, who it's for, why voice,
how it's built, what's next, and which AI tools were used and how. Both are checked on every build.
Chrome is driven through Playwright (already a dev dependency for the browser test), so no PDF
library is added. The Markdown reader covers what the write-up uses: # and ## headings,
paragraphs, "- " bullets, **bold**, *italic*, `code` and [links](url).
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "WRITEUP.md"
TARGET = ROOT / "WRITEUP.pdf"

# (what the submission asks for, words one of the ## headings must contain)
REQUIRED = [
    ("the problem", ("problem",)),
    ("who it's for", ("who",)),
    ("why voice", ("why voice",)),
    ("how it's built", ("built",)),
    ("what's next", ("next",)),
    ("AI tools used and how", ("ai tool",)),
]

CSS = """
@page { size: Letter; margin: 0.55in 0.65in; }
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.36; color: #111; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 4pt; }
h2 { font-size: 11.5pt; margin: 9pt 0 2pt; }
p { margin: 0 0 4pt; }
ul { margin: 0 0 4pt; padding-left: 15pt; }
li { margin: 0 0 1.5pt; }
code { font-family: Consolas, "Courier New", monospace; font-size: 9pt; }
a { color: inherit; }
"""


def _inline(text: str) -> str:
    s = html.escape(text, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def to_html(md: str, title: str = "Take Two: write-up") -> str:
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif m := re.match(r"^(#{1,3})\s+(.*)$", line):
            flush()
            n = len(m.group(1))
            out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif line.startswith(("- ", "* ")):
            if para:
                flush()
            items.append(line[2:])
        elif items:  # a wrapped bullet continues the last item
            items[-1] += " " + line
        else:
            para.append(line)
    flush()
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{CSS}</style></head><body>{''.join(out)}</body></html>")


def missing_sections(md: str) -> list[str]:
    heads = [h.lower().replace("’", "'") for h in re.findall(r"^##\s+(.*)$", md, re.MULTILINE)]
    return [name for name, keys in REQUIRED if not any(k in h for h in heads for k in keys)]


def page_count(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf))


def build(source: Path = SOURCE, target: Path = TARGET) -> tuple[int, list[str]]:
    """Write the PDF; return (pages, missing sections)."""
    from playwright.sync_api import sync_playwright
    md = source.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        try:
            page = browser.new_page()
            page.set_content(to_html(md), wait_until="load")
            pdf = page.pdf(format="Letter", print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()
    try:
        target.write_bytes(pdf)
    except PermissionError:
        raise SystemExit(f"{target.name} is open in another program (a PDF viewer?). Close it and build again.") from None
    return page_count(pdf), missing_sections(md)


def report(pages: int, missing: list[str], target: Path = TARGET) -> bool:
    ok = pages == 1 and not missing
    print(f"{target.name}: {pages} page{'s' if pages != 1 else ''}"
          + ("" if pages == 1 else "  <-- over the one-page limit: cut text in WRITEUP.md"))
    if missing:
        print("Missing sections (a ## heading must name each): " + ", ".join(missing))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", action="store_true", help="rebuild whenever WRITEUP.md is saved")
    ap.add_argument("--out", type=Path, default=TARGET, help="where to write the PDF (default WRITEUP.pdf)")
    args = ap.parse_args()
    if not args.watch:
        return 0 if report(*build(SOURCE, args.out), args.out) else 1
    print(f"Watching {SOURCE.name}; save it to rebuild {args.out.name}. Ctrl+C to stop.")
    seen = 0.0
    try:
        while True:
            mtime = SOURCE.stat().st_mtime
            if mtime != seen:
                seen = mtime
                try:
                    report(*build(SOURCE, args.out), args.out)
                except (Exception, SystemExit) as exc:  # keep watching through a bad save or a busy PDF viewer
                    print(f"Build failed: {exc}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
