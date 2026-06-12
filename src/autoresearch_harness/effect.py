from __future__ import annotations

from typing import Any

from .models import TaskSpec


def compare_runs(task: TaskSpec, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    metric = task.primary_metric.name
    baseline_best = _best_primary(baseline)
    candidate_best = _best_primary(candidate)
    delta = None
    if baseline_best is not None and candidate_best is not None:
        delta = candidate_best - baseline_best
        if task.primary_metric.direction == "minimize":
            delta = -delta

    pass_rate_delta = candidate.get("pass_rate", 0.0) - baseline.get("pass_rate", 0.0)
    return {
        "primary_metric": metric,
        "baseline_best": baseline_best,
        "candidate_best": candidate_best,
        "primary_delta": delta,
        "baseline_pass_rate": baseline.get("pass_rate", 0.0),
        "candidate_pass_rate": candidate.get("pass_rate", 0.0),
        "pass_rate_delta": pass_rate_delta,
    }


def _best_primary(analysis: dict[str, Any]) -> float | None:
    top_trials = analysis.get("top_trials", [])
    if not top_trials:
        return None
    return float(top_trials[0]["primary_metric"])


