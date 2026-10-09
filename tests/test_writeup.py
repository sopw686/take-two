"""The write-up the submission asks for: every required section, and one page once printed."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("writeup_pdf", ROOT / "scripts" / "writeup_pdf.py")
writeup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(writeup)


def test_writeup_has_every_required_section():
    assert writeup.missing_sections((ROOT / "WRITEUP.md").read_text(encoding="utf-8")) == []


def test_missing_sections_are_named():
    md = "# T\n\n## The problem\n\nx\n\n## Who it's for\n\n## Why voice\n\n## How it's built\n"
    assert writeup.missing_sections(md) == ["what's next", "AI tools used and how"]


def test_markdown_reader_covers_what_the_writeup_uses():
    out = writeup.to_html("# Title\n\nOne *two* **three** `four` [five](https://x.y) <b>.\n\n- a\n- b\n  wrapped\n\n## Next\nend")
    assert "<h1>Title</h1>" in out and "<h2>Next</h2>" in out
    assert "<em>two</em>" in out and "<strong>three</strong>" in out and "<code>four</code>" in out
    assert '<a href="https://x.y">five</a>' in out and "&lt;b&gt;" in out
    assert "<ul><li>a</li><li>b wrapped</li></ul>" in out


def test_page_count_reads_page_objects_not_the_page_tree():
    assert writeup.page_count(b"<< /Type /Pages /Count 2 >> << /Type /Page >> << /Type/Page >>") == 2


@pytest.mark.browser
def test_writeup_prints_on_one_page(tmp_path):
    pages, missing = writeup.build(ROOT / "WRITEUP.md", tmp_path / "w.pdf")
    assert (pages, missing) == (1, [])
