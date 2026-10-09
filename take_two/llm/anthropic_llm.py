"""Anthropic adapter: one structured-output call, validated into a pydantic model."""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from take_two import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic

        self.model = model
        self.available = True
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def complete_structured(self, system: str, user: str, output: type[T], max_tokens: int = 16000) -> T | None:
        import anthropic

        try:
            resp = self._client.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output,
                output_config={"effort": "medium"},
            )
        except anthropic.APIStatusError as exc:
            log.warning("Anthropic API error: %s", exc)
            return None
        except anthropic.APIConnectionError as exc:
            log.warning("Anthropic connection error: %s", exc)
            return None
        except Exception as exc:  # e.g. truncated or schema-invalid output failing to parse
            log.warning("Anthropic structured output unusable: %s", exc)
            return None
        if resp.stop_reason == "refusal":
            log.warning("Anthropic refused: %s", getattr(resp, "stop_details", None))
            return None
        if resp.stop_reason == "max_tokens":
            # Thinking counts toward max_tokens; a cut-off answer is not trustworthy.
            log.warning("Anthropic output hit max_tokens (%s)", max_tokens)
            return None
        return resp.parsed_output
