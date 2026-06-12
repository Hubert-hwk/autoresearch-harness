from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Hypothesis:
    id: str
    title: str
    rationale: str
    expected_effects: dict[str, str]
    risks: list[str]
    search_space: dict[str, dict[str, Any]]
    validation_plan: str
    source_run_id: str


@dataclass(frozen=True)
class TrialPlan:
    hypothesis_id: str
    task_name: str
    search_space: dict[str, dict[str, Any]]
    validation_plan: str
    metadata: dict[str, Any] = field(default_factory=dict)

