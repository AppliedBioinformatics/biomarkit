import json
import logging
from typing import Optional

from openai import OpenAI

from config import LLM_BASE_URL, LLM_MODEL_NAME
from standardisation.llms.prompts import (
    INTRO_FINDER_PROMPT,
    END_FINDER_PROMPT,
    METHODS_FINDER_PROMPT,
    RESULTS_FINDER_PROMPT,
    DISCUSSION_FINDER_PROMPT,
)


class LlamaClassifier:
    def __init__(self, max_tokens: int = 1024):
        self.model = LLM_MODEL_NAME
        self.max_tokens = max_tokens
        self.client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")

    def _complete(self, system: str, user: str, response_schema: Optional[dict] = None) -> str:
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
        logging.debug(f"[LlamaClassifier] finish_reason={response.choices[0].finish_reason}")

        if raw.startswith("```"):
            lines = raw.splitlines()
            lines = [ln for ln in lines if not ln.startswith("```")]
            raw = "\n".join(lines)

        return raw

    def _build_response_schema(self, blocks_context: dict[int, str], response_key: str) -> dict:
        enum_values = [str(k) for k in blocks_context]
        return {
            "name": response_key,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    response_key: {"type": "string", "enum": enum_values}
                },
                "required": [response_key],
                "additionalProperties": False,
            },
        }

    def _classify_block(
        self,
        blocks_context: dict[int, str],
        prompt: str,
        response_key: str,
        max_retries: int = 2,
    ) -> Optional[int]:
        user_message = json.dumps({str(k): v for k, v in blocks_context.items()})
        schema = self._build_response_schema(blocks_context, response_key)
        valid_keys = {str(k) for k in blocks_context}

        for attempt in range(max_retries + 1):
            try:
                raw = self._complete(system=prompt, user=user_message, response_schema=schema)
                result = json.loads(raw)
                index_str = result[response_key]
                if index_str not in valid_keys:
                    raise ValueError(f"Returned key {index_str!r} not in input blocks")
                return int(index_str)
            except Exception as exc:
                logging.warning(f"[LlamaClassifier] {response_key} attempt {attempt + 1} failed: {exc}")

        return None

    def classify_intro(self, blocks_context: dict[int, str], max_retries: int = 2) -> Optional[int]:
        return self._classify_block(blocks_context, INTRO_FINDER_PROMPT, "introduction_index", max_retries)

    def classify_end(self, blocks_context: dict[int, str], max_retries: int = 2) -> Optional[int]:
        return self._classify_block(blocks_context, END_FINDER_PROMPT, "end_index", max_retries)

    def classify_methods(self, blocks_context: dict[int, str], max_retries: int = 2) -> Optional[int]:
        return self._classify_block(blocks_context, METHODS_FINDER_PROMPT, "methods_index", max_retries)

    def classify_results(self, blocks_context: dict[int, str], max_retries: int = 2) -> Optional[int]:
        return self._classify_block(blocks_context, RESULTS_FINDER_PROMPT, "results_index", max_retries)

    def classify_discussion(self, blocks_context: dict[int, str], max_retries: int = 2) -> Optional[int]:
        user_message = json.dumps({str(k): v for k, v in blocks_context.items()})
        valid_keys = {str(k) for k in blocks_context}

        for attempt in range(max_retries + 1):
            try:
                raw = self._complete(system=DISCUSSION_FINDER_PROMPT, user=user_message)
                result = json.loads(raw)
                index_str = result.get("discussion_index")
                if index_str is None:
                    return None
                if str(index_str) not in valid_keys:
                    raise ValueError(f"Returned key {index_str!r} not in input blocks")
                return int(index_str)
            except Exception as exc:
                logging.warning(f"[LlamaClassifier] discussion_index attempt {attempt + 1} failed: {exc}")

        return None