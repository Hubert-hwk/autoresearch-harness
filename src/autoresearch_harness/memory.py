from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryManager:
    """JSONL-backed project memory for lessons and agent decisions."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, record: dict[str, Any]) -> Path:
        path = self.memory_dir / f"{stream}.jsonl"
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            **_json_ready(record),
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def record_hypothesis(self, hypothesis: Any) -> Path:
        return self.append("hypotheses", {"hypothesis": hypothesis})

    def record_decision(self, decision: dict[str, Any]) -> Path:
        return self.append("decisions", decision)

    def record_lesson(self, lesson: dict[str, Any]) -> Path:
        return self.append("lessons", lesson)

    def read_stream(self, stream: str, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.memory_dir / f"{stream}.jsonl"
        if not path.exists():
            return []
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if limit is None:
            return records
        return records[-limit:]

    def recent_lessons(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.read_stream("lessons", limit=limit)


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
