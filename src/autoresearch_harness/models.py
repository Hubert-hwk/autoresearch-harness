from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MetricGoal:
    name: str
    direction: str = "maximize"
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class Budget:
    max_trials: int = 20


@dataclass(frozen=True)
class TaskSpec:
    name: str
    objective: str
    executor: str
    search_space: dict[str, dict[str, Any]]
    dataset: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    budget: Budget = field(default_factory=Budget)
    primary_metric: MetricGoal = field(default_factory=lambda: MetricGoal("score"))
    guardrail_metrics: list[MetricGoal] = field(default_factory=list)


@dataclass(frozen=True)
class Trial:
    id: str
    params: dict[str, Any]


@dataclass(frozen=True)
class TrialResult:
    trial_id: str
    params: dict[str, Any]
    metrics: dict[str, float]
    passed_guardrails: bool
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    task_name: str
    total_trials: int
    best_result: TrialResult | None
    stop_reason: str
