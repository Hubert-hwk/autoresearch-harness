from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

from ..evaluation import passes_guardrails
from ..models import TaskSpec, Trial, TrialResult


class PromptTuningExecutor:
    """Deterministic prompt tuning simulator for harness validation."""

    def __init__(self, task: TaskSpec):
        if not task.dataset:
            raise ValueError("prompt_tuning requires a dataset path")
        self.task = task
        self.cases = [
            json.loads(line)
            for line in Path(task.dataset).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def run(self, trial: Trial) -> TrialResult:
        scores: list[float] = []
        hallucination_rates: list[float] = []
        token_counts: list[float] = []

        for case in self.cases:
            answer = self._simulate_answer(case, trial.params)
            scores.append(_keyword_recall(answer, case["expected_keywords"]))
            hallucination_rates.append(_keyword_hit_rate(answer, case.get("forbidden_keywords", [])))
            token_counts.append(float(len(answer.split())))

        metrics = {
            "accuracy": statistics.fmean(scores),
            "hallucination_rate": statistics.fmean(hallucination_rates),
            "avg_tokens": statistics.fmean(token_counts),
        }
        passed, notes = passes_guardrails(self.task, metrics)
        return TrialResult(
            trial_id=trial.id,
            params=trial.params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )

    def _simulate_answer(self, case: dict[str, Any], params: dict[str, Any]) -> str:
        style = params["style"]
        evidence = params["evidence_policy"]
        length = params["length"]

        selected = list(case["base_keywords"])
        if evidence in {"cite_context", "strict_context"}:
            selected.extend(case["context_keywords"])
        if style == "structured":
            selected.extend(case["structured_bonus_keywords"])
        if style == "creative":
            selected.extend(case.get("risky_keywords", []))
        if evidence == "loose":
            selected.extend(case.get("forbidden_keywords", [])[:1])

        if length == "short":
            selected = selected[:4]
        elif length == "long":
            selected.extend(case.get("extra_keywords", []))

        return " ".join(dict.fromkeys(selected))


def _keyword_recall(answer: str, expected_keywords: list[str]) -> float:
    if not expected_keywords:
        return 1.0
    normalized = _normalize(answer)
    hits = sum(1 for keyword in expected_keywords if _normalize(keyword) in normalized)
    return hits / len(expected_keywords)


def _keyword_hit_rate(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    normalized = _normalize(answer)
    hits = sum(1 for keyword in keywords if _normalize(keyword) in normalized)
    return hits / len(keywords)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()

