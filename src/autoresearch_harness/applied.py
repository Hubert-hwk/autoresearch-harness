from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .experiment_graph import ExperimentGraphStore, open_experiment_graph
from .models import CommandExecution, TaskSpec
from .patching import (
    PatchApplication,
    PatchPlan,
    apply_patch_plan,
    patch_application_to_dict,
    patch_plan_to_dict,
)
from .runner import run_task
from .spec import task_to_dict
from .workspace import WorktreeManager, workspace_record_to_dict


def run_patch_experiment(
    task: TaskSpec,
    patch_plan: PatchPlan,
    *,
    repo_root: Path,
    runs_dir: Path,
    workspaces_dir: Path,
    base_commit: str = "HEAD",
    graph_dir: Path | None = None,
    graph_id: str | None = None,
    node_id: str | None = None,
    parent_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    if task.executor != "external_command" or task.execution is None:
        raise ValueError("patch experiments currently require an external_command task")
    if task.mutation_policy is None:
        raise ValueError("patch experiments require a task mutation policy")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    experiment_id = f"patch_{timestamp}_{patch_plan.id}"
    experiment_dir = runs_dir / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=False)
    _write_json(experiment_dir / "task_snapshot.json", task_to_dict(task))
    _write_json(experiment_dir / "patch_plan.json", patch_plan_to_dict(patch_plan))
    _write_json(
        experiment_dir / "state.json",
        {
            "experiment_id": experiment_id,
            "status": "preparing_workspace",
            "base_commit_requested": base_commit,
        },
    )

    try:
        manager = WorktreeManager(repo_root, workspaces_dir)
        workspace_id = experiment_id[-80:]
        workspace = manager.prepare(workspace_id, base_commit)
    except Exception as exc:
        _write_json(
            experiment_dir / "state.json",
            {
                "experiment_id": experiment_id,
                "status": "failed",
                "stage": "workspace_preparation",
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
    workspace_path = Path(workspace.workspace_path)
    _write_json(experiment_dir / "workspace.json", workspace_record_to_dict(workspace))

    graph: ExperimentGraphStore | None = None
    graph_node_created = False
    resolved_graph_dir = graph_dir or experiment_dir
    resolved_node_id = node_id or (experiment_id if graph_dir is not None else "candidate")
    try:
        if (resolved_graph_dir / "experiment_events.jsonl").exists():
            graph = open_experiment_graph(resolved_graph_dir, graph_id)
        else:
            graph = ExperimentGraphStore(resolved_graph_dir, graph_id or experiment_id)
        graph.create_node(
            resolved_node_id,
            parent_ids=parent_node_ids,
            hypothesis={
                "rationale": patch_plan.rationale,
                "objective": task.objective,
            },
            mutation=patch_plan_to_dict(patch_plan),
            base_commit=workspace.base_commit,
            workspace=workspace_record_to_dict(workspace),
            fidelity={
                "kind": "declared_task_budget",
                "max_trials": task.budget.max_trials,
                "max_wall_time_seconds": task.budget.max_wall_time_seconds,
            },
            status="workspace_prepared",
        )
        graph_node_created = True
        candidate_task = _task_for_workspace(task, repo_root.resolve(), workspace_path)
        application = apply_patch_plan(
            workspace_path,
            task.mutation_policy,
            patch_plan,
            experiment_dir / "mutation.diff",
        )
        _write_json(
            experiment_dir / "patch_application.json",
            patch_application_to_dict(application),
        )
        pre_run_audit = _audit_workspace(workspace_path, application)
        _write_json(experiment_dir / "workspace_audit_before.json", pre_run_audit)
        graph.attach_artifacts(
            resolved_node_id,
            [
                str(experiment_dir / "task_snapshot.json"),
                str(experiment_dir / "patch_plan.json"),
                str(experiment_dir / "workspace.json"),
                str(experiment_dir / "mutation.diff"),
                str(experiment_dir / "patch_application.json"),
                str(experiment_dir / "workspace_audit_before.json"),
            ],
        )
        graph.transition(
            resolved_node_id,
            "running",
            reason="patch validated and workspace audited",
        )
        _write_json(
            experiment_dir / "state.json",
            {
                "experiment_id": experiment_id,
                "status": "running_candidate",
                "workspace": workspace_record_to_dict(workspace),
                "patch_application": patch_application_to_dict(application),
            },
        )
        summary = run_task(candidate_task, experiment_dir / "candidate")
        post_run_audit = _audit_workspace(workspace_path, application)
        _write_json(experiment_dir / "workspace_audit_after.json", post_run_audit)
        evaluation_bundle = {
            "candidate_run_id": summary.run_id,
            "task_name": summary.task_name,
            "total_trials": summary.total_trials,
            "stop_reason": summary.stop_reason,
            "best_result": summary.best_result.__dict__ if summary.best_result else None,
        }
        graph.attach_evaluation(
            resolved_node_id,
            evaluation_bundle,
            feedback=[
                {"kind": "trial_note", "text": note}
                for note in (summary.best_result.notes if summary.best_result else [])
            ],
        )
        graph.record_budget(resolved_node_id, {"trials": summary.total_trials})
        graph.attach_artifacts(
            resolved_node_id,
            [
                str(experiment_dir / "candidate" / summary.run_id),
                str(experiment_dir / "workspace_audit_after.json"),
            ],
        )
        graph.transition(
            resolved_node_id,
            "evaluated",
            reason="candidate evaluation completed",
        )
        graph_snapshot = graph.snapshot()
        result = {
            "experiment_id": experiment_id,
            "status": "completed",
            "base_commit": workspace.base_commit,
            "workspace": workspace_record_to_dict(workspace),
            "patch_application": patch_application_to_dict(application),
            "workspace_audit": post_run_audit,
            "experiment_node": next(
                node
                for node in graph_snapshot["nodes"]
                if node["node_id"] == resolved_node_id
            ),
            "candidate_run_id": summary.run_id,
            "candidate": evaluation_bundle,
            "paths": {
                "experiment_dir": str(experiment_dir),
                "candidate_run_dir": str(
                    experiment_dir / "candidate" / summary.run_id
                ),
                "workspace": workspace.workspace_path,
                "mutation_diff": str(experiment_dir / "mutation.diff"),
                "experiment_events": str(resolved_graph_dir / "experiment_events.jsonl"),
                "experiment_graph": str(resolved_graph_dir / "experiment_graph.json"),
            },
        }
        _write_json(experiment_dir / "result.json", result)
        _write_json(experiment_dir / "state.json", result)
        return result
    except Exception as exc:
        graph_error: str | None = None
        if graph is not None and graph_node_created:
            try:
                node = graph.get_node(resolved_node_id)
                if node.status not in {"accepted", "rejected", "failed", "cancelled"}:
                    graph.transition(resolved_node_id, "failed", reason=str(exc))
            except Exception as graph_exc:
                graph_error = f"{type(graph_exc).__name__}: {graph_exc}"
        _write_json(
            experiment_dir / "state.json",
            {
                "experiment_id": experiment_id,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "workspace": workspace_record_to_dict(workspace),
                "workspace_retained": True,
                "experiment_graph_error": graph_error,
            },
        )
        raise


def _task_for_workspace(task: TaskSpec, repo_root: Path, workspace: Path) -> TaskSpec:
    assert task.execution is not None
    working_directory = _remap_required_path(
        Path(task.execution.working_directory),
        repo_root,
        workspace,
        "execution.working_directory",
    )
    command = [
        _remap_command_argument(argument, repo_root, workspace)
        for argument in task.execution.command
    ]
    execution = replace(
        task.execution,
        command=command,
        working_directory=str(working_directory),
    )
    dataset = task.dataset
    if dataset is not None:
        dataset_path = Path(dataset)
        if dataset_path.is_absolute() and dataset_path.is_relative_to(repo_root):
            dataset = str(workspace / dataset_path.relative_to(repo_root))
    return replace(task, dataset=dataset, execution=execution)


def _remap_required_path(
    path: Path,
    repo_root: Path,
    workspace: Path,
    field_name: str,
) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(repo_root):
        raise ValueError(f"{field_name} must be inside repo_root for worktree isolation")
    candidate = workspace / resolved.relative_to(repo_root)
    if not candidate.is_dir():
        raise ValueError(f"{field_name} is missing from base commit: {candidate}")
    return candidate


def _remap_command_argument(argument: str, repo_root: Path, workspace: Path) -> str:
    path = Path(argument)
    if path.is_absolute() and path.is_relative_to(repo_root):
        return str(workspace / path.relative_to(repo_root))
    return argument


def _audit_workspace(
    workspace: Path,
    application: PatchApplication,
) -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    entries = [entry for entry in completed.stdout.split("\0") if entry]
    actual_paths = sorted(entry[3:] for entry in entries)
    expected_paths = sorted(change.path for change in application.changes)
    if actual_paths != expected_paths:
        unexpected = sorted(set(actual_paths) - set(expected_paths))
        missing = sorted(set(expected_paths) - set(actual_paths))
        raise RuntimeError(
            "workspace changes diverged from patch plan; "
            f"unexpected={unexpected}, missing={missing}"
        )

    hashes: dict[str, str] = {}
    expected_hashes = {change.path: change.after_sha256 for change in application.changes}
    for relative_path in expected_paths:
        path = workspace / relative_path
        digest = _sha256_file(path)
        hashes[relative_path] = digest
        if digest != expected_hashes[relative_path]:
            raise RuntimeError(f"workspace file changed after patch application: {relative_path}")
    return {
        "status": "verified",
        "changed_paths": actual_paths,
        "file_sha256": hashes,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
