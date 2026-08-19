from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import EXECUTORS
from .evaluation import better
from .experiment_graph import ExperimentGraphStore
from .models import MetricGoal, TaskSpec, Trial, TrialResult
from .policy import search_space_values
from .spec import task_to_dict


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    params: dict[str, Any]


@dataclass(frozen=True)
class AdaptiveBudgetUsage:
    trials: int
    fidelity_units: float
    wall_time_seconds: float


class GlobalBudgetTracker:
    def __init__(self, task: TaskSpec):
        self.budget = task.budget
        self.trials = 0
        self.fidelity_units = 0.0
        self.started = time.monotonic()

    def limit_reason(self, fidelity: float) -> str | None:
        if self.trials >= self.budget.max_trials:
            return "trial_budget_exhausted"
        if (
            self.budget.max_fidelity_units is not None
            and self.fidelity_units + fidelity > self.budget.max_fidelity_units
        ):
            return "fidelity_budget_exhausted"
        if self.remaining_wall_time() is not None and self.remaining_wall_time() <= 0:
            return "wall_time_budget_exhausted"
        return None

    def remaining_wall_time(self) -> float | None:
        if self.budget.max_wall_time_seconds is None:
            return None
        return max(0.0, self.budget.max_wall_time_seconds - self.elapsed())

    def consume(self, fidelity: float) -> None:
        self.trials += 1
        self.fidelity_units += fidelity

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def usage(self) -> AdaptiveBudgetUsage:
        return AdaptiveBudgetUsage(
            trials=self.trials,
            fidelity_units=self.fidelity_units,
            wall_time_seconds=self.elapsed(),
        )


def sample_candidates(task: TaskSpec) -> list[Candidate]:
    if task.scheduling is None:
        raise ValueError("adaptive scheduling configuration is required")
    names = list(task.search_space)
    dimensions = [search_space_values(task.search_space[name]) for name in names]
    if any(not values for values in dimensions):
        return []
    total = math.prod(len(values) for values in dimensions)
    count = min(task.scheduling.initial_candidates, total, task.budget.max_trials)
    indices = random.Random(task.scheduling.random_seed).sample(range(total), count)
    return [
        Candidate(
            candidate_id=f"candidate_{position:04d}",
            params=dict(zip(names, _decode_product_index(index, dimensions))),
        )
        for position, index in enumerate(indices, start=1)
    ]


def pareto_front(
    results: list[tuple[str, TrialResult]],
    objectives: list[MetricGoal],
) -> list[str]:
    eligible = [
        (candidate_id, result)
        for candidate_id, result in results
        if result.passed_guardrails
        and all(objective.name in result.metrics for objective in objectives)
    ]
    front: list[str] = []
    for candidate_id, candidate in eligible:
        if not any(
            _dominates(other, candidate, objectives)
            for other_id, other in eligible
            if other_id != candidate_id
        ):
            front.append(candidate_id)
    return front


