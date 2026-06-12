from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProvenanceRecord:
    artifact_id: str
    kind: str
    path: str
    produced_by: str
    depends_on: list[str] = field(default_factory=list)
    supports: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProvenanceRecorder:
    """JSONL evidence graph for research artifacts."""

    def __init__(self, research_dir: Path):
        self.path = research_dir / "provenance.jsonl"

    def record(
        self,
        artifact_id: str,
        kind: str,
        path: Path,
        produced_by: str,
        depends_on: list[str] | None = None,
        supports: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvenanceRecord:
        if any(record.get("artifact_id") == artifact_id for record in load_provenance(self.path.parent)):
            return [
                ProvenanceRecord(**record)
                for record in load_provenance(self.path.parent)
                if record.get("artifact_id") == artifact_id
            ][0]
        record = ProvenanceRecord(
            artifact_id=artifact_id,
            kind=kind,
            path=str(path),
            produced_by=produced_by,
            depends_on=depends_on or [],
            supports=supports or [],
            metadata=metadata or {},
        )
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record


def load_provenance(research_dir: Path) -> list[dict[str, Any]]:
    path = research_dir / "provenance.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def evidence_for(
    records: list[dict[str, Any]],
    artifact_id: str,
) -> list[dict[str, Any]]:
    by_id = {record["artifact_id"]: record for record in records}
    seen: set[str] = set()
    ordered: list[dict[str, Any]] = []

    def visit(current_id: str) -> None:
        if current_id in seen or current_id not in by_id:
            return
        seen.add(current_id)
        record = by_id[current_id]
        ordered.append(record)
        for dependency in record.get("depends_on", []):
            visit(dependency)

    visit(artifact_id)
    return ordered
