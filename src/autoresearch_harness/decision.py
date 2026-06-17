from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import TaskSpec


@dataclass(frozen=True)
class Decision:
    decision: str
    confidence: float
    reasons: list[str]
    blocking_guardrails: list[str] = field(default_factory=list)
    next_action: str = "stop"


def make_decision(
    task: TaskSpec,
    baseline_analysis: dict[str, Any],
    candidate_analysis: dict[str, Any],
    effect: dict[str, Any],
) -> Decision:
    delta = effect.get("primary_delta")
    pass_rate_delta = effect.get("pass_rate_delta", 0.0)
    new_failures = _new_failure_reasons(baseline_analysis, candidate_analysis)
    candidate_failures = candidate_analysis.get("failure_reasons", {})
    uncertainty = _primary_uncertainty(task, baseline_analysis, candidate_analysis)

    if delta is None:
        return Decision(
            decision="retry",
            confidence=0.45,
            reasons=["No guardrail-passing candidate was available for comparison."],
            blocking_guardrails=list(candidate_failures),
            next_action="mutate_search_space",
        )

    if delta < 0:
        return Decision(
            decision="reject",
            confidence=0.8,
            reasons=[f"Candidate reduced {task.primary_metric.name} by {abs(delta):.6f}."],
            blocking_guardrails=list(candidate_failures),
            next_action="try_alternative_hypothesis",
        )

    if delta > 0 and uncertainty is not None and delta <= uncertainty:
        return Decision(
            decision="needs_review",
            confidence=0.55,
            reasons=[
                (
                    f"Candidate improved {task.primary_metric.name} by {delta:.6f}, "
                    f"but this is within observed metric noise ({uncertainty:.6f})."
                ),
                "Run more seeds or a larger validation split before promotion.",
            ],
            blocking_guardrails=[],
            next_action="run_more_seeds_or_expand_validation",
        )

    if pass_rate_delta < 0 and delta > 0:
        return Decision(
            decision="needs_review",
            confidence=0.65,
            reasons=[
                "Candidate improved the primary metric but reduced guardrail pass rate.",
                f"New or worsened failure reasons: {', '.join(new_failures) or 'none'}",
            ],
            blocking_guardrails=list(candidate_failures),
            next_action="human_review_or_guardrail_focused_mutation",
        )

    if pass_rate_delta < 0:
        return Decision(
            decision="reject",
            confidence=0.75,
            reasons=["Candidate reduced guardrail pass rate without primary metric upside."],
            blocking_guardrails=list(candidate_failures),
            next_action="tighten_guardrails",
        )

    if new_failures:
        return Decision(
            decision="needs_review",
            confidence=0.6,
            reasons=[
                "Candidate preserved headline metrics but introduced new failure reasons.",
                f"New failure reasons: {', '.join(new_failures)}",
            ],
            blocking_guardrails=new_failures,
            next_action="inspect_new_failures",
        )

    return Decision(
        decision="accept",
        confidence=0.85 if delta > 0 else 0.7,
        reasons=[
            "Candidate preserved or improved primary metric.",
            "Candidate preserved or improved guardrail pass rate.",
        ],
        next_action="record_lesson_and_consider_promotion",
    )


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    return asdict(decision)


def _new_failure_reasons(
    baseline_analysis: dict[str, Any],
    candidate_analysis: dict[str, Any],
) -> list[str]:
    baseline_failures = set(baseline_analysis.get("failure_reasons", {}))
    candidate_failures = set(candidate_analysis.get("failure_reasons", {}))
    return sorted(candidate_failures - baseline_failures)


def _primary_uncertainty(
    task: TaskSpec,
    baseline_analysis: dict[str, Any],
    candidate_analysis: dict[str, Any],
) -> float | None:
    baseline_std = _top_trial_metric_std(task, baseline_analysis)
    candidate_std = _top_trial_metric_std(task, candidate_analysis)
    if baseline_std is None or candidate_std is None:
        return None
    return (baseline_std**2 + candidate_std**2) ** 0.5


def _top_trial_metric_std(task: TaskSpec, analysis: dict[str, Any]) -> float | None:
    top_trials = analysis.get("top_trials", [])
    if not top_trials:
        return None
    metrics = top_trials[0].get("metrics", {})
    std = metrics.get(f"{task.primary_metric.name}_std")
    if std is None:
        return None
    return float(std)
