from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .hypothesis import Hypothesis
from .llm import LLMClient, LLMMessage
from .models import TaskSpec


class RuleBasedResearchAgent:
    """Deterministic planner used to validate the agentic harness loop."""

    def propose(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]] | None = None,
    ) -> Hypothesis:
        memories = memories or []
        if task.executor == "prompt_tuning":
            return self._prompt_tuning_hypothesis(task, analysis, source_run_id, memories)
        if task.executor == "model_param_tuning":
            return self._model_param_hypothesis(task, analysis, source_run_id, memories)
        if task.executor == "recommender_bpr":
            return self._recommender_bpr_hypothesis(task, analysis, source_run_id, memories)
        if task.executor == "ranking_param_tuning":
            return self._ranking_hypothesis(task, analysis, source_run_id, memories)
        return self._generic_hypothesis(task, analysis, source_run_id, memories)

    def _prompt_tuning_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]],
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
        if _memory_mentions(memories, "avg_tokens"):
            _filter_values(search_space, "length", ["medium"])
            risks.append("Memory indicates answer length can become the next limiting guardrail.")

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

    def _model_param_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]],
    ) -> Hypothesis:
        search_space = deepcopy(task.search_space)
        failures = analysis.get("failure_reasons", {})
        rationale = "Focus model serving parameters around quality-stable configurations."
        risks = ["Lower-risk decoding can leave some quality upside unexplored."]

        if failures.get("latency_ms", 0) > 0 or failures.get("cost_usd", 0) > 0:
            _filter_values(search_space, "max_tokens", [512, 1024])
            _filter_values(search_space, "retrieval_depth", [1, 2])
            rationale = (
                "Baseline failures indicate serving cost or latency pressure. "
                "Reduce token and retrieval budgets before exploring quality tradeoffs."
            )
        if failures.get("stability_score", 0) > 0 or _memory_mentions(memories, "stability"):
            _filter_values(search_space, "temperature", [0.0, 0.2, 0.4])
            risks.append("Stability-focused decoding may reduce creative-answer quality.")

        return Hypothesis(
            id=f"hyp_{source_run_id}_model_param_focus",
            title="Constrain model parameters toward stable cost-aware serving",
            rationale=rationale,
            expected_effects={
                "quality_score": "maintain or improve",
                "latency_ms": "decrease or stay within guardrail",
                "cost_usd": "decrease or stay within guardrail",
                "stability_score": "improve",
            },
            risks=risks,
            search_space=search_space,
            validation_plan="Run focused model_param_tuning trials and compare candidate to baseline.",
            source_run_id=source_run_id,
        )

    def _recommender_bpr_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]],
    ) -> Hypothesis:
        search_space = deepcopy(task.search_space)
        _filter_values(search_space, "factors", [8, 16])
        _filter_values(search_space, "regularization", [0.001])
        _filter_values(search_space, "epochs", [8])
        rationale = (
            "Baseline BPR trials underexplored larger embeddings because the budget "
            "was exhausted on smaller factor settings. Focus candidate training on "
            "larger latent spaces while keeping epochs and regularization controlled."
        )
        if _memory_mentions(memories, "train_time_sec"):
            _filter_values(search_space, "epochs", [8])

        return Hypothesis(
            id=f"hyp_{source_run_id}_recommender_bpr_focus",
            title="Focus BPR recommender search on larger controlled embeddings",
            rationale=rationale,
            expected_effects={
                "ndcg_at_10": "improve",
                "hit_rate_at_10": "improve or stay above guardrail",
                "train_time_sec": "stay within guardrail",
            },
            risks=["Larger embeddings can overfit sparse users or increase runtime."],
            search_space=search_space,
            validation_plan="Run focused recommender_bpr trials and compare top-k metrics.",
            source_run_id=source_run_id,
        )

    def _ranking_hypothesis(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]],
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
        memories: list[dict[str, Any]],
    ) -> Hypothesis:
        memory_hint = ""
        if memories:
            memory_hint = f" Recent memory count: {len(memories)}."
        return Hypothesis(
            id=f"hyp_{source_run_id}_focused_retry",
            title="Retry with the current search space and preserve run evidence",
            rationale=f"Generic executor has pass rate {analysis.get('pass_rate', 0):.2%}.{memory_hint}",
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


def _memory_mentions(memories: list[dict[str, Any]], text: str) -> bool:
    needle = text.lower()
    return any(needle in str(memory).lower() for memory in memories)


class LLMResearchAgent:
    """LLM-backed hypothesis proposer with deterministic harness guardrails."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def propose(
        self,
        task: TaskSpec,
        analysis: dict[str, Any],
        source_run_id: str,
        memories: list[dict[str, Any]] | None = None,
    ) -> Hypothesis:
        memories = memories or []
        content = self.llm_client.complete(
            [
                LLMMessage(
                    role="system",
                    content=(
                        "You propose bounded optimization hypotheses for an "
                        "AutoResearch harness. Return only valid JSON. Do not "
                        "include markdown."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "task": {
                                "name": task.name,
                                "objective": task.objective,
                                "executor": task.executor,
                                "search_space": task.search_space,
                                "primary_metric": task.primary_metric.__dict__,
                                "guardrails": [
                                    guardrail.__dict__ for guardrail in task.guardrail_metrics
                                ],
                            },
                            "baseline_analysis": analysis,
                            "recent_memories": memories[-10:],
                            "required_schema": {
                                "title": "short hypothesis title",
                                "rationale": "why this direction should help",
                                "expected_effects": {"metric_name": "expected change"},
                                "risks": ["risk"],
                                "search_space": "subset of the provided search_space",
                                "validation_plan": "how to validate the hypothesis",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        payload = _parse_llm_json(content)
        return Hypothesis(
            id=f"hyp_{source_run_id}_llm",
            title=str(payload["title"]),
            rationale=str(payload["rationale"]),
            expected_effects=dict(payload.get("expected_effects", {})),
            risks=list(payload.get("risks", [])),
            search_space=_validated_search_space(task.search_space, payload["search_space"]),
            validation_plan=str(payload["validation_plan"]),
            source_run_id=source_run_id,
        )


def _parse_llm_json(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content.strip())
    except json.JSONDecodeError as exc:
        raise ValueError("LLMResearchAgent expected valid JSON output") from exc
    required = ["title", "rationale", "search_space", "validation_plan"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"LLM hypothesis missing required fields: {missing}")
    if not isinstance(payload["search_space"], dict):
        raise ValueError("LLM hypothesis search_space must be an object")
    return payload


def _validated_search_space(
    original: dict[str, dict[str, Any]],
    proposed: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    validated = deepcopy(original)
    for name, spec in proposed.items():
        if name not in validated:
            continue
        original_spec = validated[name]
        if original_spec.get("type", "categorical") == "categorical":
            original_values = list(original_spec.get("values", []))
            proposed_values = list(spec.get("values", []))
            filtered = [value for value in proposed_values if value in original_values]
            if filtered:
                original_spec["values"] = filtered
        elif original_spec.get("type") in {"float", "int"}:
            min_value = max(original_spec["min"], spec.get("min", original_spec["min"]))
            max_value = min(original_spec["max"], spec.get("max", original_spec["max"]))
            if min_value <= max_value:
                original_spec["min"] = min_value
                original_spec["max"] = max_value
                if "steps" in spec:
                    original_spec["steps"] = max(1, int(spec["steps"]))
    return validated
