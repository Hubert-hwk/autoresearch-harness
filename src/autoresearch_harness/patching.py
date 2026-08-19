from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .models import MutationPolicy


@dataclass(frozen=True)
class PatchOperation:
    op: str
    path: str
    old: str | None = None
    new: str | None = None
    content: str | None = None
    expected_replacements: int = 1


@dataclass(frozen=True)
class PatchPlan:
    id: str
    protocol_version: str
    rationale: str
    operations: list[PatchOperation]


@dataclass(frozen=True)
class FileChange:
    path: str
    operation_count: int
    before_sha256: str | None
    after_sha256: str
    before_size_bytes: int
    after_size_bytes: int


@dataclass(frozen=True)
class PatchApplication:
    plan_id: str
    protocol_version: str
    workspace_path: str
    diff_path: str
    diff_sha256: str
    changes: list[FileChange]


def load_patch_plan(path: Path) -> PatchPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("patch plan must be a JSON object")
    if payload.get("protocol_version") != "patch.v1":
        raise ValueError("patch plan protocol_version must be patch.v1")
    plan_id = payload.get("id")
    if not isinstance(plan_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", plan_id):
        raise ValueError("patch plan id must be a safe 1-80 character identifier")
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise ValueError("patch plan operations must be a non-empty array")
    operations = [_parse_operation(item) for item in raw_operations]
    return PatchPlan(
        id=plan_id,
        protocol_version="patch.v1",
        rationale=str(payload.get("rationale", "")),
        operations=operations,
    )


def apply_patch_plan(
    workspace: Path,
    policy: MutationPolicy,
    plan: PatchPlan,
    diff_path: Path,
) -> PatchApplication:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")

    snapshots: dict[str, tuple[str | None, str, int]] = {}
    operation_counts: dict[str, int] = {}
    for operation in plan.operations:
        target = _resolve_target(workspace, policy, operation.path)
        key = operation.path
        if key in snapshots:
            original, current, original_size = snapshots[key]
        else:
            original, current, original_size = _read_initial(target, policy, operation)
        updated = _apply_operation(current, original is not None, operation, policy)
        snapshots[key] = (original, updated, original_size)
        operation_counts[key] = operation_counts.get(key, 0) + 1

    if all(original == updated for original, updated, _ in snapshots.values()):
        raise ValueError("patch plan produced no file changes")

    changes: list[FileChange] = []
    diff_lines: list[str] = []
    for relative_path in sorted(snapshots):
        original, updated, original_size = snapshots[relative_path]
        target = _resolve_target(workspace, policy, relative_path)
        if original is None:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8")
        before_text = original or ""
        diff_lines.extend(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{relative_path}" if original is not None else "/dev/null",
                tofile=f"b/{relative_path}",
            )
        )
        changes.append(
            FileChange(
                path=relative_path,
                operation_count=operation_counts[relative_path],
                before_sha256=_sha256_text(original) if original is not None else None,
                after_sha256=_sha256_text(updated),
                before_size_bytes=original_size,
                after_size_bytes=len(updated.encode("utf-8")),
            )
        )

    diff_text = "".join(diff_lines)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text(diff_text, encoding="utf-8")
    return PatchApplication(
        plan_id=plan.id,
        protocol_version=plan.protocol_version,
        workspace_path=str(workspace),
        diff_path=str(diff_path),
        diff_sha256=_sha256_text(diff_text),
        changes=changes,
    )


def patch_plan_to_dict(plan: PatchPlan) -> dict[str, Any]:
    return asdict(plan)


def patch_application_to_dict(application: PatchApplication) -> dict[str, Any]:
    return asdict(application)


def _parse_operation(data: Any) -> PatchOperation:
    if not isinstance(data, dict):
        raise ValueError("patch operation must be an object")
    op = data.get("op")
    path = data.get("path")
    if op not in {"replace_text", "create_file"}:
        raise ValueError(f"unsupported patch operation: {op}")
    _validate_relative_path(path)
    if op == "replace_text":
        old = data.get("old")
        new = data.get("new")
        expected = data.get("expected_replacements", 1)
        if not isinstance(old, str) or not old:
            raise ValueError("replace_text.old must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError("replace_text.new must be a string")
        if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
            raise ValueError("expected_replacements must be a positive integer")
        return PatchOperation(
            op=op,
            path=path,
            old=old,
            new=new,
            expected_replacements=expected,
        )
    content = data.get("content")
    if not isinstance(content, str) or not content:
        raise ValueError("create_file.content must be a non-empty string")
    return PatchOperation(op=op, path=path, content=content)


def _validate_relative_path(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("patch operation path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError("patch operation path must be a normalized relative POSIX path")
    if path.parts[0] == ".git":
        raise ValueError("patch operation may not target protected Git metadata")


def _resolve_target(workspace: Path, policy: MutationPolicy, relative_path: str) -> Path:
    _validate_relative_path(relative_path)
    relative = PurePosixPath(relative_path)
    allowed = False
    for editable in policy.editable_paths:
        editable_path = PurePosixPath(editable)
        editable_target = workspace.joinpath(*editable_path.parts)
        if relative == editable_path:
            allowed = True
            break
        if editable_target.is_dir() and editable_path in relative.parents:
            allowed = True
            break
    if not allowed:
        raise ValueError(f"patch target is outside editable paths: {relative_path}")
    target = workspace.joinpath(*relative.parts)
    current = workspace
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                f"patch target may not contain a symlink component: {relative_path}"
            )
    if not target.resolve(strict=False).is_relative_to(workspace):
        raise ValueError(f"patch target escapes workspace: {relative_path}")
    return target


def _read_initial(
    target: Path,
    policy: MutationPolicy,
    operation: PatchOperation,
) -> tuple[str | None, str, int]:
    if target.exists():
        if not target.is_file():
            raise ValueError(f"patch target is not a regular file: {operation.path}")
        size = target.stat().st_size
        if size > policy.max_file_bytes:
            raise ValueError(f"patch target exceeds max_file_bytes: {operation.path}")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"patch target is not UTF-8 text: {operation.path}") from exc
        return text, text, size
    if operation.op != "create_file":
        raise ValueError(f"replace_text target does not exist: {operation.path}")
    if not policy.allow_create:
        raise ValueError("mutation policy does not allow file creation")
    return None, "", 0


def _apply_operation(
    current: str,
    existed: bool,
    operation: PatchOperation,
    policy: MutationPolicy,
) -> str:
    if operation.op == "create_file":
        if existed or current:
            raise ValueError(f"create_file target already exists: {operation.path}")
        updated = operation.content or ""
    else:
        assert operation.old is not None and operation.new is not None
        count = current.count(operation.old)
        if count != operation.expected_replacements:
            raise ValueError(
                f"replace_text expected {operation.expected_replacements} matches in "
                f"{operation.path}, found {count}"
            )
        updated = current.replace(
            operation.old,
            operation.new,
            operation.expected_replacements,
        )
    if len(updated.encode("utf-8")) > policy.max_file_bytes:
        raise ValueError(f"patched file exceeds max_file_bytes: {operation.path}")
    return updated


def _sha256_text(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()
