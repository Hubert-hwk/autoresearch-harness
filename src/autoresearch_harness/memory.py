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
        payload = {"hypothesis": hypothesis}
        hypothesis_id = _json_ready(hypothesis).get("id")
        return self.append_unique("hypotheses", payload, ("hypothesis", "id"), hypothesis_id)

    def record_decision(self, decision: dict[str, Any]) -> Path:
        return self.append_unique(
            "decisions",
            decision,
            ("research_id", "hypothesis_id"),
            (decision.get("research_id"), decision.get("hypothesis_id")),
        )

    def record_lesson(self, lesson: dict[str, Any]) -> Path:
        return self.append_unique(
            "lessons",
            lesson,
            ("research_id", "hypothesis_id"),
            (lesson.get("research_id"), lesson.get("hypothesis_id")),
        )

    def append_unique(
        self,
        stream: str,
        record: dict[str, Any],
        key_path: tuple[str, ...],
        key_value: Any,
    ) -> Path:
        path = self.memory_dir / f"{stream}.jsonl"
        if key_value is not None:
            for existing in self.read_stream(stream):
                if _get_nested(existing, key_path) == key_value:
                    return path
        return self.append(stream, record)

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


def _get_nested(record: dict[str, Any], key_path: tuple[str, ...]) -> Any:
    if len(key_path) > 1 and all(key in record for key in key_path):
        return tuple(record.get(key) for key in key_path)
    current: Any = record
    for key in key_path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
