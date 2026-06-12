from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import LLMResearchAgent, RuleBasedResearchAgent
from .branching import BranchManager, BranchRecord, branch_record_to_dict
from .decision import decision_to_dict, make_decision
from .effect import compare_runs
from .hypothesis import Hypothesis
from .llm import OpenAICompatibleClient
from .memory import MemoryManager
from .memory_index import build_memory_context, compact_memory_context, records_from_context
from .models import Budget, MetricGoal, RunSummary, TaskSpec, TrialResult
from .provenance import ProvenanceRecorder, evidence_for, load_provenance
from .registry import ResearchRegistry, resolve_research_dir
from .runner import run_task
from .spec import load_task, task_to_dict


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
    provenance = ProvenanceRecorder(research_dir)
    registry.state(
        research_id=research_id,
        status="running",
        phase="baseline",
        task=task_to_dict(task),
        agent_kind=agent_kind,
        branch_mode=branch_mode,
        memory_dir=str(memory_dir),
    )
    _write_json(research_dir / "task_snapshot.json", task_to_dict(task))
    registry.artifact("task_snapshot", research_dir / "task_snapshot.json", "Original task snapshot")
    provenance.record(
        "task_snapshot",
        "task",
        research_dir / "task_snapshot.json",
        "agentic_runner",
        supports=["baseline_task", "candidate_task"],
    )
    registry.event("research_started", {"research_id": research_id, "task_name": task.name})

    return _continue_agentic_research(
        task=task,
        research_dir=research_dir,
        registry=registry,
        repo_root=repo_root,
        memory_dir=memory_dir,
    )


def resume_agentic_research(
    runs_dir: Path,
    research_id: str | None,
    repo_root: Path,
    memory_dir: Path | None = None,
) -> dict[str, Any]:
    research_dir = resolve_research_dir(runs_dir, research_id)
    registry = ResearchRegistry(research_dir)
    state = _read_state(research_dir)
    if state.get("status") == "completed" and (research_dir / "agentic_result.json").exists():
        registry.event("resume_noop", {"reason": "research already completed"})
        return json.loads((research_dir / "agentic_result.json").read_text(encoding="utf-8"))
    task_path = research_dir / "task_snapshot.json"
    if task_path.exists():
        task = load_task(task_path)
    else:
        task = _task_from_state(state)
    return _continue_agentic_research(
        task=task,
        research_dir=research_dir,
        registry=registry,
        repo_root=repo_root,
        memory_dir=memory_dir or Path(state.get("memory_dir", "memory")),
    )


def _continue_agentic_research(
    task: TaskSpec,
    research_dir: Path,
    registry: ResearchRegistry,
    repo_root: Path,
    memory_dir: Path,
) -> dict[str, Any]:
    state = _read_state(research_dir)
    research_id = state["research_id"]
    agent_kind = state.get("agent_kind", "rule")
    branch_mode = state.get("branch_mode", "record")
    registry.state(status="running", memory_dir=str(memory_dir))

    baseline_summary = _ensure_baseline(task, research_dir, registry, state)
    baseline_analysis = _read_analysis(research_dir / "baseline", baseline_summary)
    state = _read_state(research_dir)

    hypothesis = _ensure_hypothesis(
        task=task,
        baseline_analysis=baseline_analysis,
        baseline_run_id=baseline_summary.run_id,
        research_dir=research_dir,
        registry=registry,
        memory_dir=memory_dir,
        agent_kind=agent_kind,
        state=state,
    )
    state = _read_state(research_dir)
    branch_record = _ensure_branch(
        hypothesis=hypothesis,
        research_dir=research_dir,
        registry=registry,
        repo_root=repo_root,
        branch_mode=branch_mode,
        state=state,
    )

    candidate_summary = _ensure_candidate(task, hypothesis, research_dir, registry, state)
    candidate_analysis = _read_analysis(research_dir / "candidate", candidate_summary)

    return _finalize_research(
        task=task,
        research_dir=research_dir,
        registry=registry,
        memory_dir=memory_dir,
        baseline_summary=baseline_summary,
        baseline_analysis=baseline_analysis,
        candidate_summary=candidate_summary,
        candidate_analysis=candidate_analysis,
        hypothesis=hypothesis,
        branch=branch_record_to_dict(branch_record),
        agent_kind=agent_kind,
    )


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


def _ensure_baseline(
    task: TaskSpec,
    research_dir: Path,
    registry: ResearchRegistry,
    state: dict[str, Any],
) -> RunSummary:
    if state.get("baseline_run_id"):
        baseline_dir = research_dir / "baseline" / state["baseline_run_id"]
        _register_run_artifacts(registry, baseline_dir, "baseline")
        _register_run_provenance(research_dir, baseline_dir, "baseline")
        return _summary_from_run_dir(baseline_dir, task.name)
    baseline_summary = run_task(task, research_dir / "baseline")
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
    _register_run_provenance(research_dir, baseline_dir, "baseline")
    return baseline_summary


