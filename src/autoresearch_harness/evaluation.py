from __future__ import annotations

from .models import MetricGoal, TaskSpec, TrialResult


def passes_guardrails(task: TaskSpec, metrics: dict[str, float]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    passed = True
    for goal in task.guardrail_metrics:
        value = metrics.get(goal.name)
        if value is None:
            passed = False
            notes.append(f"missing guardrail metric: {goal.name}")
            continue
        if goal.min_value is not None and value < goal.min_value:
            passed = False
            notes.append(f"{goal.name}={value:.4f} below min {goal.min_value}")
        if goal.max_value is not None and value > goal.max_value:
            passed = False
            notes.append(f"{goal.name}={value:.4f} above max {goal.max_value}")
    return passed, notes


def better(primary: MetricGoal, candidate: TrialResult, incumbent: TrialResult | None) -> bool:
    if not candidate.passed_guardrails:
        return False
    if incumbent is None:
        return True
    candidate_value = candidate.metrics[primary.name]
    incumbent_value = incumbent.metrics[primary.name]
    if primary.direction == "minimize":
        return candidate_value < incumbent_value
    return candidate_value > incumbent_value

