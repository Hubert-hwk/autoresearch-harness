from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    mode: str
    repo_root: str
    workspace_path: str
    base_commit: str
    source_branch: str
    created_at: str
    status: str = "prepared"


class WorktreeManager:
    """Create detached experiment worktrees without switching the source worktree."""

    def __init__(self, repo_root: Path, workspaces_root: Path):
        self.repo_root = repo_root.resolve()
        self.workspaces_root = workspaces_root.resolve()
        top_level = Path(self._git("rev-parse", "--show-toplevel")).resolve()
        if top_level != self.repo_root:
            raise ValueError(f"repo_root is not the Git top level: {self.repo_root}")

    def prepare(self, workspace_id: str, base_commit: str = "HEAD") -> WorkspaceRecord:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", workspace_id):
            raise ValueError("workspace_id must be a safe 1-80 character identifier")
        resolved_commit = self._git("rev-parse", f"{base_commit}^{{commit}}")
        source_branch = self._git("branch", "--show-current") or "detached"
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        workspace_path = (self.workspaces_root / workspace_id).resolve()
        if not workspace_path.is_relative_to(self.workspaces_root):
            raise ValueError("workspace path escapes workspaces root")
        if workspace_path.exists():
            raise FileExistsError(f"workspace already exists: {workspace_path}")

        self._git("worktree", "add", "--detach", str(workspace_path), resolved_commit)
        current_branch = self._git("branch", "--show-current") or "detached"
        if current_branch != source_branch:
            raise RuntimeError("source worktree branch changed while preparing experiment worktree")
        return WorkspaceRecord(
            workspace_id=workspace_id,
            mode="git_worktree_detached",
            repo_root=str(self.repo_root),
            workspace_path=str(workspace_path),
            base_commit=resolved_commit,
            source_branch=source_branch,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def remove(self, record: WorkspaceRecord, *, force: bool = False) -> None:
        workspace_path = Path(record.workspace_path).resolve()
        if not workspace_path.is_relative_to(self.workspaces_root):
            raise ValueError("refusing to remove a workspace outside workspaces root")
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(workspace_path))
        self._git(*args)

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-c", f"safe.directory={self.repo_root.as_posix()}", *args],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


def workspace_record_to_dict(record: WorkspaceRecord) -> dict[str, Any]:
    return asdict(record)
