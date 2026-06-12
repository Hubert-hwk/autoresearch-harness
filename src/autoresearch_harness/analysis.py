from __future__ import annotations

from collections import Counter
from typing import Any

from .models import MetricGoal, TrialResult


def build_run_analysis(results: list[TrialResult], primary_metric: MetricGoal) -> dict[str, Any]:
    passed = [result for result in results if result.passed_guardrails]
    failed = [result for result in results if not result.passed_guardrails]
    reverse = primary_metric.direction != "minimize"
    top_results = sorted(
        passed,
        key=lambda result: result.metrics[primary_metric.name],
        reverse=reverse,
    )[:5]

    return {
        "total_trials": len(results),
        "passed_trials": len(passed),
        "failed_trials": len(failed),
        "pass_rate": len(passed) / len(results) if results else 0.0,
        "failure_reasons": dict(_failure_reasons(failed)),
        "top_trials": [
            {
                "trial_id": result.trial_id,
                "primary_metric": result.metrics[primary_metric.name],
                "metrics": result.metrics,
                "params": result.params,
            }
            for result in top_results
        ],
    }


def _failure_reasons(results: list[TrialResult]) -> Counter[str]:
    reasons: Counter[str] = Counter()
    for result in results:
        if not result.notes:
            reasons["unknown"] += 1
        for note in result.notes:
            metric = note.split("=", maxsplit=1)[0]
            reasons[metric] += 1
    return reasons

