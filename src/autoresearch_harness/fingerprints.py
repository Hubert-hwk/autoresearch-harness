from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TaskSpec
from .spec import task_to_dict


def build_execution_fingerprint(
    task: TaskSpec,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Fingerprint the task, data, evaluator, harness, Python, packages, and Git state."""
    task_contract = _normalize_json_numbers(task_to_dict(task))
    components: dict[str, Any] = {
        "task_contract_sha256": _sha256_json(task_contract),
        "dataset": _path_record(Path(task.dataset)) if task.dataset else None,
        "evaluator_files": _evaluator_file_records(task),
        "harness_source": _harness_source_record(),
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "runtime_environment": {
            name: os.environ.get(name)
            for name in [
                "PYTHONHASHSEED",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "CUDA_VISIBLE_DEVICES",
                "LANG",
                "LC_ALL",
                "TZ",
            ]
        },
        "packages": _package_record(),
        "git": _git_record(repo_root),
    }
    return {
        "schema_version": "fingerprint.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint_id": _sha256_json(components),
        "components": components,
    }


def fingerprint_differences(
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> list[str]:
    if expected.get("fingerprint_id") == actual.get("fingerprint_id"):
        return []
    differences: list[str] = []
    expected_components = expected.get("components", {})
    actual_components = actual.get("components", {})
    for name in sorted(set(expected_components) | set(actual_components)):
        if expected_components.get(name) != actual_components.get(name):
            differences.append(name)
    return differences or ["fingerprint_id"]


def _evaluator_file_records(task: TaskSpec) -> list[dict[str, Any]]:
    if task.execution is None:
        return []
    working_directory = Path(task.execution.working_directory)
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for argument in task.execution.command:
        if argument == "{python}":
            continue
        path = Path(argument)
        candidate = path if path.is_absolute() else working_directory / path
        candidate = candidate.resolve()
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        records.append(_path_record(candidate))
    if task.verification is not None:
        for relative_path in task.verification.fingerprint_paths:
            candidate = (working_directory / relative_path).resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            records.append(_path_record(candidate))
    return records


def _harness_source_record() -> dict[str, Any]:
    root = Path(__file__).resolve().parent
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*.py"))
        if path.is_file()
    ]
    return {"sha256": _sha256_json(files), "files": files}


def _package_record() -> dict[str, Any]:
    packages = sorted(
        {
            (
                (distribution.metadata.get("Name") or distribution.name).lower(),
                distribution.version,
            )
            for distribution in importlib.metadata.distributions()
        }
    )
    records = [{"name": name, "version": version} for name, version in packages]
    return {"sha256": _sha256_json(records), "packages": records}


def _git_record(repo_root: Path | None) -> dict[str, Any] | None:
    if repo_root is None:
        return None
    root = repo_root.resolve()
    try:
        commit = _git(root, "rev-parse", "HEAD^{commit}")
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=normal")
        diff = _git(root, "diff", "--binary", "HEAD", "--", ".")
    except (OSError, subprocess.CalledProcessError):
        return None
    return {
        "repo_root": str(root),
        "commit": commit,
        "dirty": bool(status),
        "status_sha256": _sha256_text(status),
        "tracked_diff_sha256": _sha256_text(diff),
    }


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _path_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved.is_dir():
        files = [
            {
                "path": child.relative_to(resolved).as_posix(),
                "sha256": _sha256_file(child),
                "size_bytes": child.stat().st_size,
            }
            for child in sorted(resolved.rglob("*"))
            if child.is_file()
            and ".git" not in child.relative_to(resolved).parts
            and "__pycache__" not in child.relative_to(resolved).parts
        ]
        return {
            "path": str(resolved),
            "exists": True,
            "kind": "directory",
            "sha256": _sha256_json(files),
            "files": files,
        }
    if not resolved.is_file():
        return {"path": str(resolved), "exists": False}
    return {
        "path": str(resolved),
        "exists": True,
        "kind": "file",
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_json_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
