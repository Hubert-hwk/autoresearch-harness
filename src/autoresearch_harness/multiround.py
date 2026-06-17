from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agentic import run_agentic_research
from .models import TaskSpec
from .spec import load_task, task_to_dict


DEFAULT_EXTENDED_SEEDS = [
    20260612,
    20260613,
    20260614,
    20260615,
    20260616,
    20260617,
    20260618,
]


def run_multi_round_research(
    task: TaskSpec,
    runs_dir: Path,
    repo_root: Path,
    memory_dir: Path,
    *,
    max_rounds: int = 3,
    branch_mode: str = "record",
    agent_kind: str = "rule",
    review_seed_count: int = 5,
) -> dict[str, Any]:
    multi_round_id = datetime.now(timezone.utc).strftime("multi_round_%Y%m%dT%H%M%S%fZ")
    multi_round_dir = runs_dir / multi_round_id
    multi_round_dir.mkdir(parents=True, exist_ok=False)

    current_task = task
    trace: list[dict[str, Any]] = []
    stop_reason = "max_rounds_exhausted"

    for round_index in range(1, max_rounds + 1):
        round_id = f"round_{round_index:03d}"
        round_dir = multi_round_dir / round_id
        round_dir.mkdir(parents=True, exist_ok=False)
        task_path = round_dir / "input_task.json"
        _write_json(task_path, task_to_dict(current_task))

        result = run_agentic_research(
            task=current_task,
            runs_dir=round_dir,
            repo_root=repo_root,
            memory_dir=memory_dir,
            branch_mode=branch_mode,
            agent_kind=agent_kind,
        )
        decision = result["decision"]["decision"]
        trace_record = {
            "round": round_index,
            "round_id": round_id,
            "research_id": result["research_id"],
            "decision": decision,
            "next_action": result["decision"]["next_action"],
            "effect": result["effect"],
            "hypothesis_id": result["hypothesis"]["id"],
            "hypothesis_title": result["hypothesis"]["title"],
            "input_task_path": str(task_path),
            "research_dir": result["paths"]["research_dir"],
            "seed_count": _seed_count(current_task),
        }
        trace.append(trace_record)
        _append_jsonl(multi_round_dir / "optimization_trace.jsonl", trace_record)

        if decision == "accept":
            current_task = _promoted_candidate_task(result)
            stop_reason = "accepted_candidate_promoted"
            if round_index == max_rounds:
                break
            continue

        if decision == "needs_review" and current_task.executor == "recommender_bpr":
            expanded = _with_review_seeds(current_task, review_seed_count)
            if expanded.metadata == current_task.metadata:
                stop_reason = "needs_review_after_max_validation_strength"
                break
            current_task = expanded
            stop_reason = "needs_review_scheduled_revalidation"
            continue

        stop_reason = f"stopped_on_{decision}"
        break

    if stop_reason == "needs_review_scheduled_revalidation" and trace:
        stop_reason = "max_rounds_exhausted_pending_revalidation"

    result = {
        "multi_round_id": multi_round_id,
        "status": "completed",
        "rounds_completed": len(trace),
        "stop_reason": stop_reason,
        "final_decision": trace[-1]["decision"] if trace else None,
        "trace": trace,
        "paths": {
            "multi_round_dir": str(multi_round_dir),
            "memory_dir": str(memory_dir),
        },
    }
    _write_json(multi_round_dir / "round_summary.json", result)
    _write_report(multi_round_dir / "report.md", result)
    return result


def _promoted_candidate_task(result: dict[str, Any]) -> TaskSpec:
    return load_task(Path(result["mutation_artifact"]["task_path"]))


def _with_review_seeds(task: TaskSpec, review_seed_count: int) -> TaskSpec:
    current = list(task.metadata.get("seeds", []))
    if not current:
        current = DEFAULT_EXTENDED_SEEDS[:3]
    target_count = min(max(review_seed_count, len(current) + 2), len(DEFAULT_EXTENDED_SEEDS))
    if len(current) >= target_count:
        return task
    expanded = list(dict.fromkeys(current + DEFAULT_EXTENDED_SEEDS))[:target_count]
    metadata = dict(task.metadata)
    metadata["seeds"] = expanded
    metadata["validation_mode"] = "expanded_seed_review"
    return replace(task, metadata=metadata)


def _seed_count(task: TaskSpec) -> int | None:
    seeds = task.metadata.get("seeds")
    if seeds is None:
        return None
    return len(seeds)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    lines = [
        f"# Multi-Round AutoResearch Run: {result['multi_round_id']}",
        "",
        f"- Status: `{result['status']}`",
        f"- Rounds completed: `{result['rounds_completed']}`",
        f"- Final decision: `{result['final_decision']}`",
        f"- Stop reason: `{result['stop_reason']}`",
        "",
        "## Rounds",
        "",
    ]
    for record in result["trace"]:
        lines.extend(
            [
                f"### {record['round_id']}",
                "",
                f"- Research id: `{record['research_id']}`",
                f"- Decision: `{record['decision']}`",
                f"- Next action: `{record['next_action']}`",
                f"- Hypothesis: `{record['hypothesis_title']}`",
                f"- Seed count: `{record['seed_count']}`",
                "",
                "```json",
                json.dumps(record["effect"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
