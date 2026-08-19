from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .fingerprints import build_execution_fingerprint
from .models import TaskSpec
from .spec import load_task


MEMORY_SCHEMA_VERSION = "evidence-memory.v1"
EVENT_SCHEMA_VERSION = "evidence-memory.event.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@dataclass(frozen=True)
class EvidenceMemoryEvent:
    sequence: int
    event_id: str
    event_type: str
    memory_id: str
    payload: dict[str, Any]
    created_at: str
    previous_event_hash: str | None
    event_hash: str
    schema_version: str = EVENT_SCHEMA_VERSION


class EvidenceMemoryStore:
    """Hash-chained, append-only store for verification-backed durable knowledge."""

    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.events_path = memory_dir / "evidence_memory_events.jsonl"
        self.snapshot_path = memory_dir / "evidence_memory.json"
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.rebuild(write_snapshot=False)

    def record(
        self,
        memory: dict[str, Any],
        *,
        supersedes: list[str] | None = None,
    ) -> dict[str, Any]:
        existing = self.validate_record(memory, supersedes=supersedes)
        if existing is not None:
            return existing
        memory_id = memory["memory_id"]
        superseded_ids = supersedes or []
        payload = deepcopy(memory)
        payload["supersedes"] = superseded_ids
        self._append("memory_recorded", memory_id, {"memory": payload})
        return self.get(memory_id)

    def validate_record(
        self,
        memory: dict[str, Any],
        *,
        supersedes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Validate a proposed append and return its existing idempotent record."""
        memory_id = memory.get("memory_id")
        _validate_id(memory_id, "memory_id")
        if memory.get("schema_version") != MEMORY_SCHEMA_VERSION:
            raise ValueError(f"memory schema_version must be {MEMORY_SCHEMA_VERSION}")
        _validate_memory(memory)
        current = self.rebuild(write_snapshot=False)
        superseded_ids = supersedes or []
        if memory_id in current:
            existing = current[memory_id]
            if not _same_memory_content(existing, memory):
                raise ValueError(f"memory id already exists with different content: {memory_id}")
            if existing.get("supersedes", []) != superseded_ids:
                raise ValueError(f"memory id already exists with different supersession: {memory_id}")
            return existing
        if len(superseded_ids) != len(set(superseded_ids)):
            raise ValueError("supersedes must contain unique memory ids")
        for old_id in superseded_ids:
            if old_id not in current:
                raise ValueError(f"cannot supersede unknown memory: {old_id}")
            if current[old_id]["validity"]["status"] != "active":
                raise ValueError(f"cannot supersede inactive memory: {old_id}")
        for existing in current.values():
            if (
                existing["validity"]["status"] == "active"
                and existing["memory_id"] not in superseded_ids
                and _claims_conflict(existing, memory)
            ):
                raise ValueError(
                    "conflicting active memory requires explicit supersession: "
                    f"{existing['memory_id']}"
                )
        return None

    def invalidate(self, memory_id: str, reason: str) -> dict[str, Any]:
        memory = self.get(memory_id)
        if memory["validity"]["status"] != "active":
            raise ValueError(f"only active memory can be invalidated: {memory_id}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("invalidation reason must be non-empty")
        self._append("memory_invalidated", memory_id, {"reason": reason.strip()})
        return self.get(memory_id)

    def get(self, memory_id: str) -> dict[str, Any]:
        memories = self.rebuild(write_snapshot=False)
        if memory_id not in memories:
            raise KeyError(f"unknown evidence memory: {memory_id}")
        return memories[memory_id]

    def rebuild(self, *, write_snapshot: bool = True) -> dict[str, dict[str, Any]]:
        events = self._load_events()
        memories: dict[str, dict[str, Any]] = {}
        for event in events:
            if event.event_type == "memory_recorded":
                if event.memory_id in memories:
                    raise ValueError(f"duplicate evidence memory: {event.memory_id}")
                memory = deepcopy(event.payload["memory"])
                if memory.get("memory_id") != event.memory_id:
                    raise ValueError("evidence memory event and payload ids differ")
                _validate_memory(memory)
                for superseded_id in memory.get("supersedes", []):
                    if superseded_id not in memories:
                        raise ValueError(f"superseded memory is unavailable: {superseded_id}")
                    old = memories[superseded_id]
                    if old["validity"]["status"] != "active":
                        raise ValueError(f"superseded memory is already inactive: {superseded_id}")
                    old["validity"]["status"] = "superseded"
                    old["validity"]["superseded_by"] = event.memory_id
                    old["validity"]["updated_at"] = event.created_at
                memories[event.memory_id] = memory
            elif event.event_type == "memory_invalidated":
                if event.memory_id not in memories:
                    raise ValueError(f"invalidation references unknown memory: {event.memory_id}")
                memory = memories[event.memory_id]
                if memory["validity"]["status"] != "active":
                    raise ValueError(f"invalidation references inactive memory: {event.memory_id}")
                memory["validity"]["status"] = "invalidated"
                memory["validity"]["reason"] = event.payload["reason"]
                memory["validity"]["updated_at"] = event.created_at
            else:
                raise ValueError(f"unsupported evidence memory event: {event.event_type}")
        if write_snapshot:
            snapshot = {
                "schema_version": "evidence-memory.snapshot.v1",
                "event_count": len(events),
                "head_event_hash": events[-1].event_hash if events else None,
                "memories": list(memories.values()),
            }
            _atomic_write_json(self.snapshot_path, snapshot)
        return memories

    def snapshot(self) -> dict[str, Any]:
        self.rebuild(write_snapshot=True)
        return json.loads(self.snapshot_path.read_text(encoding="utf-8"))

    def _append(self, event_type: str, memory_id: str, payload: dict[str, Any]) -> None:
        events = self._load_events()
        body = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_id": f"evt_{uuid4().hex}",
            "event_type": event_type,
            "memory_id": memory_id,
            "payload": payload,
            "created_at": _now(),
            "previous_event_hash": events[-1].event_hash if events else None,
        }
        event = EvidenceMemoryEvent(**body, event_hash=_sha256_json(body))
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
            file.flush()
            os.fsync(file.fileno())
        self.rebuild(write_snapshot=True)

    def _load_events(self) -> list[EvidenceMemoryEvent]:
        if not self.events_path.exists():
            return []
        events: list[EvidenceMemoryEvent] = []
        previous_hash: str | None = None
        seen_ids: set[str] = set()
        for line_number, line in enumerate(
            self.events_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                event = EvidenceMemoryEvent(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                raise ValueError(f"invalid evidence memory event at line {line_number}") from exc
            if event.schema_version != EVENT_SCHEMA_VERSION:
                raise ValueError(f"unsupported evidence memory event at line {line_number}")
            if event.sequence != len(events) + 1:
                raise ValueError(f"evidence memory sequence gap at line {line_number}")
            if event.event_id in seen_ids:
                raise ValueError(f"duplicate evidence memory event id at line {line_number}")
            if event.previous_event_hash != previous_hash:
                raise ValueError(f"evidence memory hash chain is broken at line {line_number}")
            body = asdict(event)
            recorded_hash = body.pop("event_hash")
            if _sha256_json(body) != recorded_hash:
                raise ValueError(f"evidence memory content hash mismatch at line {line_number}")
            events.append(event)
            previous_hash = event.event_hash
            seen_ids.add(event.event_id)
        return events


def ingest_verification_memory(
    verification_dir: Path,
    replay_result_path: Path,
    memory_dir: Path,
    *,
    supersedes: list[str] | None = None,
    valid_days: float | None = None,
) -> dict[str, Any]:
    verification = _load_hashed_json(
        verification_dir / "verification_result.json",
        "verification_result_sha256",
    )
    replay = _load_hashed_json(replay_result_path, "replay_result_sha256")
    if verification.get("status") != "completed" or verification.get("stop_reason") != "verification_complete":
        raise ValueError("only complete verification runs can enter evidence memory")
    if verification.get("fingerprint_drift_components"):
        raise ValueError("verification fingerprint drift blocks evidence memory")
    interval = verification.get("statistics", {}).get("paired_interval")
    if interval is None:
        raise ValueError("verification lacks a paired confidence interval")
    if replay.get("status") != "matched" or not replay.get("matched"):
        raise ValueError("evidence memory requires a matched replay")
    if replay.get("drift_components") or replay.get("post_replay_drift_components"):
        raise ValueError("replay fingerprint drift blocks evidence memory")
    if replay.get("verification_id") != verification.get("verification_id"):
        raise ValueError("replay result belongs to a different verification run")

    manifest = json.loads((verification_dir / "replay_manifest.json").read_text(encoding="utf-8"))
    manifest_hash = manifest.pop("manifest_sha256", None)
    if manifest_hash != _sha256_json(manifest):
        raise ValueError("replay manifest content hash mismatch")
    if replay.get("manifest_sha256") != manifest_hash:
        raise ValueError("replay result does not match verification manifest")

    task = load_task(verification_dir / "task_snapshot.json")
    baseline = json.loads((verification_dir / "baseline_params.json").read_text(encoding="utf-8"))
    candidate = json.loads((verification_dir / "candidate_params.json").read_text(encoding="utf-8"))
    fingerprint = json.loads(
        (verification_dir / "fingerprint_before.json").read_text(encoding="utf-8")
    )
    memory = _build_memory(
        verification,
        replay,
        task,
        baseline,
        candidate,
        fingerprint,
        verification_dir,
        replay_result_path,
        valid_days,
    )
    store = EvidenceMemoryStore(memory_dir)
    existing = store.validate_record(memory, supersedes=supersedes)
    if existing is not None:
        return existing
    _archive_evidence_bundle(
        memory,
        verification_dir,
        replay_result_path,
        memory_dir,
    )
    return store.record(memory, supersedes=supersedes)


def query_evidence_memory(
    task: TaskSpec,
    memory_dir: Path,
    *,
    repo_root: Path | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("evidence memory query limit must be positive")
    current_fingerprint = build_execution_fingerprint(task, repo_root=repo_root)
    query_scope = _scope_from(task, current_fingerprint)
    store = EvidenceMemoryStore(memory_dir)
    memories = store.rebuild(write_snapshot=True)
    matches: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for memory in memories.values():
        reasons: list[str] = []
        validity = memory["validity"]
        if validity["status"] != "active":
            excluded.append({"memory_id": memory["memory_id"], "reason": validity["status"]})
            continue
        valid_until = validity.get("valid_until")
        if valid_until and _parse_timestamp(valid_until, "valid_until") <= now:
            excluded.append({"memory_id": memory["memory_id"], "reason": "expired"})
            continue
        integrity_error = _evidence_integrity_error(memory)
        if integrity_error is not None:
            excluded.append(
                {"memory_id": memory["memory_id"], "reason": integrity_error}
            )
            continue
        scope = memory["scope"]
        for field in ["executor", "primary_metric"]:
            if scope.get(field) != query_scope.get(field):
                reasons.append(f"scope_mismatch:{field}")
        for field in ["dataset_sha256", "evaluator_dependencies_sha256"]:
            if scope.get(field) and scope.get(field) != query_scope.get(field):
                reasons.append(f"scope_mismatch:{field}")
        if reasons:
            excluded.append({"memory_id": memory["memory_id"], "reason": reasons})
            continue
        score = 10
        match_reasons = ["executor", "primary_metric"]
        if scope.get("task_name") == query_scope.get("task_name"):
            score += 4
            match_reasons.append("task_name")
        overlap = sorted(set(scope.get("parameter_names", [])) & set(task.search_space))
        score += len(overlap) * 2
        match_reasons.extend(f"parameter:{name}" for name in overlap)
        matches.append(
            {
                "memory_id": memory["memory_id"],
                "score": score,
                "reasons": match_reasons,
                "memory": memory,
            }
        )
    matches.sort(key=lambda item: (-item["score"], item["memory_id"]))
    return {
        "schema_version": "evidence-memory.query.v1",
        "query_scope": query_scope,
        "matched": matches[:limit],
        "excluded": excluded,
        "total_memories": len(memories),
    }


def _build_memory(
    verification: dict[str, Any],
    replay: dict[str, Any],
    task: TaskSpec,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    fingerprint: dict[str, Any],
    verification_dir: Path,
    replay_result_path: Path,
    valid_days: float | None,
) -> dict[str, Any]:
    interval = verification["statistics"]["paired_interval"]
    candidate_pass_rate = verification["statistics"]["candidate_guardrail_pass_rate"]
    required_pass_rate = task.verification.min_guardrail_pass_rate if task.verification else 1.0
    decision = verification["decision"]["decision"]
    if candidate_pass_rate < required_pass_rate:
        claim_type = "guardrail_tradeoff"
    elif decision == "promote":
        claim_type = "beneficial_effect"
    elif interval["upper"] <= 0:
        claim_type = "harmful_or_null_effect"
    else:
        claim_type = "inconclusive_effect"
    changes = {
        name: {"baseline": baseline.get(name), "candidate": candidate.get(name)}
        for name in sorted(set(baseline) | set(candidate))
        if baseline.get(name) != candidate.get(name)
    }
    identity = {
        "verification_id": verification["verification_id"],
        "fingerprint_id": verification["fingerprint_id"],
        "baseline": baseline,
        "candidate": candidate,
    }
    memory_id = f"mem_{_sha256_json(identity)[:24]}"
    created_at = _now()
    valid_until = None
    if valid_days is not None:
        if not math.isfinite(valid_days) or valid_days <= 0:
            raise ValueError("valid_days must be positive")
        valid_until = (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "memory_id": memory_id,
        "claim_type": claim_type,
        "claim": {
            "statement": (
                f"Under the recorded scope, changing {sorted(changes)} produced a "
                f"mean {task.primary_metric.name} improvement of {interval['mean']:.6f}."
            ),
            "primary_metric": task.primary_metric.name,
            "direction": task.primary_metric.direction,
            "changed_parameters": changes,
            "paired_effect": interval,
            "candidate_guardrail_pass_rate": candidate_pass_rate,
            "verification_decision": decision,
        },
        "scope": _scope_from(task, fingerprint),
        "evidence": {
            "verification_id": verification["verification_id"],
            "verification_result": str(verification_dir / "verification_result.json"),
            "verification_result_sha256": verification["verification_result_sha256"],
            "replay_id": replay["replay_id"],
            "replay_result": str(replay_result_path),
            "replay_result_sha256": replay["replay_result_sha256"],
            "manifest_sha256": replay["manifest_sha256"],
            "replay_manifest": str(verification_dir / "replay_manifest.json"),
            "fingerprint_id": verification["fingerprint_id"],
            "trial_count": verification["trial_count"],
        },
        "validity": {
            "status": "active",
            "valid_from": created_at,
            "valid_until": valid_until,
            "superseded_by": None,
            "updated_at": created_at,
        },
        "supersedes": [],
        "created_at": created_at,
    }


def _scope_from(task: TaskSpec, fingerprint: dict[str, Any]) -> dict[str, Any]:
    components = fingerprint["components"]
    dataset = components.get("dataset") or {}
    evaluator_files = components.get("evaluator_files") or []
    return {
        "task_name": task.name,
        "executor": task.executor,
        "primary_metric": task.primary_metric.name,
        "guardrail_metrics": [goal.name for goal in task.guardrail_metrics],
        "parameter_names": sorted(task.search_space),
        "dataset_sha256": dataset.get("sha256"),
        "evaluator_dependencies_sha256": _evaluator_scope_hash(evaluator_files),
    }


def _load_hashed_json(path: Path, hash_field: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded_hash = payload.pop(hash_field, None)
    if recorded_hash != _sha256_json(payload):
        raise ValueError(f"content hash mismatch: {path}")
    payload[hash_field] = recorded_hash
    return payload


def _archive_evidence_bundle(
    memory: dict[str, Any],
    verification_dir: Path,
    replay_result_path: Path,
    memory_dir: Path,
) -> None:
    evidence_dir = memory_dir / "evidence" / memory["memory_id"]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        "verification_result.json": verification_dir / "verification_result.json",
        "replay_result.json": replay_result_path,
        "replay_manifest.json": verification_dir / "replay_manifest.json",
        "task_snapshot.json": verification_dir / "task_snapshot.json",
        "baseline_params.json": verification_dir / "baseline_params.json",
        "candidate_params.json": verification_dir / "candidate_params.json",
        "fingerprint_before.json": verification_dir / "fingerprint_before.json",
        "fingerprint_after.json": verification_dir / "fingerprint_after.json",
    }
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f"verification evidence is missing: {source}")
        shutil.copy2(source, evidence_dir / name)
    memory["evidence"]["bundle_dir"] = str(evidence_dir)
    memory["evidence"]["verification_result"] = str(
        evidence_dir / "verification_result.json"
    )
    memory["evidence"]["replay_result"] = str(evidence_dir / "replay_result.json")
    memory["evidence"]["replay_manifest"] = str(evidence_dir / "replay_manifest.json")


def _evidence_integrity_error(memory: dict[str, Any]) -> str | None:
    evidence = memory["evidence"]
    try:
        verification = _load_hashed_json(
            Path(evidence["verification_result"]),
            "verification_result_sha256",
        )
        replay = _load_hashed_json(
            Path(evidence["replay_result"]),
            "replay_result_sha256",
        )
        manifest = json.loads(Path(evidence["replay_manifest"]).read_text(encoding="utf-8"))
        manifest_hash = manifest.pop("manifest_sha256", None)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return "evidence_integrity_failed"
    if verification["verification_result_sha256"] != evidence["verification_result_sha256"]:
        return "verification_evidence_hash_mismatch"
    if replay["replay_result_sha256"] != evidence["replay_result_sha256"]:
        return "replay_evidence_hash_mismatch"
    if manifest_hash != evidence["manifest_sha256"] or manifest_hash != _sha256_json(manifest):
        return "manifest_evidence_hash_mismatch"
    return None


def _validate_id(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe 1-128 character identifier")


def _validate_memory(memory: dict[str, Any]) -> None:
    if memory.get("claim_type") not in {
        "beneficial_effect",
        "guardrail_tradeoff",
        "harmful_or_null_effect",
        "inconclusive_effect",
    }:
        raise ValueError("unsupported evidence memory claim_type")
    for field in ["claim", "scope", "evidence", "validity"]:
        if not isinstance(memory.get(field), dict):
            raise ValueError(f"evidence memory {field} must be an object")
    if memory["validity"].get("status") != "active":
        raise ValueError("new evidence memory must start active")
    for field in ["created_at"]:
        _parse_timestamp(memory.get(field), field)
    for field in ["valid_from", "updated_at"]:
        _parse_timestamp(memory["validity"].get(field), field)
    valid_until = memory["validity"].get("valid_until")
    if valid_until is not None:
        _parse_timestamp(valid_until, "valid_until")
    supersedes = memory.get("supersedes", [])
    if not isinstance(supersedes, list) or any(
        not isinstance(memory_id, str) for memory_id in supersedes
    ):
        raise ValueError("evidence memory supersedes must be a list of ids")
    if not memory["evidence"].get("verification_id") or not memory["evidence"].get("replay_id"):
        raise ValueError("evidence memory requires verification and replay ids")


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"evidence memory {field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"evidence memory {field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"evidence memory {field_name} must be timezone-aware")
    return parsed


def _same_memory_content(left: dict[str, Any], right: dict[str, Any]) -> bool:
    stable_fields = ["schema_version", "memory_id", "claim_type", "claim", "scope"]
    if any(left.get(field) != right.get(field) for field in stable_fields):
        return False
    evidence_fields = [
        "verification_id",
        "verification_result_sha256",
        "replay_id",
        "replay_result_sha256",
        "manifest_sha256",
        "fingerprint_id",
        "trial_count",
    ]
    return all(
        left["evidence"].get(field) == right["evidence"].get(field)
        for field in evidence_fields
    )


def _evaluator_scope_hash(records: list[dict[str, Any]]) -> str:
    portable = [
        {key: value for key, value in record.items() if key != "path"}
        for record in records
    ]
    return _sha256_json(portable)


def _claims_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["scope"] != right["scope"]:
        return False
    left_changes = left["claim"].get("changed_parameters", {})
    right_changes = right["claim"].get("changed_parameters", {})
    if left_changes != right_changes:
        return False
    positive = {"beneficial_effect"}
    return (left["claim_type"] in positive) != (right["claim_type"] in positive)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
