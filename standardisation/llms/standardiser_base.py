"""
Abstract base class for LLM providers used in heading classification.

Concrete providers (Ollama, vLLM, Anthropic, etc.) subclass this and implement
`_complete()`, which sends a system + user prompt to the underlying model and
returns the raw text response.

Subclasses (e.g. SectionClassifierBase) layer prompt construction, response
parsing, and validation on top of `_complete()`.
"""

from abc import ABC, abstractmethod
from typing import Optional


class StandardiserBase(ABC):
    """Abstract base for LLM-backed classifiers.

    Subclasses must implement `_complete(system, user) -> str`, which sends the
    prompt to the underlying model and returns the raw text response.
    """

    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def _complete(self, system: str, user: str, response_schema: Optional[dict] = None) -> str:
        """Send a system + user prompt to the LLM and return the raw text response.

        If ``response_schema`` is given, providers that support structured output
        should constrain the model to emit JSON matching it. Providers that do not
        support it may ignore the argument.
        """
        ...