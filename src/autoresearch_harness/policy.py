from __future__ import annotations

import itertools
from typing import Any, Iterable

from .models import TaskSpec, Trial


def generate_trials(task: TaskSpec) -> Iterable[Trial]:
    names = list(task.search_space)
    values = [_values_for(task.search_space[name]) for name in names]

    for index, combo in enumerate(itertools.product(*values), start=1):
        if index > task.budget.max_trials:
            return
        yield Trial(
            id=f"trial_{index:04d}",
            params=dict(zip(names, combo)),
        )


def _values_for(spec: dict[str, Any]) -> list[Any]:
    kind = spec.get("type", "categorical")
    if kind == "categorical":
        return list(spec["values"])

    if kind in {"float", "int"}:
        start = spec["min"]
        end = spec["max"]
        steps = int(spec.get("steps", 5))
        if steps <= 1:
            values = [start]
        else:
            width = (end - start) / (steps - 1)
            values = [start + width * i for i in range(steps)]
        if kind == "int":
            return [int(round(value)) for value in values]
        return [round(float(value), 6) for value in values]

    raise ValueError(f"Unsupported search space type: {kind}")


def search_space_values(spec: dict[str, Any]) -> list[Any]:
    """Return the finite values represented by one search-space dimension."""
    return _values_for(spec)
