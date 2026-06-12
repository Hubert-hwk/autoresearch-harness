from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BranchRecord:
    mode: str
    base_branch: str
    base_commit: str
    experiment_branch: str
    created: bool


@dataclass(frozen=True)
class BranchLifecycleEvent:
    name: str
    status: str
    metadata: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class BranchLifecycle:
    hypothesis_id: str
    experiment_branch: str
    base_branch: str
    base_commit: str
    mode: str
    created: bool
    status: str
    disposition: str | None
    events: list[BranchLifecycleEvent]


class BranchManager:
    """Records or creates experiment branches for agentic research runs."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def prepare(self, hypothesis_id: str, mode: str = "record") -> BranchRecord:
        if mode not in {"record", "create"}:
            raise ValueError("branch mode must be 'record' or 'create'")

        base_branch = self._git("branch", "--show-current") or "detached"
        base_commit = self._git("rev-parse", "HEAD")
        experiment_branch = f"autoresearch/{_slug(hypothesis_id)}"
        created = False

        if mode == "create":
            existing = self._git("branch", "--list", experiment_branch)
            if existing:
                self._git("switch", experiment_branch)
            else:
                self._git("switch", "-c", experiment_branch)
                created = True

        return BranchRecord(
            mode=mode,
            base_branch=base_branch,
            base_commit=base_commit,
            experiment_branch=experiment_branch,
            created=created,
        )

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-c", f"safe.directory={self.repo_root.as_posix()}", *args],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


def branch_record_to_dict(record: BranchRecord) -> dict[str, object]:
    return asdict(record)


def start_branch_lifecycle(hypothesis_id: str, record: BranchRecord) -> BranchLifecycle:
    return BranchLifecycle(
        hypothesis_id=hypothesis_id,
        experiment_branch=record.experiment_branch,
        base_branch=record.base_branch,
        base_commit=record.base_commit,
        mode=record.mode,
        created=record.created,
        status="prepared",
        disposition=None,
        events=[
            BranchLifecycleEvent(
                name="branch_prepared",
                status="prepared",
                metadata=branch_record_to_dict(record),
                created_at=_now(),
            )
        ],
    )


def advance_branch_lifecycle(
    lifecycle: BranchLifecycle,
    event_name: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> BranchLifecycle:
    events = list(lifecycle.events)
    if not any(event.name == event_name for event in events):
        events.append(
            BranchLifecycleEvent(
                name=event_name,
                status=status,
                metadata=metadata or {},
                created_at=_now(),
            )
        )
    return BranchLifecycle(
        hypothesis_id=lifecycle.hypothesis_id,
        experiment_branch=lifecycle.experiment_branch,
        base_branch=lifecycle.base_branch,
        base_commit=lifecycle.base_commit,
        mode=lifecycle.mode,
        created=lifecycle.created,
        status=status,
        disposition=lifecycle.disposition,
        events=events,
    )


def complete_branch_lifecycle(
    lifecycle: BranchLifecycle,
    decision: str,
) -> BranchLifecycle:
    disposition = _disposition_for(decision, lifecycle.mode)
    return advance_branch_lifecycle(
        BranchLifecycle(
            hypothesis_id=lifecycle.hypothesis_id,
            experiment_branch=lifecycle.experiment_branch,
            base_branch=lifecycle.base_branch,
            base_commit=lifecycle.base_commit,
            mode=lifecycle.mode,
            created=lifecycle.created,
            status=lifecycle.status,
            disposition=disposition,
            events=lifecycle.events,
        ),
        "decision_recorded",
        "completed",
        {"decision": decision, "disposition": disposition},
    )


def branch_lifecycle_to_dict(lifecycle: BranchLifecycle) -> dict[str, Any]:
    return asdict(lifecycle)


def branch_lifecycle_from_dict(data: dict[str, Any]) -> BranchLifecycle:
    return BranchLifecycle(
        hypothesis_id=data["hypothesis_id"],
        experiment_branch=data["experiment_branch"],
        base_branch=data["base_branch"],
        base_commit=data["base_commit"],
        mode=data["mode"],
        created=bool(data["created"]),
        status=data["status"],
        disposition=data.get("disposition"),
        events=[
            BranchLifecycleEvent(
                name=event["name"],
                status=event["status"],
                metadata=dict(event.get("metadata", {})),
                created_at=event["created_at"],
            )
            for event in data.get("events", [])
        ],
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return slug[:80] or "experiment"


def _disposition_for(decision: str, mode: str) -> str:
    if mode == "record":
        return "record_only"
    if decision == "accept":
        return "retain_for_promotion"
    if decision == "needs_review":
        return "retain_for_review"
    if decision == "retry":
        return "retain_for_retry"
    return "retain_for_audit"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