def _ensure_hypothesis(
    task: TaskSpec,
    baseline_analysis: dict[str, Any],
    baseline_run_id: str,
    research_dir: Path,
    registry: ResearchRegistry,
    memory_dir: Path,
    agent_kind: str,
    state: dict[str, Any],
):
    if state.get("hypothesis"):
        _register_memory_context_if_present(research_dir, registry)
        hypothesis = _hypothesis_from_dict(state["hypothesis"])
        hypothesis_path = research_dir / "hypothesis.json"
        if not hypothesis_path.exists():
            _write_json(hypothesis_path, state["hypothesis"])
        registry.artifact("hypothesis", hypothesis_path, "Agent-proposed hypothesis")
        ProvenanceRecorder(research_dir).record(
            "hypothesis",
            "hypothesis",
            hypothesis_path,
            f"{agent_kind}_agent",
            depends_on=["baseline_analysis"],
            supports=["candidate_task", "effect", "decision"],
        )
        return hypothesis
    memory = MemoryManager(memory_dir)
    memory_context = build_memory_context(
        task,
        baseline_analysis,
        memory.recent_lessons(limit=50),
    )
    memory_context_path = research_dir / "memory_context.json"
    _write_json(memory_context_path, memory_context)
    registry.artifact(
        "memory_context",
        memory_context_path,
        "Ranked project memory used for hypothesis planning",
    )
    ProvenanceRecorder(research_dir).record(
        "memory_context",
        "memory_context",
        memory_context_path,
        "memory_index",
        depends_on=["baseline_analysis"],
        supports=["hypothesis"],
    )
    registry.state(memory_context=compact_memory_context(memory_context))
    agent = _make_agent(agent_kind)
    hypothesis = agent.propose(
        task,
        baseline_analysis,
        baseline_run_id,
        memories=records_from_context(memory_context),
    )
    hypothesis_dict = asdict(hypothesis)
    _write_json(research_dir / "hypothesis.json", hypothesis_dict)
    registry.artifact("hypothesis", research_dir / "hypothesis.json", "Agent-proposed hypothesis")
    ProvenanceRecorder(research_dir).record(
        "hypothesis",
        "hypothesis",
        research_dir / "hypothesis.json",
        f"{agent_kind}_agent",
        depends_on=["baseline_analysis"],
        supports=["candidate_task", "effect", "decision"],
    )
    registry.state(phase="branch", hypothesis=hypothesis_dict)
    registry.event("hypothesis_proposed", {"hypothesis_id": hypothesis.id, "title": hypothesis.title})
    return hypothesis


def _register_memory_context_if_present(
    research_dir: Path,
    registry: ResearchRegistry,
) -> None:
    memory_context_path = research_dir / "memory_context.json"
    if not memory_context_path.exists():
        return
    registry.artifact(
        "memory_context",
        memory_context_path,
        "Ranked project memory used for hypothesis planning",
    )
    ProvenanceRecorder(research_dir).record(
        "memory_context",
        "memory_context",
        memory_context_path,
        "memory_index",
        depends_on=["baseline_analysis"],
        supports=["hypothesis"],
    )


def _ensure_branch(
    hypothesis,
    research_dir: Path,
    registry: ResearchRegistry,
    repo_root: Path,
    branch_mode: str,
    state: dict[str, Any],
):
    if state.get("branch"):
        branch_record = _branch_record_from_dict(state["branch"])
        branch_path = research_dir / "branch.json"
        if not branch_path.exists():
            _write_json(branch_path, state["branch"])
        registry.artifact("branch", branch_path, "Experiment branch metadata")
        ProvenanceRecorder(research_dir).record(
            "branch",
            "branch",
            branch_path,
            "branch_manager",
            depends_on=["hypothesis"],
            supports=["candidate_task", "decision"],
        )
        return branch_record
    branch_record = BranchManager(repo_root).prepare(hypothesis.id, mode=branch_mode)
    branch_dict = branch_record_to_dict(branch_record)
    _write_json(research_dir / "branch.json", branch_dict)
    registry.artifact("branch", research_dir / "branch.json", "Experiment branch metadata")
    ProvenanceRecorder(research_dir).record(
        "branch",
        "branch",
        research_dir / "branch.json",
        "branch_manager",
        depends_on=["hypothesis"],
        supports=["candidate_task", "decision"],
    )
    registry.state(phase="candidate", branch=branch_dict)
    registry.event("branch_prepared", branch_dict)
    return branch_record


