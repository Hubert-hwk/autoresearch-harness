from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


EVENT_SCHEMA_VERSION = "experiment.event.v1"
GRAPH_SCHEMA_VERSION = "experiment_graph.v1"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_TRANSITIONS = {
    "planned": {"workspace_prepared", "running", "failed", "cancelled"},
    "workspace_prepared": {"running", "failed", "cancelled"},
    "running": {"evaluated", "failed", "cancelled"},
    "evaluated": {"accepted", "rejected", "needs_review", "failed"},
    "needs_review": {"running", "accepted", "rejected", "failed", "cancelled"},
    "accepted": set(),
    "rejected": set(),
    "failed": set(),
    "cancelled": set(),
}


@dataclass(frozen=True)
class ExperimentEvent:
    sequence: int
    event_id: str
    graph_id: str
    node_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    previous_event_hash: str | None
    event_hash: str
    schema_version: str = EVENT_SCHEMA_VERSION


@dataclass(frozen=True)
class ExperimentNode:
    node_id: str
    graph_id: str
    parent_ids: tuple[str, ...]
    hypothesis: dict[str, Any]
    mutation: dict[str, Any]
    base_commit: str
    workspace: dict[str, Any] | None
    fidelity: dict[str, Any]
    budget_spent: dict[str, float]
    status: str
    evaluation_bundle: dict[str, Any] | None
    decision: dict[str, Any] | None
    feedback: tuple[dict[str, Any], ...]
    artifact_refs: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass
