from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class BranchRecord:
    mode: str
    base_branch: str
    base_commit: str
    experiment_branch: str
    created: bool


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


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return slug[:80] or "experiment"

