from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from ..evaluation import passes_guardrails
from ..models import TaskSpec, Trial, TrialResult


class ModelParamTuningExecutor:
    """Deterministic model-serving parameter tuning simulator."""

    def __init__(self, task: TaskSpec):
        if not task.dataset:
            raise ValueError("model_param_tuning requires a dataset path")
        self.task = task
        self.cases = [
            json.loads(line)
            for line in Path(task.dataset).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def run(self, trial: Trial) -> TrialResult:
        quality_scores: list[float] = []
        latency_scores: list[float] = []
        cost_scores: list[float] = []
        stability_scores: list[float] = []

        for case in self.cases:
            quality_scores.append(self._quality(case, trial.params))
            latency_scores.append(self._latency_ms(case, trial.params))
            cost_scores.append(self._cost_usd(case, trial.params))
            stability_scores.append(self._stability(case, trial.params))

        metrics = {
            "quality_score": statistics.fmean(quality_scores),
            "latency_ms": statistics.fmean(latency_scores),
            "cost_usd": statistics.fmean(cost_scores),
            "stability_score": statistics.fmean(stability_scores),
        }
        passed, notes = passes_guardrails(self.task, metrics)
        return TrialResult(
            trial_id=trial.id,
            params=trial.params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )

    def _quality(self, case: dict[str, Any], params: dict[str, Any]) -> float:
        target_temperature = float(case["target_temperature"])
        target_context = int(case["target_context_tokens"])
        temperature = float(params["temperature"])
        top_p = float(params["top_p"])
        max_tokens = int(params["max_tokens"])
        retrieval_depth = int(params["retrieval_depth"])

        quality = case["base_quality"]
        quality += max(0.0, 1.0 - abs(temperature - target_temperature) * 2.0) * 0.18
        quality += max(0.0, 1.0 - abs(top_p - 0.85) * 1.5) * 0.08
        quality += min(max_tokens / target_context, 1.0) * 0.12
        quality += min(retrieval_depth / case["ideal_retrieval_depth"], 1.0) * 0.1
        if temperature > case["risk_temperature"]:
            quality -= 0.08
        return round(max(0.0, min(1.0, quality)), 6)

    def _latency_ms(self, case: dict[str, Any], params: dict[str, Any]) -> float:
        return round(
            case["base_latency_ms"]
            + int(params["max_tokens"]) * 0.32
            + int(params["retrieval_depth"]) * 85
            + float(params["top_p"]) * 80,
            6,
        )

    def _cost_usd(self, case: dict[str, Any], params: dict[str, Any]) -> float:
        return round(
            case["base_cost_usd"]
            + int(params["max_tokens"]) * 0.000018
            + int(params["retrieval_depth"]) * 0.0012,
            6,
        )

    def _stability(self, case: dict[str, Any], params: dict[str, Any]) -> float:
        temperature = float(params["temperature"])
        stability = 1.0 - max(0.0, temperature - 0.2) * 0.55
        stability -= max(0, int(params["retrieval_depth"]) - case["ideal_retrieval_depth"]) * 0.03
        return round(max(0.0, min(1.0, stability)), 6)

