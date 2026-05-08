from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


class LLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return assistant text for chat messages."""


@dataclass
class OpenAICompatibleLLM:
    """Minimal OpenAI-compatible chat client using only Python stdlib."""

    model: str = field(default_factory=lambda: os.getenv("MINIBOT_MODEL", "gpt-4o-mini"))
    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    temperature: float = 0.2

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise RuntimeError("Please set OPENAI_API_KEY before using minibot.")

        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


class FakeLLM:
    """Tiny scripted LLM for tests and demos."""

    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self.replies:
            return '{"thought":"done","final":"No scripted reply left."}'
        return self.replies.pop(0)
