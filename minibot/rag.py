from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    source: str
    text: str


class SimpleRAG:
    """Small RAG engine: load files, split chunks, keyword retrieve."""

    def __init__(self, docs_dir: Path = Path("data/docs"), chunk_size: int = 500, overlap: int = 80):
        self.docs_dir = docs_dir
        self.chunk_size = chunk_size
        self.overlap = overlap

    def load(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        for path in self.docs_dir.rglob("*"):
            if path.suffix.lower() not in {".md", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks.extend(self.split(text, str(path)))
        return chunks

    def split(self, text: str, source: str) -> list[Chunk]:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return []
        step = max(1, self.chunk_size - self.overlap)
        return [
            Chunk(source=source, text=text[i:i + self.chunk_size])
            for i in range(0, len(text), step)
        ]

    def search(self, query: str, limit: int = 3) -> list[Chunk]:
        words = [w.lower() for w in re.findall(r"[\w\u4e00-\u9fff]+", query)]
        scored = []
        for chunk in self.load():
            lower = chunk.text.lower()
            score = sum(lower.count(w) for w in words)
            if score:
                scored.append((score, chunk))
        return [c for _, c in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]
