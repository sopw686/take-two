"""[DEFINE: term] checks. Filled in at milestone 3; this stub reports terms as unchecked."""

from __future__ import annotations

from marked.marks import Script
from marked.stt.base import Transcript


def check_defines(script: Script, transcript: Transcript, line_rows: list[dict]) -> list[dict]:
    return [{"term": d.term, "line": d.line, "section": d.section, "status": "not_checked",
             "method": "none"} for d in script.defines]