class _NodeProjection:
    node_id: str
    graph_id: str
    parent_ids: list[str]
    hypothesis: dict[str, Any]
    mutation: dict[str, Any]
    base_commit: str
    workspace: dict[str, Any] | None
    fidelity: dict[str, Any]
    budget_spent: dict[str, float] = field(default_factory=dict)
    status: str = "planned"
    evaluation_bundle: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    feedback: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def freeze(self) -> ExperimentNode:
        return ExperimentNode(
            node_id=self.node_id,
            graph_id=self.graph_id,
            parent_ids=tuple(self.parent_ids),
            hypothesis=deepcopy(self.hypothesis),
            mutation=deepcopy(self.mutation),
            base_commit=self.base_commit,
            workspace=deepcopy(self.workspace),
            fidelity=deepcopy(self.fidelity),
            budget_spent=deepcopy(self.budget_spent),
            status=self.status,
            evaluation_bundle=deepcopy(self.evaluation_bundle),
            decision=deepcopy(self.decision),
            feedback=tuple(deepcopy(self.feedback)),
            artifact_refs=tuple(self.artifact_refs),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ExperimentGraphStore:
    """Append-only, hash-chained experiment graph with rebuildable node views."""

    def __init__(self, graph_dir: Path, graph_id: str):
        _validate_id(graph_id, "graph_id")
        self.graph_dir = graph_dir
        self.graph_id = graph_id
        self.events_path = graph_dir / "experiment_events.jsonl"
        self.snapshot_path = graph_dir / "experiment_graph.json"
        graph_dir.mkdir(parents=True, exist_ok=True)
        self.rebuild(write_snapshot=False)

    def create_node(
        self,
        node_id: str,
        *,
        parent_ids: list[str] | None = None,
        hypothesis: dict[str, Any] | None = None,
        mutation: dict[str, Any] | None = None,
        base_commit: str,
        workspace: dict[str, Any] | None = None,
        fidelity: dict[str, Any] | None = None,
        status: str = "planned",
        event_id: str | None = None,
    ) -> ExperimentNode:
        _validate_id(node_id, "node_id")
        if not isinstance(base_commit, str) or not base_commit.strip():
            raise ValueError("base_commit must be a non-empty string")
        if status not in {"planned", "workspace_prepared"}:
            raise ValueError("new nodes must start as planned or workspace_prepared")
        parents = parent_ids or []
        if len(parents) != len(set(parents)) or node_id in parents:
            raise ValueError("parent_ids must be unique and may not contain node_id")
        nodes = self.rebuild(write_snapshot=False)
        if node_id in nodes:
            raise ValueError(f"experiment node already exists: {node_id}")
        missing = [parent for parent in parents if parent not in nodes]
        if missing:
            raise ValueError(f"parent nodes must exist before child creation: {missing}")
        self._append(
            node_id,
            "node_created",
            {
                "parent_ids": parents,
                "hypothesis": hypothesis or {},
                "mutation": mutation or {},
                "base_commit": base_commit,
                "workspace": workspace,
                "fidelity": fidelity or {},
                "status": status,
            },
            event_id,
        )
        return self.get_node(node_id)

    def transition(
        self,
        node_id: str,
        status: str,
        *,
        reason: str = "",
        event_id: str | None = None,
    ) -> ExperimentNode:
        node = self.get_node(node_id)
        if status not in _TRANSITIONS.get(node.status, set()):
            raise ValueError(f"invalid node status transition: {node.status} -> {status}")
        self._append(
            node_id,
            "status_changed",
            {"from": node.status, "to": status, "reason": reason},
            event_id,
        )
        return self.get_node(node_id)

    def attach_evaluation(
        self,
        node_id: str,
        evaluation_bundle: dict[str, Any],
        *,
        feedback: list[dict[str, Any]] | None = None,
        event_id: str | None = None,
    ) -> ExperimentNode:
        node = self.get_node(node_id)
        if node.status != "running":
            raise ValueError("evaluation may only be attached to a running node")
        self._append(
            node.node_id,
            "evaluation_attached",
            {"evaluation_bundle": evaluation_bundle, "feedback": feedback or []},
            event_id,
        )
        return self.get_node(node_id)

    def record_budget(
        self,
        node_id: str,
        budget_spent: dict[str, float],
        *,
        event_id: str | None = None,
    ) -> ExperimentNode:
        if not budget_spent or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
            for value in budget_spent.values()
        ):
            raise ValueError("budget_spent must contain non-negative numeric values")
        node = self.get_node(node_id)
        if node.status not in {"running", "evaluated", "failed"}:
            raise ValueError("budget may only be recorded after node execution starts")
        self._append(
            node.node_id,
            "budget_recorded",
            {"budget_spent": budget_spent},
            event_id,
        )
        return self.get_node(node_id)

    def attach_decision(
        self,
        node_id: str,
        decision: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> ExperimentNode:
        node = self.get_node(node_id)
        if node.status not in {"evaluated", "needs_review"}:
            raise ValueError("decision may only be attached to an evaluated node")
        self._append(
            node.node_id,
            "decision_attached",
            {"decision": decision},
            event_id,
        )
        return self.get_node(node_id)

    def attach_artifacts(
        self,
        node_id: str,
        artifact_refs: list[str],
        *,
        event_id: str | None = None,
    ) -> ExperimentNode:
        if not artifact_refs or not all(isinstance(item, str) and item for item in artifact_refs):
            raise ValueError("artifact_refs must be a non-empty string array")
        self._append(
            self.get_node(node_id).node_id,
            "artifacts_attached",
            {"artifact_refs": artifact_refs},
            event_id,
        )
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> ExperimentNode:
        nodes = self.rebuild(write_snapshot=False)
        if node_id not in nodes:
            raise KeyError(f"unknown experiment node: {node_id}")
        return nodes[node_id]

    def rebuild(self, *, write_snapshot: bool = True) -> dict[str, ExperimentNode]:
        events = self._load_events()
        projections: dict[str, _NodeProjection] = {}
        for event in events:
            self._apply_event(projections, event)
        nodes = {node_id: projection.freeze() for node_id, projection in projections.items()}
        if write_snapshot:
            snapshot = {
                "schema_version": GRAPH_SCHEMA_VERSION,
                "graph_id": self.graph_id,
                "event_count": len(events),
                "head_event_hash": events[-1].event_hash if events else None,
                "nodes": [asdict(node) for node in nodes.values()],
            }
            _atomic_write_json(self.snapshot_path, snapshot)
        return nodes

    def snapshot(self) -> dict[str, Any]:
        self.rebuild(write_snapshot=True)
        return json.loads(self.snapshot_path.read_text(encoding="utf-8"))

    def _append(
        self,
        node_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None,
    ) -> ExperimentEvent:
        events = self._load_events()
        resolved_event_id = event_id or f"evt_{uuid4().hex}"
        _validate_id(resolved_event_id, "event_id")
        for existing in events:
            if existing.event_id == resolved_event_id:
                if (
                    existing.node_id == node_id
                    and existing.event_type == event_type
                    and existing.payload == payload
                ):
                    return existing
                raise ValueError(f"event_id already exists with different content: {event_id}")
        created_at = datetime.now(timezone.utc).isoformat()
        body = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_id": resolved_event_id,
            "graph_id": self.graph_id,
            "node_id": node_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": created_at,
            "previous_event_hash": events[-1].event_hash if events else None,
        }
        event = ExperimentEvent(**body, event_hash=_event_hash(body))
        candidate = [*events, event]
        projections: dict[str, _NodeProjection] = {}
        for item in candidate:
            self._apply_event(projections, item)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
            file.flush()
            os.fsync(file.fileno())
        self.rebuild(write_snapshot=True)
        return event

    def _load_events(self) -> list[ExperimentEvent]:
        if not self.events_path.exists():
            return []
        events: list[ExperimentEvent] = []
        seen_ids: set[str] = set()
        previous_hash: str | None = None
        for line_number, line in enumerate(
            self.events_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                event = ExperimentEvent(**data)
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"invalid experiment event at line {line_number}") from exc
            if event.schema_version != EVENT_SCHEMA_VERSION:
                raise ValueError(f"unsupported event schema at line {line_number}")
            if event.graph_id != self.graph_id:
                raise ValueError(f"event graph_id mismatch at line {line_number}")
            if event.sequence != len(events) + 1:
                raise ValueError(f"event sequence discontinuity at line {line_number}")
            if event.event_id in seen_ids:
                raise ValueError(f"duplicate event_id at line {line_number}")
            if event.previous_event_hash != previous_hash:
                raise ValueError(f"event hash chain is broken at line {line_number}")
            body = asdict(event)
            recorded_hash = body.pop("event_hash")
            if _event_hash(body) != recorded_hash:
                raise ValueError(f"event content hash mismatch at line {line_number}")
            events.append(event)
            seen_ids.add(event.event_id)
            previous_hash = event.event_hash
        return events

    def _apply_event(
        self,
        projections: dict[str, _NodeProjection],
        event: ExperimentEvent,
    ) -> None:
        payload = event.payload
        if event.event_type == "node_created":
            if event.node_id in projections:
                raise ValueError(f"duplicate node creation: {event.node_id}")
            parents = payload["parent_ids"]
            missing = [parent for parent in parents if parent not in projections]
            if missing:
                raise ValueError(f"node references unavailable parents: {missing}")
            projections[event.node_id] = _NodeProjection(
                node_id=event.node_id,
                graph_id=self.graph_id,
                parent_ids=list(parents),
                hypothesis=deepcopy(payload["hypothesis"]),
                mutation=deepcopy(payload["mutation"]),
                base_commit=payload["base_commit"],
                workspace=deepcopy(payload.get("workspace")),
                fidelity=deepcopy(payload["fidelity"]),
                status=payload["status"],
                created_at=event.created_at,
                updated_at=event.created_at,
            )
            return
        if event.node_id not in projections:
            raise ValueError(f"event references unknown node: {event.node_id}")
        node = projections[event.node_id]
        if event.event_type == "status_changed":
            if payload["from"] != node.status or payload["to"] not in _TRANSITIONS[node.status]:
                raise ValueError(f"invalid replayed status transition for {event.node_id}")
            node.status = payload["to"]
        elif event.event_type == "evaluation_attached":
            if node.status != "running":
                raise ValueError(f"evaluation attached outside running state: {event.node_id}")
            if node.evaluation_bundle is not None:
                raise ValueError(f"evaluation already attached: {event.node_id}")
            node.evaluation_bundle = deepcopy(payload["evaluation_bundle"])
            node.feedback.extend(deepcopy(payload["feedback"]))
        elif event.event_type == "budget_recorded":
            if node.status not in {"running", "evaluated", "failed"}:
                raise ValueError(f"budget recorded before execution: {event.node_id}")
            if node.budget_spent:
                raise ValueError(f"budget already recorded: {event.node_id}")
            node.budget_spent = {
                key: float(value) for key, value in payload["budget_spent"].items()
            }
        elif event.event_type == "decision_attached":
            if node.status not in {"evaluated", "needs_review"}:
                raise ValueError(f"decision attached before evaluation: {event.node_id}")
            if node.decision is not None:
                raise ValueError(f"decision already attached: {event.node_id}")
            node.decision = deepcopy(payload["decision"])
        elif event.event_type == "artifacts_attached":
            for artifact in payload["artifact_refs"]:
                if artifact not in node.artifact_refs:
                    node.artifact_refs.append(artifact)
        else:
            raise ValueError(f"unsupported experiment event type: {event.event_type}")
        node.updated_at = event.created_at


def rebuild_experiment_graph(graph_dir: Path) -> dict[str, Any]:
    """Discover a graph from its event source, validate it, and rebuild its view."""
    return open_experiment_graph(graph_dir).snapshot()


def open_experiment_graph(
    graph_dir: Path,
    graph_id: str | None = None,
) -> ExperimentGraphStore:
    """Open an existing graph, discovering its id from the append-only source."""
    if graph_id is not None:
        return ExperimentGraphStore(graph_dir, graph_id)
    events_path = graph_dir / "experiment_events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"no experiment event source found under {graph_dir}")
    first_line = next(
        (line for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()),
        None,
    )
    if first_line is None:
        raise ValueError("experiment event source is empty")
    try:
        graph_id = json.loads(first_line)["graph_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("cannot discover graph_id from experiment event source") from exc
    return ExperimentGraphStore(graph_dir, graph_id)


def _event_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe 1-128 character identifier")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
