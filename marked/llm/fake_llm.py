"""Development-only stand-in for the LLM, enabled with MARKED_LLM=fake.

It exists so the suggestion review UI can be exercised without a key. It is
not a fallback: without MARKED_LLM=fake and without a key, suggestions stay
disabled, as the product requires. Its proposals are crude on purpose and the
UI labels the provider as "fake".
"""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    name = "fake (development stand-in, not a real model)"
    model = "none"
    available = True

    def complete_structured(self, system: str, user: str, output: type[T], max_tokens: int = 16000) -> T | None:
        if output.__name__ == "Proposal":
            return output.model_validate(self._proposal(user))  # type: ignore[return-value]
        if output.__name__ == "ImprovCoachOutput":
            return output.model_validate(self._improv_coach(user))  # type: ignore[return-value]
        if output.__name__ == "ContentReview":
            return output.model_validate(self._content_review(user))  # type: ignore[return-value]
        return None  # define checks fall back to the heuristic

    @staticmethod
    def _improv_coach(user: str) -> dict:
        import json
        try:
            data = json.loads(user[user.index("{"): user.rindex("}") + 1])
        except ValueError:
            return {"suggestions": []}
        f, e = data.get("fillers", {}), data.get("engagement", {})
        out = [{"focus": "fillers", "metric": f"{f.get('per_100')} per 100 words",
                "text": f"(fake) You used {f.get('count')} fillers, {f.get('per_100')} per 100 words. Swap each for a silent beat."}]
        if e.get("pitch_range_st") is not None:
            out.append({"focus": "engagement", "metric": f"{e['pitch_range_st']} semitones",
                        "text": f"(fake) Pitch range was {e['pitch_range_st']} semitones; lift the key word of each sentence."})
        out.append({"focus": "confidence", "metric": "", "text": "(fake) Sound more confident."})  # no number: dropped by code
        return {"suggestions": out}

    @staticmethod
    def _content_review(user: str) -> dict:
        m = re.search(r'"""\n(.*)\n"""', user, flags=re.S)
        words = (m.group(1) if m else "").split()
        first, last = " ".join(words[:6]), " ".join(words[-6:])
        mid = " ".join(words[len(words) // 2: len(words) // 2 + 5])
        topic = re.search(r"^Topic: (.*)$", user, flags=re.M)
        return {
            "hook": {"verdict": "weak", "note": "(fake) The opening states the topic instead of making us curious.", "evidence_quote": first},
            "on_topic": {"verdict": "present", "note": "(fake) Stays with the topic throughout.", "evidence_quote": mid},
            "suspense": {"verdict": "present", "note": "(fake) This quote is invented, so code should drop this item.", "evidence_quote": "a sentence nobody said"},
            "ending": {"verdict": "weak", "note": "(fake) The last line trails off rather than closing.", "evidence_quote": last},
            "rewrite_opening": f"(fake) What if everything you thought about {topic.group(1) if topic else 'this'} was only half the story?",
        }

    @staticmethod
    def _proposal(user: str) -> dict:
        lines = re.findall(r"^(\d+): (.*)$", user, flags=re.M)
        marks: list[dict] = []
        if not lines:
            return {"marks": []}
        n = len(lines)
        has_sections = "already has sections" in user
        if not has_sections and n >= 6:
            marks.append({"type": "section", "line_index": n // 3, "name": "Methods", "reason": "The approach starts here; a budget keeps methods from squeezing the ending."})
            marks.append({"type": "section", "line_index": 2 * n // 3, "name": "Results", "reason": "Results deserve their own time; budgets make the trade-off visible."})
        # KEY: a line in the last third that mentions a result-like word, else the longest there.
        tail = [(int(i), t) for i, t in lines if int(i) >= 2 * n // 3]
        key = next(((i, t) for i, t in tail if re.search(r"\b(predict|found|show|result|increase|decrease|accura)", t, re.I)), None) or max(tail, key=lambda x: len(x[1]), default=None)
        if key:
            i, t = key
            marks.append({"type": "key", "line_index": i, "reason": "This sentence carries the finding; slowing down lets the audience register the number."})
            marks.append({"type": "long_pause", "line_index": i, "word_index": len(t.split()), "reason": "A long pause after the finding lets it land before you move on."})
        # A short pause before a contrast word somewhere.
        for i, t in lines:
            m = re.search(r"\b(but|yet|however)\b", t, re.I)
            if m:
                wi = len(t[: m.start()].split())
                marks.append({"type": "pause", "line_index": int(i), "word_index": wi, "reason": "A beat before the contrast word makes the turn in the argument audible."})
                break
        # DEFINE: a lowercase multi-word technical-looking phrase.
        for i, t in lines:
            m = re.search(r"\b([a-z]+ (?:heating|boosted|neural|learning|regression|entropy|gradient|convolution)[a-z]* ?[a-z]*)\b", t)
            if m:
                marks.append({"type": "define", "line_index": int(i), "term": m.group(1).strip(), "reason": "Most listeners outside your subfield will not know this term; say what it means first."})
                break
        # Deliberate over-marking so the caps visibly do their job in the UI.
        for i, _t in lines[:6]:
            marks.append({"type": "key", "line_index": int(i), "reason": "Over-marked on purpose; the app's caps should drop most of these."})
        return {"marks": marks}
