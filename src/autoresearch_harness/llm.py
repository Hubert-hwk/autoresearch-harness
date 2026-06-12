from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


class LLMClient(Protocol):
    """Provider-agnostic interface for future model-backed research agents."""

    def complete(self, messages: list[LLMMessage]) -> str:
        """Return model text for a research planning or critique prompt."""


class NoopLLMClient:
    """Placeholder client used until a real provider adapter is configured."""

    def complete(self, messages: list[LLMMessage]) -> str:
        raise RuntimeError(
            "No LLM provider is configured. Use RuleBasedResearchAgent or add "
            "a provider-specific LLMClient implementation."
        )

