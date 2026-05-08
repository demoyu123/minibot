from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ShortTermMemory:
    max_turns: int = 6
    messages: deque[dict[str, str]] = field(default_factory=deque)

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        while len(self.messages) > self.max_turns * 2:
            self.messages.popleft()

    def context(self) -> str:
        if not self.messages:
            return "None"
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.messages)


class LongTermMemory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, text: str) -> str:
        item = {"time": datetime.now().isoformat(timespec="seconds"), "text": text}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return "saved"

    def all(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        items = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
        return items

    def search(self, query: str, limit: int = 5) -> list[str]:
        words = set(query.lower().split())
        scored = []
        for item in self.all():
            text = item["text"]
            score = sum(1 for w in words if w in text.lower())
            if score or query.lower() in text.lower():
                scored.append((score, text))
        return [text for _, text in sorted(scored, reverse=True)[:limit]]

    def context(self, limit: int = 8) -> str:
        items = self.all()[-limit:]
        return "\n".join(f"- {x['text']}" for x in items) if items else "None"


class History:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, user: str, answer: str) -> None:
        item = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "user": user,
            "assistant": answer,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


class Memory:
    """Memory facade: short-term context + durable files."""

    def __init__(self, root: Path = Path("memory")):
        self.short = ShortTermMemory()
        self.long = LongTermMemory(root / "long_term.jsonl")
        self.history = History(root / "history.jsonl")

    def build_context(self) -> str:
        return (
            "## Short-term memory\n"
            f"{self.short.context()}\n\n"
            "## Long-term memory\n"
            f"{self.long.context()}"
        )
