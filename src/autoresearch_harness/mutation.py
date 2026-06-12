from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from .hypothesis import Hypothesis
from .models import Budget, TaskSpec
from .spec import task_to_dict


@dataclass(frozen=True)
class MutationOperation:
    op: str
    target: str
    before: Any
    after: Any
    rationale: str


@dataclass(frozen=True)
class MutationPlan:
    hypothesis_id: str
    task_name: str
    protocol_version: str
    operations: list[MutationOperation]
    candidate_search_space: dict[str, dict[str, Any]]
    candidate_budget: int
    safety_checks: list[str]


@dataclass(frozen=True)
class MutationArtifact:
    task_path: str
    diff_path: str
    changed: bool
    diff_exit_code: int


def build_mutation_plan(task: TaskSpec, hypothesis: Hypothesis) -> MutationPlan:
    candidate_search_space = _validated_search_space(task.search_space, hypothesis.search_space)
    operations = _search_space_operations(task.search_space, candidate_search_space)
    if not operations:
        operations = [
            MutationOperation(
                op="preserve",
                target="search_space",
                before=task.search_space,
                after=candidate_search_space,
                rationale="Hypothesis did not require narrowing the task search space.",
            )
        ]

    return MutationPlan(
        hypothesis_id=hypothesis.id,
        task_name=task.name,
        protocol_version="mutation.v1",
        operations=operations,
        candidate_search_space=candidate_search_space,
        candidate_budget=_search_space_size(candidate_search_space),
        safety_checks=[
            "candidate_search_space_is_subset_of_task",
            "mutation_operations_are_declarative",
            "candidate_budget_matches_search_space_size",
        ],
    )


def apply_mutation_plan(task: TaskSpec, plan: MutationPlan) -> TaskSpec:
    return replace(
        task,
        name=f"{task.name}_agentic_candidate",
        search_space=plan.candidate_search_space,
        budget=Budget(max_trials=plan.candidate_budget),
    )


def materialize_mutation_artifact(
    task: TaskSpec,
    plan: MutationPlan,
    artifact_dir: Path,
    repo_root: Path,
) -> MutationArtifact:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = artifact_dir / "baseline_task.json"
    candidate_path = artifact_dir / "candidate_task.json"
    diff_path = artifact_dir / "mutation.diff"

    baseline_payload = task_to_dict(task)
    candidate_payload = task_to_dict(apply_mutation_plan(task, plan))
    baseline_path.write_text(
        json.dumps(baseline_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(candidate_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo_root.as_posix()}",
            "diff",
            "--no-index",
            "--",
            str(baseline_path),
            str(candidate_path),
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "git diff --no-index failed")
    diff_path.write_text(completed.stdout, encoding="utf-8")
    return MutationArtifact(
        task_path=str(candidate_path),
        diff_path=str(diff_path),
        changed=completed.returncode == 1,
        diff_exit_code=completed.returncode,
    )


def mutation_plan_to_dict(plan: MutationPlan) -> dict[str, Any]:
    return asdict(plan)


def mutation_artifact_to_dict(artifact: MutationArtifact) -> dict[str, Any]:
    return asdict(artifact)


def mutation_artifact_from_dict(data: dict[str, Any]) -> MutationArtifact:
    return MutationArtifact(
        task_path=data["task_path"],
        diff_path=data["diff_path"],
        changed=bool(data["changed"]),
        diff_exit_code=int(data["diff_exit_code"]),
    )


def mutation_plan_from_dict(data: dict[str, Any]) -> MutationPlan:
    return MutationPlan(
        hypothesis_id=data["hypothesis_id"],
        task_name=data["task_name"],
        protocol_version=data["protocol_version"],
        operations=[
            MutationOperation(
                op=item["op"],
                target=item["target"],
                before=item.get("before"),
                after=item.get("after"),
                rationale=item["rationale"],
            )
            for item in data.get("operations", [])
        ],
        candidate_search_space=data["candidate_search_space"],
        candidate_budget=int(data["candidate_budget"]),
        safety_checks=list(data.get("safety_checks", [])),
    )


def _validated_search_space(
    original: dict[str, dict[str, Any]],
    proposed: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    validated: dict[str, dict[str, Any]] = {}
    for name, original_spec in original.items():
        candidate_spec = dict(original_spec)
        proposed_spec = proposed.get(name)
        if proposed_spec is None:
            validated[name] = candidate_spec
            continue

        if original_spec.get("type", "categorical") == "categorical":
            original_values = list(original_spec.get("values", []))
            proposed_values = list(proposed_spec.get("values", []))
            filtered = [value for value in proposed_values if value in original_values]
            if filtered:
                candidate_spec["values"] = filtered
        elif original_spec.get("type") in {"float", "int"}:
            min_value = max(original_spec["min"], proposed_spec.get("min", original_spec["min"]))
            max_value = min(original_spec["max"], proposed_spec.get("max", original_spec["max"]))
            if min_value <= max_value:
                candidate_spec["min"] = min_value
                candidate_spec["max"] = max_value
                if "steps" in proposed_spec:
                    candidate_spec["steps"] = max(1, int(proposed_spec["steps"]))
        validated[name] = candidate_spec
    return validated


def _search_space_operations(
    original: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
) -> list[MutationOperation]:
    operations: list[MutationOperation] = []
    for name, candidate_spec in candidate.items():
        original_spec = original[name]
        if candidate_spec == original_spec:
            continue
        operations.append(
            MutationOperation(
                op="replace_search_space_param",
                target=f"search_space.{name}",
                before=original_spec,
                after=candidate_spec,
                rationale="Apply bounded hypothesis search-space narrowing.",
            )
        )
    return operations


def _search_space_size(search_space: dict[str, dict[str, Any]]) -> int:
    total = 1
    for spec in search_space.values():
        if spec.get("type", "categorical") == "categorical":
            total *= len(spec["values"])
        else:
            total *= int(spec.get("steps", 5))
    return total
