from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ResearchRegistry:
    """Durable run registry for resumable and auditable research tasks."""

    def __init__(self, research_dir: Path):
        self.research_dir = research_dir
        self.research_dir.mkdir(parents=True, exist_ok=True)

    def event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "created_at": _now(),
            "event": name,
            "payload": payload or {},
        }
        _append_jsonl(self.research_dir / "events.jsonl", record)

    def artifact(
        self,
        kind: str,
        path: Path,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "created_at": _now(),
            "kind": kind,
            "path": str(path),
            "description": description,
            "metadata": metadata or {},
        }
        _append_jsonl(self.research_dir / "artifacts.jsonl", record)

    def state(self, **updates: Any) -> dict[str, Any]:
        path = self.research_dir / "state.json"
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
        else:
            state = {
                "created_at": _now(),
                "status": "initialized",
                "phase": "initialized",
            }
        state.update(updates)
        state["updated_at"] = _now()
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state


def load_research_status(runs_dir: Path, research_id: str | None = None) -> dict[str, Any]:
    research_dir = _resolve_research_dir(runs_dir, research_id)
    state_path = research_dir / "state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"No state.json found under {research_dir}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    return {
        "research_id": research_dir.name,
        "research_dir": str(research_dir),
        "state": state,
        "events": _read_jsonl(research_dir / "events.jsonl"),
        "artifacts": _read_jsonl(research_dir / "artifacts.jsonl"),
    }


def _resolve_research_dir(runs_dir: Path, research_id: str | None) -> Path:
    if research_id:
        return runs_dir / research_id
    candidates = [
        path
        for path in runs_dir.glob("agentic_*")
        if path.is_dir() and (path / "state.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError(f"No agentic research runs found under {runs_dir}")
    return sorted(candidates, key=lambda path: path.name)[-1]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

