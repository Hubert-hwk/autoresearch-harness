from __future__ import annotations

from copy import deepcopy
from typing import Any

from .hypothesis import Hypothesis
from .models import TaskSpec


class RuleBasedResearchAgent:
    """Deterministic planner used to validate the agentic harness loop."""

    def propose(self, task: TaskSpec, analysis: dict[str, Any], source_run_id: str) -> Hypothesis:
        if task.executor == "prompt_tuning":
            return self._prompt_tuning_hypothesis(task, analysis, source_run_id)
        if task.executor == "ranking_param_tuning":
            return self._ranking_hypothesis(task, analysis, source_run_id)
        return self._generic_hypothesis(task, analysis, source_run_id)

    def _prompt_tuning_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
    ) -> Hypothesis:
        search_space = deepcopy(task.search_space)
        failures = analysis.get("failure_reasons", {})
        rationale = "Prior run showed mixed results; focus on grounded prompt variants."
        risks = ["Narrowing the search space can miss creative but valid alternatives."]

        if failures.get("hallucination_rate", 0) > 0:
            _filter_values(search_space, "evidence_policy", ["cite_context", "strict_context"])
            _filter_values(search_space, "style", ["structured"])
            _filter_values(search_space, "length", ["medium", "long"])
            rationale = (
                "Baseline failures were dominated by hallucination guardrail violations. "
                "Constrain evidence policy to grounded modes and use structured answers."
            )
            risks = ["Grounded structured answers may increase average token count."]

        return Hypothesis(
            id=f"hyp_{source_run_id}_grounded_prompt",
            title="Constrain prompt variants toward grounded structured answers",
            rationale=rationale,
            expected_effects={
                "accuracy": "maintain or improve",
                "hallucination_rate": "decrease",
                "avg_tokens": "watch guardrail",
            },
            risks=risks,
            search_space=search_space,
            validation_plan="Run focused prompt_tuning trials and compare against baseline run.",
            source_run_id=source_run_id,
        )

    def _ranking_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
    ) -> Hypothesis:
        search_space = deepcopy(task.search_space)
        failures = analysis.get("failure_reasons", {})
        if failures.get("latency_p95_ms", 0) > 0:
            _filter_values(search_space, "latency_penalty", [0.2])
            rationale = "Baseline had latency guardrail failures; emphasize latency penalty."
        else:
            rationale = "Focus ranking trials around the observed high-performing region."
        return Hypothesis(
            id=f"hyp_{source_run_id}_ranking_focus",
            title="Focus ranking search around guardrail-safe candidates",
            rationale=rationale,
            expected_effects={
                task.primary_metric.name: "maintain or improve",
                "latency_p95_ms": "decrease or stay within guardrail",
            },
            risks=["Guardrail-safe candidates can trade off revenue or relevance."],
            search_space=search_space,
            validation_plan="Run focused ranking trials and compare candidate run to baseline.",
            source_run_id=source_run_id,
        )

    def _generic_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
    ) -> Hypothesis:
        return Hypothesis(
            id=f"hyp_{source_run_id}_focused_retry",
            title="Retry with the current search space and preserve run evidence",
            rationale=f"Generic executor has pass rate {analysis.get('pass_rate', 0):.2%}.",
            expected_effects={task.primary_metric.name: "observe"},
            risks=["No executor-specific planning rule is available yet."],
            search_space=deepcopy(task.search_space),
            validation_plan="Run the same task and compare artifacts.",
            source_run_id=source_run_id,
        )


def _filter_values(
    search_space: dict[str, dict[str, Any]],
    name: str,
    allowed_values: list[Any],
) -> None:
    spec = search_space.get(name)
    if not spec or spec.get("type", "categorical") != "categorical":
        return
    current = list(spec.get("values", []))
    filtered = [value for value in current if value in allowed_values]
    if filtered:
        spec["values"] = filtered

