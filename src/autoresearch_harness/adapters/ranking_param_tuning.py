from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from ..evaluation import passes_guardrails
from ..models import TaskSpec, Trial, TrialResult


class RankingParamTuningExecutor:
    """Local ranking simulation for search/ads/recommendation parameter tuning."""

    def __init__(self, task: TaskSpec):
        if not task.dataset:
            raise ValueError("ranking_param_tuning requires a dataset path")
        self.task = task
        self.queries = [
            json.loads(line)
            for line in Path(task.dataset).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def run(self, trial: Trial) -> TrialResult:
        ndcg_scores: list[float] = []
        latencies: list[float] = []
        revenues: list[float] = []

        for query in self.queries:
            ranked = sorted(
                query["items"],
                key=lambda item: self._score(item, trial.params),
                reverse=True,
            )
            topk = ranked[:3]
            ndcg_scores.append(_ndcg_at_k(topk, query["items"], k=3))
            latencies.append(self._latency_ms(topk, trial.params))
            revenues.append(sum(item["bid"] * item["conversion_prob"] for item in topk))

        metrics = {
            "ndcg_at_3": statistics.fmean(ndcg_scores),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "revenue": statistics.fmean(revenues),
        }
        passed, notes = passes_guardrails(self.task, metrics)
        return TrialResult(
            trial_id=trial.id,
            params=trial.params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )

    def _score(self, item: dict[str, float], params: dict[str, Any]) -> float:
        return (
            params["relevance_weight"] * item["relevance"]
            + params["ctr_weight"] * item["ctr"]
            + params["bid_weight"] * item["bid"]
            + params["freshness_weight"] * item["freshness"]
            - params["latency_penalty"] * item["latency_ms"] / 100.0
        )

    def _latency_ms(self, items: list[dict[str, float]], params: dict[str, Any]) -> float:
        base = max(item["latency_ms"] for item in items)
        complexity = 2.0 + params["relevance_weight"] * 1.8 + params["ctr_weight"] * 1.2
        return base + complexity


def _ndcg_at_k(ranked_items: list[dict[str, float]], all_items: list[dict[str, float]], k: int) -> float:
    dcg = _dcg([item["label"] for item in ranked_items[:k]])
    ideal = _dcg(sorted((item["label"] for item in all_items), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg / ideal


def _dcg(labels: list[float]) -> float:
    return sum((2**label - 1) / math.log2(index + 2) for index, label in enumerate(labels))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]