def _ensure_candidate(
    task: TaskSpec,
    hypothesis,
    research_dir: Path,
    registry: ResearchRegistry,
    state: dict[str, Any],
) -> RunSummary:
    if state.get("candidate_run_id"):
        candidate_dir = research_dir / "candidate" / state["candidate_run_id"]
        _register_run_artifacts(registry, candidate_dir, "candidate")
        _register_run_provenance(research_dir, candidate_dir, "candidate")
        return _summary_from_run_dir(candidate_dir, f"{task.name}_agentic_candidate")
    candidate_task = _candidate_task(task, hypothesis.search_space)
    candidate_summary = run_task(candidate_task, research_dir / "candidate")
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
    _register_run_provenance(research_dir, candidate_dir, "candidate")
    return candidate_summary


def _finalize_research(
    task: TaskSpec,
    research_dir: Path,
    registry: ResearchRegistry,
    memory_dir: Path,
    baseline_summary: RunSummary,
    baseline_analysis: dict[str, Any],
    candidate_summary: RunSummary,
    candidate_analysis: dict[str, Any],
    hypothesis,
    branch: dict[str, Any],
    agent_kind: str,
) -> dict[str, Any]:
    effect = compare_runs(task, baseline_analysis, candidate_analysis)
    decision = decision_to_dict(make_decision(task, baseline_analysis, candidate_analysis, effect))
    research_id = _read_state(research_dir)["research_id"]
    memory = MemoryManager(memory_dir)
    memory.record_hypothesis(hypothesis)
    memory.record_decision(
        {
            "research_id": research_id,
            "hypothesis_id": hypothesis.id,
            "effect": effect,
            "decision": decision,
            "branch": branch,
        }
    )
    memory.record_lesson(_lesson(research_id, hypothesis.id, effect, decision))

    result = {
        "research_id": research_id,
        "baseline_run_id": baseline_summary.run_id,
        "candidate_run_id": candidate_summary.run_id,
        "hypothesis": asdict(hypothesis),
        "branch": branch,
        "agent_kind": agent_kind,
        "effect": effect,
        "decision": decision,
        "paths": {
            "research_dir": str(research_dir),
            "memory_dir": str(memory_dir),
        },
    }
    _write_json(research_dir / "effect.json", result["effect"])
    registry.artifact("effect", research_dir / "effect.json", "Baseline-vs-candidate effect comparison")
    provenance = ProvenanceRecorder(research_dir)
    provenance.record(
        "effect",
        "effect",
        research_dir / "effect.json",
        "effect_evaluator",
        depends_on=["baseline_analysis", "candidate_analysis", "hypothesis"],
        supports=["decision", "lesson"],
    )
    _write_json(research_dir / "decision.json", result["decision"])
    registry.artifact("decision", research_dir / "decision.json", "Harness decision and next action")
    provenance.record(
        "decision",
        "decision",
        research_dir / "decision.json",
        "decision_engine",
        depends_on=["effect", "baseline_analysis", "candidate_analysis", "hypothesis", "branch"],
        supports=["lesson", "report", "agentic_result"],
    )
    decision_evidence = evidence_for(load_provenance(research_dir), "decision")
    _write_json(research_dir / "agentic_result.json", result)
    registry.artifact("result", research_dir / "agentic_result.json", "Complete agentic research result")
    provenance.record(
        "agentic_result",
        "result",
        research_dir / "agentic_result.json",
        "agentic_runner",
        depends_on=["decision", "effect", "hypothesis", "branch"],
        supports=["report"],
    )
    _write_report(research_dir / "report.md", result)
    registry.artifact("report", research_dir / "report.md", "Human-readable agentic research report")
    provenance.record(
        "report",
        "report",
        research_dir / "report.md",
        "agentic_runner",
        depends_on=["agentic_result", "decision", "effect"],
    )
    registry.state(
        status="completed",
        phase="completed",
        recommendation=decision["decision"],
        reason="; ".join(decision["reasons"]),
        decision=decision,
        decision_evidence=[
            {
                "artifact_id": record["artifact_id"],
                "kind": record["kind"],
                "path": record["path"],
            }
            for record in decision_evidence
        ],
    )
    registry.event("research_completed", {"recommendation": decision["decision"]})
    return result


def _make_agent(agent_kind: str):
    if agent_kind == "rule":
        return RuleBasedResearchAgent()
    if agent_kind == "llm":
        return LLMResearchAgent(OpenAICompatibleClient.from_env())
    raise ValueError(f"Unsupported agent kind: {agent_kind}")


def _read_state(research_dir: Path) -> dict[str, Any]:
    return json.loads((research_dir / "state.json").read_text(encoding="utf-8"))


