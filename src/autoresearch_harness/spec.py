from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .models import (
    AdaptiveScheduling,
    Budget,
    CommandExecution,
    MetricGoal,
    MutationPolicy,
    TaskSpec,
    VerificationPolicy,
)


def load_task(path: Path) -> TaskSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    dataset = data.get("dataset")
    if dataset:
        dataset = str((root / dataset).resolve())

    metrics = data.get("metrics", {})
    primary = metrics.get("primary", {"name": "score", "direction": "maximize"})
    guardrails = metrics.get("guardrails", [])

    task = TaskSpec(
        name=data["name"],
        objective=data["objective"],
        executor=data["executor"],
        dataset=dataset,
        search_space=data["search_space"],
        metadata=dict(data.get("metadata", {})),
        budget=_budget(data.get("budget", {})),
        primary_metric=_metric_goal(primary),
        guardrail_metrics=[_metric_goal(item) for item in guardrails],
        schema_version=str(data.get("schema_version", "task.v1")),
        execution=_command_execution(data.get("execution"), root),
        mutation_policy=_mutation_policy(data.get("mutation")),
        scheduling=_adaptive_scheduling(data.get("scheduling")),
        verification=_verification_policy(data.get("verification")),
    )
    _validate_task(task)
    return task


def task_to_dict(task: TaskSpec) -> dict[str, Any]:
    data = {
        "schema_version": task.schema_version,
        "name": task.name,
        "objective": task.objective,
        "executor": task.executor,
        "dataset": task.dataset,
        "metadata": task.metadata,
        "search_space": task.search_space,
        "budget": _budget_to_dict(task.budget),
        "metrics": {
            "primary": task.primary_metric.__dict__,
            "guardrails": [item.__dict__ for item in task.guardrail_metrics],
        },
    }
    if task.execution is not None:
        data["execution"] = {
            "command": task.execution.command,
            "working_directory": task.execution.working_directory,
            "metrics_path": task.execution.metrics_path,
            "artifact_paths": task.execution.artifact_paths,
            "timeout_seconds": task.execution.timeout_seconds,
            "environment": task.execution.environment,
        }
    if task.mutation_policy is not None:
        data["mutation"] = {
            "editable_paths": task.mutation_policy.editable_paths,
            "allow_create": task.mutation_policy.allow_create,
            "max_file_bytes": task.mutation_policy.max_file_bytes,
        }
    if task.scheduling is not None:
        data["scheduling"] = {
            "protocol_version": task.scheduling.protocol_version,
            "strategy": task.scheduling.strategy,
            "initial_candidates": task.scheduling.initial_candidates,
            "reduction_factor": task.scheduling.reduction_factor,
            "random_seed": task.scheduling.random_seed,
            "fidelity": {
                "parameter": task.scheduling.fidelity_parameter,
                "levels": task.scheduling.fidelity_levels,
            },
            "objectives": [goal.__dict__ for goal in task.scheduling.objectives],
        }
    if task.verification is not None:
        data["verification"] = {
            "protocol_version": task.verification.protocol_version,
            "seed_parameter": task.verification.seed_parameter,
            "seeds": task.verification.seeds,
            "confidence_level": task.verification.confidence_level,
            "bootstrap_samples": task.verification.bootstrap_samples,
            "bootstrap_seed": task.verification.bootstrap_seed,
            "min_primary_improvement": task.verification.min_primary_improvement,
            "min_guardrail_pass_rate": task.verification.min_guardrail_pass_rate,
            "metric_tolerance": task.verification.metric_tolerance,
            "replay_metrics": task.verification.replay_metrics,
            "fingerprint_paths": task.verification.fingerprint_paths,
        }
    return data


def _metric_goal(data: dict[str, Any]) -> MetricGoal:
    return MetricGoal(
        name=data["name"],
        direction=data.get("direction", "maximize"),
        min_value=data.get("min", data.get("min_value")),
        max_value=data.get("max", data.get("max_value")),
    )


def _budget(data: dict[str, Any]) -> Budget:
    if not isinstance(data, dict):
        raise ValueError("budget must be an object")
    max_trials = data.get("max_trials", 20)
    if not isinstance(max_trials, int) or isinstance(max_trials, bool):
        raise ValueError("budget.max_trials must be an integer")
    max_wall_time = _optional_positive_number(
        data.get("max_wall_time_seconds"),
        "budget.max_wall_time_seconds",
    )
    max_fidelity = _optional_positive_number(
        data.get("max_fidelity_units"),
        "budget.max_fidelity_units",
    )
    return Budget(
        max_trials=max_trials,
        max_wall_time_seconds=max_wall_time,
        max_fidelity_units=max_fidelity,
    )


def _budget_to_dict(budget: Budget) -> dict[str, Any]:
    data: dict[str, Any] = {"max_trials": budget.max_trials}
    if budget.max_wall_time_seconds is not None:
        data["max_wall_time_seconds"] = budget.max_wall_time_seconds
    if budget.max_fidelity_units is not None:
        data["max_fidelity_units"] = budget.max_fidelity_units
    return data


