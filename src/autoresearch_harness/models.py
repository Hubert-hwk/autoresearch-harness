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
    max_wall_time_seconds: float | None = None
    max_fidelity_units: float | None = None


@dataclass(frozen=True)
class CommandExecution:
    command: list[str]
    working_directory: str
    metrics_path: str = "metrics.json"
    artifact_paths: list[str] = field(default_factory=list)
    timeout_seconds: float = 300.0
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MutationPolicy:
    editable_paths: list[str]
    allow_create: bool = False
    max_file_bytes: int = 1_000_000


@dataclass(frozen=True)
class AdaptiveScheduling:
    fidelity_parameter: str
    fidelity_levels: list[float]
    objectives: list[MetricGoal]
    initial_candidates: int = 8
    reduction_factor: int = 2
    random_seed: int = 0
    strategy: str = "successive_halving"
    protocol_version: str = "scheduling.v1"


@dataclass(frozen=True)
class VerificationPolicy:
    seed_parameter: str
    seeds: list[int]
    confidence_level: float = 0.95
    bootstrap_samples: int = 2000
    bootstrap_seed: int = 0
    min_primary_improvement: float = 0.0
    min_guardrail_pass_rate: float = 1.0
    metric_tolerance: float = 1e-9
    replay_metrics: list[str] = field(default_factory=list)
    fingerprint_paths: list[str] = field(default_factory=list)
    protocol_version: str = "verification.v1"


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
    schema_version: str = "task.v1"
    execution: CommandExecution | None = None
    mutation_policy: MutationPolicy | None = None
    scheduling: AdaptiveScheduling | None = None
    verification: VerificationPolicy | None = None


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