def _task_from_state(state: dict[str, Any]) -> TaskSpec:
    task = state["task"]
    metrics = task["metrics"]
    return TaskSpec(
        name=task["name"],
        objective=task["objective"],
        executor=task["executor"],
        dataset=task.get("dataset"),
        search_space=task["search_space"],
        budget=Budget(max_trials=int(task["budget"]["max_trials"])),
        primary_metric=_metric_goal_from_dict(metrics["primary"]),
        guardrail_metrics=[
            _metric_goal_from_dict(item) for item in metrics.get("guardrails", [])
        ],
    )


def _metric_goal_from_dict(data: dict[str, Any]) -> MetricGoal:
    return MetricGoal(
        name=data["name"],
        direction=data.get("direction", "maximize"),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
    )


def _hypothesis_from_dict(data: dict[str, Any]) -> Hypothesis:
    return Hypothesis(
        id=data["id"],
        title=data["title"],
        rationale=data["rationale"],
        expected_effects=data["expected_effects"],
        risks=data["risks"],
        search_space=data["search_space"],
        validation_plan=data["validation_plan"],
        source_run_id=data["source_run_id"],
    )


def _branch_record_from_dict(data: dict[str, Any]) -> BranchRecord:
    return BranchRecord(
        mode=data["mode"],
        base_branch=data["base_branch"],
        base_commit=data["base_commit"],
        experiment_branch=data["experiment_branch"],
        created=bool(data["created"]),
    )


def _summary_from_run_dir(run_dir: Path, task_name: str) -> RunSummary:
    analysis = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8"))
    top_trials = analysis.get("top_trials", [])
    best_result = None
    if top_trials:
        best = top_trials[0]
        best_result = TrialResult(
            trial_id=best["trial_id"],
            params=best["params"],
            metrics=best["metrics"],
            passed_guardrails=True,
        )
    return RunSummary(
        run_id=run_dir.name,
        task_name=task_name,
        total_trials=int(analysis["total_trials"]),
        best_result=best_result,
        stop_reason=_read_stop_reason(run_dir),
    )


def _read_stop_reason(run_dir: Path) -> str:
    path = run_dir / "decisions.jsonl"
    if not path.exists():
        return "unknown"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        return "unknown"
    return records[-1].get("stop_reason", "unknown")


def _read_analysis(parent: Path, summary: RunSummary) -> dict[str, Any]:
    path = parent / summary.run_id / "analysis.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _lesson(
    research_id: str,
    hypothesis_id: str,
    effect: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    return {
        "research_id": research_id,
        "hypothesis_id": hypothesis_id,
        "lesson": "; ".join(decision["reasons"]),
        "recommendation": decision["decision"],
        "supporting_effect": effect,
        "supporting_decision": decision,
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    effect = result["effect"]
    decision = result["decision"]
    lines = [
        f"# Agentic AutoResearch Run: {result['research_id']}",
        "",
        f"- Hypothesis: `{result['hypothesis']['title']}`",
        f"- Branch mode: `{result['branch']['mode']}`",
        f"- Agent: `{result['agent_kind']}`",
        f"- Experiment branch: `{result['branch']['experiment_branch']}`",
        f"- Decision: `{decision['decision']}`",
        f"- Confidence: `{decision['confidence']:.2f}`",
        f"- Next action: `{decision['next_action']}`",
        f"- Reason: {'; '.join(decision['reasons'])}",
        "",
        "## Effect",
        "",
        "```json",
        json.dumps(effect, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Decision",
        "",
        "```json",
        json.dumps(decision, ensure_ascii=False, indent=2),
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


def _register_run_provenance(research_dir: Path, run_dir: Path, phase: str) -> None:
    recorder = ProvenanceRecorder(research_dir)
    dependencies = {
        "task": ["task_snapshot"] if phase == "baseline" else ["task_snapshot", "hypothesis"],
        "trials": [f"{phase}_task"],
        "analysis": [f"{phase}_trials"],
        "decisions": [f"{phase}_analysis"],
        "report": [f"{phase}_analysis", f"{phase}_decisions"],
    }
    producers = {
        "task": "runner",
        "trials": "executor",
        "analysis": "analysis_builder",
        "decisions": "runner",
        "report": "runner",
    }
    for stem in ["task", "trials", "analysis", "decisions", "report"]:
        suffix = "jsonl" if stem in {"trials", "decisions"} else "json" if stem != "report" else "md"
        filename = f"{stem}.{suffix}"
        path = run_dir / filename
        if path.exists():
            recorder.record(
                f"{phase}_{stem}",
                stem,
                path,
                producers[stem],
                depends_on=dependencies[stem],
                supports=_supports_for_run_artifact(phase, stem),
                metadata={"phase": phase},
            )


def _supports_for_run_artifact(phase: str, stem: str) -> list[str]:
    if stem == "analysis":
        return ["effect", "decision"]
    if stem == "trials":
        return [f"{phase}_analysis"]
    if stem == "task":
        return [f"{phase}_trials"]
    if stem == "decisions":
        return [f"{phase}_report"]
    return []