def select_promotions(
    results: list[tuple[str, TrialResult]],
    primary: MetricGoal,
    reduction_factor: int,
) -> list[str]:
    eligible = [
        item
        for item in results
        if item[1].passed_guardrails and primary.name in item[1].metrics
    ]
    reverse = primary.direction != "minimize"
    eligible.sort(
        key=lambda item: item[1].metrics[primary.name],
        reverse=reverse,
    )
    keep = max(1, len(eligible) // reduction_factor) if eligible else 0
    return [candidate_id for candidate_id, _ in eligible[:keep]]


def run_adaptive_task(
    task: TaskSpec,
    runs_dir: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    scheduling = task.scheduling
    if scheduling is None:
        raise ValueError("adaptive-run requires a task scheduling block")
    _validate_runtime_contract(task)
    run_id = datetime.now(timezone.utc).strftime("adaptive_%Y%m%dT%H%M%S%fZ")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "task.json", task_to_dict(task))

    executor_cls = EXECUTORS.get(task.executor)
    if executor_cls is None:
        raise ValueError(f"Unknown executor: {task.executor}")
    executor = executor_cls(task)
    if hasattr(executor, "set_run_dir"):
        executor.set_run_dir(run_dir)

    candidates = sample_candidates(task)
    if not candidates:
        raise ValueError("adaptive search space produced no candidates")
    graph = ExperimentGraphStore(run_dir, run_id)
    base_commit = _resolve_base_commit(repo_root, task)
    budget = GlobalBudgetTracker(task)
    active = candidates
    parent_nodes: dict[str, str] = {}
    stages: list[dict[str, Any]] = []
    stop_reason = "completed_all_fidelities"
    _append_event(run_dir, "adaptive_run_started", {"candidate_count": len(candidates)})

    for stage_index, fidelity in enumerate(scheduling.fidelity_levels, start=1):
        pre_stage_limit = budget.limit_reason(fidelity)
        if pre_stage_limit is not None:
            stop_reason = pre_stage_limit
            break
        _append_event(
            run_dir,
            "stage_started",
            {
                "stage_index": stage_index,
                "fidelity": fidelity,
                "candidate_ids": [candidate.candidate_id for candidate in active],
            },
        )
        observations: list[tuple[Candidate, TrialResult, str, float]] = []
        stage_limit: str | None = None
        for candidate in active:
            stage_limit = budget.limit_reason(fidelity)
            if stage_limit is not None:
                stop_reason = stage_limit
                break
            trial_id = f"stage_{stage_index:02d}_{candidate.candidate_id}"
            node_id = f"s{stage_index:02d}_{candidate.candidate_id}"
            graph.create_node(
                node_id,
                parent_ids=[parent_nodes[candidate.candidate_id]]
                if candidate.candidate_id in parent_nodes
                else [],
                hypothesis={"objective": task.objective},
                mutation={"parameters": candidate.params},
                base_commit=base_commit,
                fidelity={
                    "parameter": scheduling.fidelity_parameter,
                    "value": fidelity,
                    "stage": stage_index,
                },
            )
            graph.transition(node_id, "running", reason="scheduled by successive halving")
            params = dict(candidate.params)
            params[scheduling.fidelity_parameter] = fidelity
            trial = Trial(id=trial_id, params=params)
            started = time.monotonic()
            try:
                if task.executor == "external_command":
                    result = executor.run(
                        trial,
                        timeout_seconds=budget.remaining_wall_time(),
                    )
                else:
                    result = executor.run(trial)
            except Exception as exc:
                result = TrialResult(
                    trial_id=trial.id,
                    params=trial.params,
                    metrics={},
                    passed_guardrails=False,
                    notes=[f"executor_exception={type(exc).__name__}: {exc}"],
                )
            duration = time.monotonic() - started
            budget.consume(fidelity)
            observations.append((candidate, result, node_id, duration))
            _append_jsonl(
                run_dir / "adaptive_trials.jsonl",
                {
                    "stage_index": stage_index,
                    "fidelity": fidelity,
                    "candidate_id": candidate.candidate_id,
                    "node_id": node_id,
                    "duration_seconds": duration,
                    "budget_after": asdict(budget.usage()),
                    "result": asdict(result),
                },
            )
            graph.attach_evaluation(
                node_id,
                {"trial_result": asdict(result), "duration_seconds": duration},
                feedback=[{"kind": "trial_note", "text": note} for note in result.notes],
            )
            graph.record_budget(
                node_id,
                {
                    "trials": 1,
                    "fidelity_units": fidelity,
                    "wall_time_seconds": duration,
                },
            )
            graph.attach_artifacts(node_id, [str(run_dir / "adaptive_trials.jsonl")])
            graph.transition(node_id, "evaluated", reason="trial evaluation completed")
            _append_event(
                run_dir,
                "trial_completed",
                {
                    "stage_index": stage_index,
                    "candidate_id": candidate.candidate_id,
                    "node_id": node_id,
                    "passed_guardrails": result.passed_guardrails,
                },
            )

        stage_pairs = [
            (candidate.candidate_id, result) for candidate, result, _, _ in observations
        ]
        pareto_ids = pareto_front(stage_pairs, scheduling.objectives)
        stage_complete = len(observations) == len(active)
        final_stage = stage_index == len(scheduling.fidelity_levels)
        promoted_ids: list[str] = []
        if stage_complete and not final_stage:
            promoted_ids = select_promotions(
                stage_pairs,
                task.primary_metric,
                scheduling.reduction_factor,
            )

        for candidate, _, node_id, _ in observations:
            if not stage_complete:
                decision = "needs_review"
                reason = f"stage interrupted by {stage_limit}"
            elif final_stage:
                decision = "accept" if candidate.candidate_id in pareto_ids else "reject"
                reason = "final-stage Pareto archive membership"
            else:
                decision = "accept" if candidate.candidate_id in promoted_ids else "reject"
                reason = "successive-halving promotion"
            graph.attach_decision(
                node_id,
                {"decision": decision, "reason": reason, "stage": stage_index},
            )
            graph.transition(
                node_id,
                {"accept": "accepted", "reject": "rejected", "needs_review": "needs_review"}[
                    decision
                ],
                reason=reason,
            )

        stage_record = {
            "stage_index": stage_index,
            "fidelity": fidelity,
            "scheduled_candidates": [candidate.candidate_id for candidate in active],
            "evaluated_candidates": [candidate.candidate_id for candidate, _, _, _ in observations],
            "stage_complete": stage_complete,
            "pareto_candidate_ids": pareto_ids,
            "promoted_candidate_ids": promoted_ids,
            "results": [
                {
                    "candidate_id": candidate.candidate_id,
                    "node_id": node_id,
                    "duration_seconds": duration,
                    "trial_result": asdict(result),
                }
                for candidate, result, node_id, duration in observations
            ],
        }
        stages.append(stage_record)
        _append_event(run_dir, "stage_completed", stage_record)
        _write_json(
            run_dir / "state.json",
            {
                "run_id": run_id,
                "status": "running" if stage_complete else "budget_exhausted",
                "stop_reason": stop_reason,
                "completed_stages": len(stages),
                "budget_usage": asdict(budget.usage()),
            },
        )
        if not stage_complete:
            break
        if final_stage:
            break
        if not promoted_ids:
            stop_reason = "no_guardrail_passing_candidates"
            break
        parent_nodes = {
            candidate.candidate_id: node_id
            for candidate, _, node_id, _ in observations
            if candidate.candidate_id in promoted_ids
        }
        active = [
            candidate for candidate in active if candidate.candidate_id in promoted_ids
        ]

    archive = {
        "schema_version": "pareto_archive.v1",
        "objectives": [goal.__dict__ for goal in scheduling.objectives],
        "stages": [
            {
                "stage_index": stage["stage_index"],
                "fidelity": stage["fidelity"],
                "stage_complete": stage["stage_complete"],
                "candidate_ids": stage["pareto_candidate_ids"],
            }
            for stage in stages
        ],
        "final_candidate_ids": stages[-1]["pareto_candidate_ids"] if stages else [],
    }
    _write_json(run_dir / "pareto_archive.json", archive)
    best = _best_from_last_stage(stages, task.primary_metric)
    result = {
        "run_id": run_id,
        "status": "completed",
        "stop_reason": stop_reason,
        "budget_usage": asdict(budget.usage()),
        "initial_candidates": [asdict(candidate) for candidate in candidates],
        "stages": stages,
        "pareto_archive": archive,
        "best_result": asdict(best) if best else None,
        "paths": {
            "run_dir": str(run_dir),
            "trials": str(run_dir / "adaptive_trials.jsonl"),
            "schedule_events": str(run_dir / "schedule_events.jsonl"),
            "experiment_graph": str(run_dir / "experiment_graph.json"),
            "pareto_archive": str(run_dir / "pareto_archive.json"),
        },
    }
    _append_event(run_dir, "adaptive_run_completed", {"stop_reason": stop_reason})
    _write_json(run_dir / "result.json", result)
    _write_json(run_dir / "state.json", result)
    _write_report(run_dir, result)
    return result


def _decode_product_index(index: int, dimensions: list[list[Any]]) -> list[Any]:
    values: list[Any] = [None] * len(dimensions)
    for position in range(len(dimensions) - 1, -1, -1):
        dimension = dimensions[position]
        index, offset = divmod(index, len(dimension))
        values[position] = dimension[offset]
    return values


def _validate_runtime_contract(task: TaskSpec) -> None:
    scheduling = task.scheduling
    assert scheduling is not None
    if task.budget.max_trials <= 0:
        raise ValueError("adaptive trial budget must be positive")
    for name, value in [
        ("max_wall_time_seconds", task.budget.max_wall_time_seconds),
        ("max_fidelity_units", task.budget.max_fidelity_units),
    ]:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError(f"adaptive {name} must be finite and positive")
    if scheduling.initial_candidates <= 0 or scheduling.reduction_factor < 2:
        raise ValueError("adaptive candidate count and reduction factor are invalid")
    if (
        not scheduling.fidelity_levels
        or any(not math.isfinite(value) or value <= 0 for value in scheduling.fidelity_levels)
        or scheduling.fidelity_levels != sorted(set(scheduling.fidelity_levels))
    ):
        raise ValueError("adaptive fidelity levels must be finite, unique, and increasing")
    if not scheduling.objectives or any(
        objective.direction not in {"maximize", "minimize"}
        for objective in scheduling.objectives
    ):
        raise ValueError("adaptive objectives must declare maximize or minimize")


def _dominates(
    candidate: TrialResult,
    other: TrialResult,
    objectives: list[MetricGoal],
) -> bool:
    at_least_as_good = True
    strictly_better = False
    for objective in objectives:
        left = candidate.metrics[objective.name]
        right = other.metrics[objective.name]
        if objective.direction == "minimize":
            at_least_as_good = at_least_as_good and left <= right
            strictly_better = strictly_better or left < right
        else:
            at_least_as_good = at_least_as_good and left >= right
            strictly_better = strictly_better or left > right
    return at_least_as_good and strictly_better


def _best_from_last_stage(
    stages: list[dict[str, Any]],
    primary: MetricGoal,
) -> TrialResult | None:
    if not stages:
        return None
    best: TrialResult | None = None
    for record in stages[-1]["results"]:
        result = TrialResult(**record["trial_result"])
        if primary.name not in result.metrics:
            continue
        if better(primary, result, best):
            best = result
    return best


def _resolve_base_commit(repo_root: Path | None, task: TaskSpec) -> str:
    if repo_root is not None:
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD^{commit}"],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return completed.stdout.strip()
        except OSError:
            pass
    fingerprint = hashlib.sha256(
        json.dumps(task_to_dict(task), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"task:{fingerprint}"


def _append_event(run_dir: Path, event: str, payload: dict[str, Any]) -> None:
    _append_jsonl(
        run_dir / "schedule_events.jsonl",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        },
    )


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_report(run_dir: Path, result: dict[str, Any]) -> None:
    usage = result["budget_usage"]
    lines = [
        f"# Adaptive Research Run: {result['run_id']}",
        "",
        f"- Stop reason: `{result['stop_reason']}`",
        f"- Trials: `{usage['trials']}`",
        f"- Fidelity units: `{usage['fidelity_units']:.3f}`",
        f"- Wall time: `{usage['wall_time_seconds']:.3f}s`",
        f"- Completed stages: `{sum(1 for stage in result['stages'] if stage['stage_complete'])}`",
        f"- Final Pareto candidates: `{', '.join(result['pareto_archive']['final_candidate_ids']) or 'none'}`",
    ]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
