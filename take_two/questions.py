"""Q&A practice: likely audience questions about the speaker's own script (a talk, a defense, a pitch).

The model reads the script text only (never audio) and proposes questions, each
tagged and tied to the script line it is about. Code drops anything it cannot
check (an unknown tag, a line index outside the script, an empty or over-long
question, a duplicate) and keeps at most eight. Without a key the feature is off
with a one-line reason; there is no heuristic stand-in. Typing your own question
needs no key at all. The answer is then an ordinary Improvise take whose topic
is the question.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from take_two.marks import Script

TAGS = ("clarification", "methods challenge", "limitation", "implication")
MAX_QUESTIONS = 8
MAX_CHARS = 200  # the Improvise topic limit: the question becomes the topic


class ProposedQuestion(BaseModel):
    text: str = Field(description="One question an audience member might ask, at most 200 characters.")
    tag: str = Field(description="One of: clarification, methods challenge, limitation, implication.")
    line_index: int = Field(description="0-based index of the script line the question is about.")


class QuestionsOutput(BaseModel):
    questions: list[ProposedQuestion] = Field(description="Five to eight questions, the most likely first.")


SYSTEM = """You help a speaker prepare for the audience's questions after a talk, a thesis defense, a pitch or an interview. You receive the script of what they will say (text only). Propose five to eight questions a knowledgeable audience is likely to ask, the most likely first. Mix four kinds and tag each: clarification (a term, number or step that may be unclear), methods challenge (how it was done or how they know, whether it could be biased or confounded), limitation (what the work cannot show or where it may not hold), implication (what follows from it, what comes next). Each question must give the 0-based index of the script line it is about, and must be a single question of at most 200 characters, phrased the way a person would ask it out loud. Ask; do not answer. Do not grade or praise the script."""


def build_user_prompt(script: Script) -> str:
    return "Script (line index: text):\n" + "\n".join(f"{ln.index}: {ln.text}" for ln in script.lines)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def validate_questions(out: QuestionsOutput, script: Script) -> tuple[list[dict], list[dict]]:
    """(kept, dropped reasons with counts). Pure; fully testable."""
    kept: list[dict] = []
    dropped: dict[str, int] = {}
    seen: set[str] = set()

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for q in out.questions:
        text = " ".join(q.text.split())
        tag = " ".join(q.tag.lower().replace("-", " ").split())
        if tag not in TAGS:
            drop("unknown tag")
        elif not 0 <= q.line_index < len(script.lines):
            drop("line index outside the script")
        elif not text:
            drop("empty question")
        elif len(text) > MAX_CHARS:
            drop(f"longer than {MAX_CHARS} characters")
        elif _key(text) in seen:
            drop("duplicate")
        elif len(kept) >= MAX_QUESTIONS:
            drop(f"more than {MAX_QUESTIONS} questions")
        else:
            seen.add(_key(text))
            kept.append({"text": text, "tag": tag, "line_index": q.line_index, "line_text": script.lines[q.line_index].text})
    return kept, [{"reason": k, "count": v} for k, v in dropped.items()]