def _command_execution(data: Any, root: Path) -> CommandExecution | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("execution must be an object")
    command = data.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise ValueError("execution.command must be a non-empty string array")
    working_directory_value = data.get("working_directory", ".")
    if not isinstance(working_directory_value, str):
        raise ValueError("execution.working_directory must be a string")
    artifact_paths = data.get("artifact_paths", [])
    if not isinstance(artifact_paths, list):
        raise ValueError("execution.artifact_paths must be a string array")
    environment = data.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("execution.environment must be an object")
    working_directory = (root / working_directory_value).resolve()
    return CommandExecution(
        command=list(command),
        working_directory=str(working_directory),
        metrics_path=_safe_relative_path(data.get("metrics_path", "metrics.json"), "metrics_path"),
        artifact_paths=[
            _safe_relative_path(item, "artifact_paths")
            for item in artifact_paths
        ],
        timeout_seconds=float(data.get("timeout_seconds", 300.0)),
        environment={str(key): str(value) for key, value in environment.items()},
    )


def _safe_relative_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"execution.{field_name} entries must be non-empty strings")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"execution.{field_name} must stay inside the trial output directory")
    return path.as_posix()


def _mutation_policy(data: Any) -> MutationPolicy | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("mutation must be an object")
    editable_paths = data.get("editable_paths")
    if not isinstance(editable_paths, list) or not editable_paths:
        raise ValueError("mutation.editable_paths must be a non-empty string array")
    allow_create = data.get("allow_create", False)
    if not isinstance(allow_create, bool):
        raise ValueError("mutation.allow_create must be a boolean")
    max_file_bytes_value = data.get("max_file_bytes", 1_000_000)
    if not isinstance(max_file_bytes_value, int) or isinstance(max_file_bytes_value, bool):
        raise ValueError("mutation.max_file_bytes must be an integer")
    max_file_bytes = max_file_bytes_value
    if max_file_bytes <= 0:
        raise ValueError("mutation.max_file_bytes must be greater than zero")
    normalized_paths = [
        _safe_relative_path(item, "editable_paths") for item in editable_paths
    ]
    if any(Path(item).parts[0] == ".git" for item in normalized_paths):
        raise ValueError("mutation.editable_paths may not target protected Git metadata")
    return MutationPolicy(
        editable_paths=normalized_paths,
        allow_create=allow_create,
        max_file_bytes=max_file_bytes,
    )


def _adaptive_scheduling(data: Any) -> AdaptiveScheduling | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("scheduling must be an object")
    if data.get("protocol_version") != "scheduling.v1":
        raise ValueError("scheduling.protocol_version must be scheduling.v1")
    if data.get("strategy", "successive_halving") != "successive_halving":
        raise ValueError("scheduling.strategy must be successive_halving")
    fidelity = data.get("fidelity")
    if not isinstance(fidelity, dict):
        raise ValueError("scheduling.fidelity must be an object")
    parameter = fidelity.get("parameter")
    levels = fidelity.get("levels")
    if not isinstance(parameter, str) or not parameter:
        raise ValueError("scheduling.fidelity.parameter must be a non-empty string")
    if (
        not isinstance(levels, list)
        or not levels
        or any(
            not isinstance(level, (int, float))
            or isinstance(level, bool)
            or not math.isfinite(level)
            or level <= 0
            for level in levels
        )
    ):
        raise ValueError("scheduling.fidelity.levels must be positive numbers")
    numeric_levels = [float(level) for level in levels]
    if numeric_levels != sorted(set(numeric_levels)):
        raise ValueError("scheduling.fidelity.levels must be unique and increasing")
    initial_candidates = data.get("initial_candidates", 8)
    reduction_factor = data.get("reduction_factor", 2)
    random_seed = data.get("random_seed", 0)
    for name, value, minimum in [
        ("initial_candidates", initial_candidates, 1),
        ("reduction_factor", reduction_factor, 2),
    ]:
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"scheduling.{name} must be an integer >= {minimum}")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool):
        raise ValueError("scheduling.random_seed must be an integer")
    raw_objectives = data.get("objectives")
    if not isinstance(raw_objectives, list) or not raw_objectives:
        raise ValueError("scheduling.objectives must be a non-empty array")
    objectives = [_metric_goal(item) for item in raw_objectives]
    if any(goal.direction not in {"maximize", "minimize"} for goal in objectives):
        raise ValueError("scheduling objective direction must be maximize or minimize")
    if len({goal.name for goal in objectives}) != len(objectives):
        raise ValueError("scheduling objective names must be unique")
    return AdaptiveScheduling(
        fidelity_parameter=parameter,
        fidelity_levels=numeric_levels,
        objectives=objectives,
        initial_candidates=initial_candidates,
        reduction_factor=reduction_factor,
        random_seed=random_seed,
    )


