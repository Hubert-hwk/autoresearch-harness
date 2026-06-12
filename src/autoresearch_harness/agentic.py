from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import RuleBasedResearchAgent
from .branching import BranchManager, branch_record_to_dict
from .effect import compare_runs
from .memory import MemoryManager
from .models import Budget, RunSummary, TaskSpec
from .runner import run_task


def run_agentic_research(
    task: TaskSpec,
    runs_dir: Path,
    repo_root: Path,
    memory_dir: Path,
    branch_mode: str = "record",
) -> dict[str, Any]:
    research_id = datetime.now(timezone.utc).strftime("agentic_%Y%m%dT%H%M%S%fZ")
    research_dir = runs_dir / research_id
    research_dir.mkdir(parents=True, exist_ok=False)

    baseline_summary = run_task(task, research_dir / "baseline")
    baseline_analysis = _read_analysis(research_dir / "baseline", baseline_summary)

    agent = RuleBasedResearchAgent()
    hypothesis = agent.propose(task, baseline_analysis, baseline_summary.run_id)
    branch_record = BranchManager(repo_root).prepare(hypothesis.id, mode=branch_mode)

    candidate_task = _candidate_task(task, hypothesis.search_space)
    candidate_summary = run_task(candidate_task, research_dir / "candidate")
    candidate_analysis = _read_analysis(research_dir / "candidate", candidate_summary)

    effect = compare_runs(task, baseline_analysis, candidate_analysis)
    memory = MemoryManager(memory_dir)
    memory.record_hypothesis(hypothesis)
    memory.record_decision(
        {
            "research_id": research_id,
            "hypothesis_id": hypothesis.id,
            "effect": effect,
            "branch": branch_record_to_dict(branch_record),
        }
    )
    memory.record_lesson(_lesson(research_id, hypothesis.id, effect))

    result = {
        "research_id": research_id,
        "baseline_run_id": baseline_summary.run_id,
        "candidate_run_id": candidate_summary.run_id,
        "hypothesis": asdict(hypothesis),
        "branch": branch_record_to_dict(branch_record),
        "effect": effect,
        "paths": {
            "research_dir": str(research_dir),
            "memory_dir": str(memory_dir),
        },
    }
    _write_json(research_dir / "hypothesis.json", result["hypothesis"])
    _write_json(research_dir / "branch.json", result["branch"])
    _write_json(research_dir / "effect.json", result["effect"])
    _write_json(research_dir / "agentic_result.json", result)
    _write_report(research_dir / "report.md", result)
    return result


def _candidate_task(task: TaskSpec, search_space: dict[str, dict[str, Any]]) -> TaskSpec:
    max_trials = 1
    for spec in search_space.values():
        if spec.get("type", "categorical") == "categorical":
            max_trials *= len(spec["values"])
        else:
            max_trials *= int(spec.get("steps", 5))
    return replace(
        task,
        name=f"{task.name}_agentic_candidate",
        search_space=search_space,
        budget=Budget(max_trials=max_trials),
    )


def _read_analysis(parent: Path, summary: RunSummary) -> dict[str, Any]:
    path = parent / summary.run_id / "analysis.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lesson(research_id: str, hypothesis_id: str, effect: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_id": research_id,
        "hypothesis_id": hypothesis_id,
        "lesson": effect["reason"],
        "recommendation": effect["recommendation"],
        "supporting_effect": effect,
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    effect = result["effect"]
    lines = [
        f"# Agentic AutoResearch Run: {result['research_id']}",
        "",
        f"- Hypothesis: `{result['hypothesis']['title']}`",
        f"- Branch mode: `{result['branch']['mode']}`",
        f"- Experiment branch: `{result['branch']['experiment_branch']}`",
        f"- Recommendation: `{effect['recommendation']}`",
        f"- Reason: {effect['reason']}",
        "",
        "## Effect",
        "",
        "```json",
        json.dumps(effect, ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

