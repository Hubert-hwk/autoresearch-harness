from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60


class OpenAICompatibleClient:
    """Minimal stdlib client for OpenAI-compatible chat-completions APIs."""

    def __init__(self, config: OpenAICompatibleConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        api_key = os.environ.get("AUTORESEARCH_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("AUTORESEARCH_LLM_MODEL", "gpt-4.1-mini")
        base_url = os.environ.get("AUTORESEARCH_LLM_BASE_URL", "https://api.openai.com/v1")
        if not api_key:
            raise RuntimeError(
                "Missing LLM API key. Set AUTORESEARCH_LLM_API_KEY or OPENAI_API_KEY."
            )
        return cls(OpenAICompatibleConfig(api_key=api_key, model=model, base_url=base_url))

    def complete(self, messages: list[LLMMessage]) -> str:
        payload = {
            "model": self.config.model,
            "messages": [message.__dict__ for message in messages],
            "temperature": 0.2,
        }
        request = urllib.request.Request(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API request failed: {exc.code} {body}") from exc
        return data["choices"][0]["message"]["content"]
