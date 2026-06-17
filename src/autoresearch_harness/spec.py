from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Budget, MetricGoal, TaskSpec


def load_task(path: Path) -> TaskSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    dataset = data.get("dataset")
    if dataset:
        dataset = str((root / dataset).resolve())

    metrics = data.get("metrics", {})
    primary = metrics.get("primary", {"name": "score", "direction": "maximize"})
    guardrails = metrics.get("guardrails", [])

    return TaskSpec(
        name=data["name"],
        objective=data["objective"],
        executor=data["executor"],
        dataset=dataset,
        search_space=data["search_space"],
        metadata=dict(data.get("metadata", {})),
        budget=Budget(max_trials=int(data.get("budget", {}).get("max_trials", 20))),
        primary_metric=_metric_goal(primary),
        guardrail_metrics=[_metric_goal(item) for item in guardrails],
    )


def task_to_dict(task: TaskSpec) -> dict[str, Any]:
    return {
        "name": task.name,
        "objective": task.objective,
        "executor": task.executor,
        "dataset": task.dataset,
        "metadata": task.metadata,
        "search_space": task.search_space,
        "budget": {"max_trials": task.budget.max_trials},
        "metrics": {
            "primary": task.primary_metric.__dict__,
            "guardrails": [item.__dict__ for item in task.guardrail_metrics],
        },
    }


def _metric_goal(data: dict[str, Any]) -> MetricGoal:
    return MetricGoal(
        name=data["name"],
        direction=data.get("direction", "maximize"),
        min_value=data.get("min"),
        max_value=data.get("max"),
    )
