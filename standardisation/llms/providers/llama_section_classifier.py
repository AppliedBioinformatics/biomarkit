"""LLM section classifier using a local Ollama / OpenAI-compatible endpoint."""
import logging
from typing import Optional

from openai import OpenAI

from config import LLM_BASE_URL, LLM_MODEL_NAME
from standardisation.llms.section_classifier_base import SectionClassifierBase


class LlamaSectionClassifier(SectionClassifierBase):
    """Section classifier backed by a local Ollama endpoint (or any OpenAI-compatible server)."""

    def __init__(self, max_tokens: int = 1024):
        super().__init__(model=LLM_MODEL_NAME)
        self.max_tokens = max_tokens
        self.client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")

    def _complete(self, system: str, user: str, response_schema: Optional[dict] = None) -> str:
        # Constrained decoding: Ollama honours an OpenAI-style json_schema
        # response_format, forcing valid JSON whose values are limited to the
        # allowed action enum. This eliminates the malformed-JSON and
        # invalid-action failures that the retry loop previously absorbed.
        kwargs = {}
        if response_schema is not None:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": response_schema}

        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        raw = response.choices[0].message.content
        logging.debug(f"[LlamaSectionClassifier] finish_reason={response.choices[0].finish_reason}")

        # Strip markdown code fences that some models wrap JSON in
        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [ln for ln in lines if not ln.startswith("```")]
            raw = "\n".join(lines)

        return raw
