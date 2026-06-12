from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import LLMResearchAgent, RuleBasedResearchAgent
from .branching import BranchManager, branch_record_to_dict
from .effect import compare_runs
from .llm import OpenAICompatibleClient
from .memory import MemoryManager
from .models import Budget, RunSummary, TaskSpec
from .registry import ResearchRegistry
from .runner import run_task
from .spec import task_to_dict


def run_agentic_research(
    task: TaskSpec,
    runs_dir: Path,
    repo_root: Path,
    memory_dir: Path,
    branch_mode: str = "record",
    agent_kind: str = "rule",
) -> dict[str, Any]:
    research_id = datetime.now(timezone.utc).strftime("agentic_%Y%m%dT%H%M%S%fZ")
    research_dir = runs_dir / research_id
    research_dir.mkdir(parents=True, exist_ok=False)
    registry = ResearchRegistry(research_dir)
    registry.state(
        research_id=research_id,
        status="running",
        phase="baseline",
        task=task_to_dict(task),
        agent_kind=agent_kind,
        branch_mode=branch_mode,
    )
    registry.event("research_started", {"research_id": research_id, "task_name": task.name})

    baseline_summary = run_task(task, research_dir / "baseline")
    baseline_analysis = _read_analysis(research_dir / "baseline", baseline_summary)
    baseline_dir = research_dir / "baseline" / baseline_summary.run_id
    registry.state(phase="hypothesis", baseline_run_id=baseline_summary.run_id)
    registry.event(
        "baseline_completed",
        {
            "run_id": baseline_summary.run_id,
            "total_trials": baseline_summary.total_trials,
            "best_trial_id": baseline_summary.best_result.trial_id
            if baseline_summary.best_result
            else None,
        },
    )
    _register_run_artifacts(registry, baseline_dir, "baseline")

    memory = MemoryManager(memory_dir)
    agent = _make_agent(agent_kind)
    hypothesis = agent.propose(
        task,
        baseline_analysis,
        baseline_summary.run_id,
        memories=memory.recent_lessons(),
    )
    registry.state(phase="branch", hypothesis=asdict(hypothesis))
    registry.event("hypothesis_proposed", {"hypothesis_id": hypothesis.id, "title": hypothesis.title})
    branch_record = BranchManager(repo_root).prepare(hypothesis.id, mode=branch_mode)
    registry.state(phase="candidate", branch=branch_record_to_dict(branch_record))
    registry.event("branch_prepared", branch_record_to_dict(branch_record))

    candidate_task = _candidate_task(task, hypothesis.search_space)
    candidate_summary = run_task(candidate_task, research_dir / "candidate")
    candidate_analysis = _read_analysis(research_dir / "candidate", candidate_summary)
    candidate_dir = research_dir / "candidate" / candidate_summary.run_id
    registry.state(phase="evaluation", candidate_run_id=candidate_summary.run_id)
    registry.event(
        "candidate_completed",
        {
            "run_id": candidate_summary.run_id,
            "total_trials": candidate_summary.total_trials,
            "best_trial_id": candidate_summary.best_result.trial_id
            if candidate_summary.best_result
            else None,
        },
    )
    _register_run_artifacts(registry, candidate_dir, "candidate")

    effect = compare_runs(task, baseline_analysis, candidate_analysis)
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
        "agent_kind": agent_kind,
        "effect": effect,
        "paths": {
            "research_dir": str(research_dir),
            "memory_dir": str(memory_dir),
        },
    }
    _write_json(research_dir / "hypothesis.json", result["hypothesis"])
    registry.artifact("hypothesis", research_dir / "hypothesis.json", "Agent-proposed hypothesis")
    _write_json(research_dir / "branch.json", result["branch"])
    registry.artifact("branch", research_dir / "branch.json", "Experiment branch metadata")
    _write_json(research_dir / "effect.json", result["effect"])
    registry.artifact("effect", research_dir / "effect.json", "Baseline-vs-candidate effect comparison")
    _write_json(research_dir / "agentic_result.json", result)
    registry.artifact("result", research_dir / "agentic_result.json", "Complete agentic research result")
    _write_report(research_dir / "report.md", result)
    registry.artifact("report", research_dir / "report.md", "Human-readable agentic research report")
    registry.state(
        status="completed",
        phase="completed",
        recommendation=effect["recommendation"],
        reason=effect["reason"],
    )
    registry.event("research_completed", {"recommendation": effect["recommendation"]})
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


def _make_agent(agent_kind: str):
    if agent_kind == "rule":
        return RuleBasedResearchAgent()
    if agent_kind == "llm":
        return LLMResearchAgent(OpenAICompatibleClient.from_env())
    raise ValueError(f"Unsupported agent kind: {agent_kind}")


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
        f"- Agent: `{result['agent_kind']}`",
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


def _register_run_artifacts(registry: ResearchRegistry, run_dir: Path, phase: str) -> None:
    for filename, description in [
        ("task.json", "Resolved task specification"),
        ("trials.jsonl", "Trial-level metrics and guardrail results"),
        ("analysis.json", "Run analysis with pass rate, failures, and top trials"),
        ("decisions.jsonl", "Run decision events"),
        ("report.md", "Human-readable run report"),
    ]:
        path = run_dir / filename
        if path.exists():
            registry.artifact(
                f"{phase}_{path.stem}",
                path,
                f"{phase} {description}",
                {"phase": phase, "filename": filename},
            )