def _verification_policy(data: Any) -> VerificationPolicy | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("verification must be an object")
    if data.get("protocol_version") != "verification.v1":
        raise ValueError("verification.protocol_version must be verification.v1")
    seed_parameter = data.get("seed_parameter")
    seeds = data.get("seeds")
    if not isinstance(seed_parameter, str) or not seed_parameter:
        raise ValueError("verification.seed_parameter must be a non-empty string")
    if (
        not isinstance(seeds, list)
        or len(seeds) < 2
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("verification.seeds must contain at least two unique integers")
    confidence_level = data.get("confidence_level", 0.95)
    min_improvement = data.get("min_primary_improvement", 0.0)
    min_pass_rate = data.get("min_guardrail_pass_rate", 1.0)
    tolerance = data.get("metric_tolerance", 1e-9)
    numeric_values = [confidence_level, min_improvement, min_pass_rate, tolerance]
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        for value in numeric_values
    ):
        raise ValueError("verification numeric fields must be finite numbers")
    if not 0 < confidence_level < 1:
        raise ValueError("verification.confidence_level must be between zero and one")
    if not 0 <= min_pass_rate <= 1:
        raise ValueError("verification.min_guardrail_pass_rate must be between zero and one")
    if tolerance < 0:
        raise ValueError("verification.metric_tolerance must be non-negative")
    bootstrap_samples = data.get("bootstrap_samples", 2000)
    bootstrap_seed = data.get("bootstrap_seed", 0)
    replay_metrics = data.get("replay_metrics", [])
    fingerprint_paths = data.get("fingerprint_paths", [])
    if (
        not isinstance(bootstrap_samples, int)
        or isinstance(bootstrap_samples, bool)
        or bootstrap_samples < 100
    ):
        raise ValueError("verification.bootstrap_samples must be an integer >= 100")
    if not isinstance(bootstrap_seed, int) or isinstance(bootstrap_seed, bool):
        raise ValueError("verification.bootstrap_seed must be an integer")
    if not isinstance(replay_metrics, list) or not all(
        isinstance(name, str) and name for name in replay_metrics
    ):
        raise ValueError("verification.replay_metrics must be a string array")
    if len(replay_metrics) != len(set(replay_metrics)):
        raise ValueError("verification.replay_metrics must be unique")
    if not isinstance(fingerprint_paths, list):
        raise ValueError("verification.fingerprint_paths must be a string array")
    normalized_fingerprint_paths = [
        _safe_relative_path(path, "fingerprint_paths") for path in fingerprint_paths
    ]
    if len(normalized_fingerprint_paths) != len(set(normalized_fingerprint_paths)):
        raise ValueError("verification.fingerprint_paths must be unique")
    return VerificationPolicy(
        seed_parameter=seed_parameter,
        seeds=list(seeds),
        confidence_level=float(confidence_level),
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
        min_primary_improvement=float(min_improvement),
        min_guardrail_pass_rate=float(min_pass_rate),
        metric_tolerance=float(tolerance),
        replay_metrics=list(replay_metrics),
        fingerprint_paths=normalized_fingerprint_paths,
    )


def _validate_task(task: TaskSpec) -> None:
    if task.schema_version not in {"task.v1", "task.v2"}:
        raise ValueError(f"Unsupported task schema version: {task.schema_version}")
    if task.budget.max_trials <= 0:
        raise ValueError("budget.max_trials must be greater than zero")
    if (
        task.budget.max_wall_time_seconds is not None
        and (
            not math.isfinite(task.budget.max_wall_time_seconds)
            or task.budget.max_wall_time_seconds <= 0
        )
    ):
        raise ValueError("budget.max_wall_time_seconds must be greater than zero")
    if (
        task.budget.max_fidelity_units is not None
        and (
            not math.isfinite(task.budget.max_fidelity_units)
            or task.budget.max_fidelity_units <= 0
        )
    ):
        raise ValueError("budget.max_fidelity_units must be greater than zero")
    if task.executor == "external_command" and task.execution is None:
        raise ValueError("external_command tasks require an execution block")
    if task.executor == "external_command" and task.schema_version != "task.v2":
        raise ValueError("external_command tasks require schema_version task.v2")
    if task.mutation_policy is not None and task.schema_version != "task.v2":
        raise ValueError("mutation policy requires schema_version task.v2")
    if task.scheduling is not None:
        if task.schema_version != "task.v2":
            raise ValueError("adaptive scheduling requires schema_version task.v2")
        if task.scheduling.fidelity_parameter in task.search_space:
            raise ValueError("scheduling fidelity parameter must not be in search_space")
    if task.verification is not None:
        if task.schema_version != "task.v2":
            raise ValueError("verification requires schema_version task.v2")
        if task.verification.seed_parameter in task.search_space:
            raise ValueError("verification seed parameter must not be in search_space")
        if (
            task.verification.replay_metrics
            and task.primary_metric.name not in task.verification.replay_metrics
        ):
            raise ValueError("verification.replay_metrics must include the primary metric")
    if task.execution is not None:
        if task.execution.timeout_seconds <= 0:
            raise ValueError("execution.timeout_seconds must be greater than zero")
        if not Path(task.execution.working_directory).is_dir():
            raise ValueError(
                f"execution.working_directory does not exist: {task.execution.working_directory}"
            )


def _optional_positive_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{field_name} must be a finite number greater than zero")
    return numeric
