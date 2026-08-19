from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evaluation import passes_guardrails
from ..models import CommandExecution, TaskSpec, Trial, TrialResult


class ExternalCommandExecutor:
    """Execute a declared command and collect machine-readable trial evidence."""

    def __init__(self, task: TaskSpec):
        if task.execution is None:
            raise ValueError("external_command requires an execution block")
        self.task = task
        self.execution = task.execution
        self.run_dir: Path | None = None

    def set_run_dir(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def run(
        self,
        trial: Trial,
        timeout_seconds: float | None = None,
    ) -> TrialResult:
        if self.run_dir is None:
            raise RuntimeError("ExternalCommandExecutor requires a run directory")

        output_dir = self.run_dir / "executor_artifacts" / trial.id
        output_dir.mkdir(parents=True, exist_ok=False)
        params_path = output_dir / "trial_params.json"
        stdout_path = output_dir / "stdout.log"
        stderr_path = output_dir / "stderr.log"
        execution_path = output_dir / "execution.json"
        params_path.write_text(
            json.dumps(trial.params, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        command = _resolved_command(self.execution)
        environment = _execution_environment(
            self.task,
            self.execution,
            trial,
            output_dir,
            params_path,
        )
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        status = "completed"
        exit_code: int | None = None
        failure_note: str | None = None

        effective_timeout = self.execution.timeout_seconds
        if timeout_seconds is not None:
            effective_timeout = min(effective_timeout, max(timeout_seconds, 0.001))

        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                completed = subprocess.run(
                    command,
                    cwd=self.execution.working_directory,
                    env=environment,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    check=False,
                    timeout=effective_timeout,
                )
            exit_code = completed.returncode
            if exit_code != 0:
                status = "failed"
                failure_note = f"executor_exit_code={exit_code}"
        except subprocess.TimeoutExpired:
            status = "timed_out"
            failure_note = f"executor_timeout={effective_timeout:.3f}s"
        except OSError as exc:
            status = "failed"
            failure_note = f"executor_start_error: {exc}"

        duration = time.perf_counter() - started
        metrics_path = output_dir / self.execution.metrics_path
        metrics, metric_notes = _load_metrics(
            metrics_path,
            self.task.primary_metric.name,
            output_dir,
        )
        metrics["execution_time_sec"] = round(duration, 6)
        passed, guardrail_notes = passes_guardrails(self.task, metrics)
        notes = [item for item in [failure_note] if item]
        notes.extend(metric_notes)
        notes.extend(guardrail_notes)
        passed = passed and status == "completed" and not metric_notes

        declared_artifacts = [
            output_dir / relative_path for relative_path in self.execution.artifact_paths
        ]
        missing_artifacts = [
            path.relative_to(output_dir).as_posix()
            for path in declared_artifacts
            if not _is_safe_file(path, output_dir)
        ]
        if missing_artifacts:
            notes.append(f"missing_declared_artifacts: {', '.join(missing_artifacts)}")
            passed = False

        execution_record = {
            "schema_version": "execution.v1",
            "trial_id": trial.id,
            "status": status,
            "command": command,
            "working_directory": self.execution.working_directory,
            "started_at": started_at,
            "duration_seconds": duration,
            "timeout_seconds": effective_timeout,
            "exit_code": exit_code,
            "params_path": str(params_path),
            "metrics_path": str(metrics_path),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "declared_artifacts": [str(path) for path in declared_artifacts],
            "missing_artifacts": missing_artifacts,
            "metrics": metrics,
        }
        execution_path.write_text(
            json.dumps(execution_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _record_artifacts(
            self.run_dir,
            trial,
            params_path=params_path,
            metrics_path=metrics_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            execution_path=execution_path,
            declared_artifacts=declared_artifacts,
            status=status,
        )
        return TrialResult(
            trial_id=trial.id,
            params=trial.params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )


def _resolved_command(execution: CommandExecution) -> list[str]:
    return [sys.executable if item == "{python}" else item for item in execution.command]


def _execution_environment(
    task: TaskSpec,
    execution: CommandExecution,
    trial: Trial,
    output_dir: Path,
    params_path: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            key: value
            for key, value in execution.environment.items()
            if not key.startswith("AUTORESEARCH_")
        }
    )
    environment.update(
        {
            "AUTORESEARCH_TRIAL_ID": trial.id,
            "AUTORESEARCH_TRIAL_PARAMS": str(params_path.resolve()),
            "AUTORESEARCH_OUTPUT_DIR": str(output_dir.resolve()),
            "AUTORESEARCH_TASK_NAME": task.name,
        }
    )
    if task.dataset:
        environment["AUTORESEARCH_DATASET"] = str(Path(task.dataset).resolve())
    return environment


def _load_metrics(
    path: Path,
    primary_metric: str,
    output_dir: Path,
) -> tuple[dict[str, float], list[str]]:
    if not _is_safe_file(path, output_dir):
        if path.exists():
            return {}, ["invalid metrics artifact path"]
        return {}, [f"missing metrics artifact: {path.name}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {}, [f"invalid metrics artifact: {exc}"]
    if not isinstance(payload, dict):
        return {}, ["invalid metrics artifact: expected a JSON object"]

    metrics: dict[str, float] = {}
    notes: list[str] = []
    for name, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            notes.append(f"invalid metric value: {name}")
            continue
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            notes.append(f"non-finite metric value: {name}")
            continue
        metrics[str(name)] = numeric_value
    if primary_metric not in metrics:
        notes.append(f"missing primary metric: {primary_metric}")
    return metrics, notes


def _record_artifacts(
    run_dir: Path,
    trial: Trial,
    *,
    params_path: Path,
    metrics_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    execution_path: Path,
    declared_artifacts: list[Path],
    status: str,
) -> None:
    records = [
        ("trial_params", params_path, "Resolved parameters passed to the external command"),
        ("execution_manifest", execution_path, "Command, status, timing, and output manifest"),
        ("stdout_log", stdout_path, "External command standard output"),
        ("stderr_log", stderr_path, "External command standard error"),
    ]
    output_dir = params_path.parent
    if _is_safe_file(metrics_path, output_dir):
        records.append(("metrics", metrics_path, "Machine-readable evaluator metrics"))
    records.extend(
        ("declared_artifact", path, "Task-declared external command artifact")
        for path in declared_artifacts
        if _is_safe_file(path, output_dir)
    )
    manifest_path = run_dir / "executor_artifacts.jsonl"
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for kind, path, description in records:
            manifest.write(
                json.dumps(
                    {
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "trial_id": trial.id,
                        "kind": kind,
                        "path": str(path),
                        "description": description,
                        "metadata": {
                            "status": status,
                            "sha256": _sha256(path),
                            "size_bytes": path.stat().st_size,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_file(path: Path, output_dir: Path) -> bool:
    return path.is_file() and path.resolve().is_relative_to(output_dir.resolve())
