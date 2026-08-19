from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adaptive import run_adaptive_task
from .applied import run_patch_experiment
from .experiment_graph import rebuild_experiment_graph
from .evidence_memory import (
    EvidenceMemoryStore,
    ingest_verification_memory,
    query_evidence_memory,
)
from .agentic import resume_agentic_research, run_agentic_research
from .multiround import run_multi_round_research
from .patching import load_patch_plan
from .registry import load_research_status
from .runner import run_task
from .spec import load_task
from .verification import load_parameter_set, replay_verification, run_verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an autoresearch task")
    run_parser.add_argument("task", type=Path)
    run_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))

    adaptive_parser = subparsers.add_parser(
        "adaptive-run",
        help="run deterministic successive halving with global budgets",
    )
    adaptive_parser.add_argument("task", type=Path)
    adaptive_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    adaptive_parser.add_argument("--repo-root", type=Path, default=Path("."))

    verify_parser = subparsers.add_parser(
        "verify-run",
        help="run paired repeated-seed verification and independent promotion gates",
    )
    verify_parser.add_argument("task", type=Path)
    verify_parser.add_argument("baseline_params", type=Path)
    verify_parser.add_argument("candidate_params", type=Path)
    verify_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    verify_parser.add_argument("--repo-root", type=Path, default=Path("."))

    replay_parser = subparsers.add_parser(
        "replay",
        help="replay a verification manifest after fingerprint validation",
    )
    replay_parser.add_argument("manifest_or_dir", type=Path)
    replay_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    replay_parser.add_argument("--allow-drift", action="store_true")

    memory_ingest_parser = subparsers.add_parser(
        "memory-ingest",
        help="ingest a verified and replayed result into durable evidence memory",
    )
    memory_ingest_parser.add_argument("verification_dir", type=Path)
    memory_ingest_parser.add_argument("replay_result", type=Path)
    memory_ingest_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    memory_ingest_parser.add_argument("--supersedes", action="append", default=[])
    memory_ingest_parser.add_argument("--valid-days", type=float)

    memory_query_parser = subparsers.add_parser(
        "memory-query",
        help="query active evidence memory under the current task scope",
    )
    memory_query_parser.add_argument("task", type=Path)
    memory_query_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    memory_query_parser.add_argument("--repo-root", type=Path, default=Path("."))
    memory_query_parser.add_argument("--limit", type=int, default=10)
    memory_query_parser.add_argument("--json", action="store_true")

    memory_invalidate_parser = subparsers.add_parser(
        "memory-invalidate",
        help="invalidate an active evidence memory with an append-only event",
    )
    memory_invalidate_parser.add_argument("memory_id")
    memory_invalidate_parser.add_argument("--reason", required=True)
    memory_invalidate_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))

    memory_status_parser = subparsers.add_parser(
        "memory-status",
        help="validate and rebuild the evidence memory snapshot",
    )
    memory_status_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    memory_status_parser.add_argument("--json", action="store_true")

    patch_parser = subparsers.add_parser(
        "patch-run",
        help="apply a typed patch in a detached worktree and evaluate it",
    )
    patch_parser.add_argument("task", type=Path)
    patch_parser.add_argument("patch_plan", type=Path)
    patch_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    patch_parser.add_argument("--workspaces-dir", type=Path, default=Path("runs/worktrees"))
    patch_parser.add_argument("--repo-root", type=Path, default=Path("."))
    patch_parser.add_argument("--base-commit", default="HEAD")
    patch_parser.add_argument("--graph-dir", type=Path)
    patch_parser.add_argument("--graph-id")
    patch_parser.add_argument("--node-id")
    patch_parser.add_argument("--parent-node", action="append", default=[])

    graph_parser = subparsers.add_parser(
        "graph-status",
        help="validate event integrity and rebuild an experiment graph view",
    )
    graph_parser.add_argument("graph_dir", type=Path)
    graph_parser.add_argument("--json", action="store_true")

    research_parser = subparsers.add_parser("research", help="run an agentic research loop")
    research_parser.add_argument("task", type=Path)
    research_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    research_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    research_parser.add_argument("--repo-root", type=Path, default=Path("."))
    research_parser.add_argument("--branch-mode", choices=["record", "create"], default="record")
    research_parser.add_argument("--agent", choices=["rule", "llm"], default="rule")

    multi_parser = subparsers.add_parser("multi-round", help="run a multi-round agentic research loop")
    multi_parser.add_argument("task", type=Path)
    multi_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    multi_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    multi_parser.add_argument("--repo-root", type=Path, default=Path("."))
    multi_parser.add_argument("--branch-mode", choices=["record", "create"], default="record")
    multi_parser.add_argument("--agent", choices=["rule", "llm"], default="rule")
    multi_parser.add_argument("--max-rounds", type=int, default=3)
    multi_parser.add_argument("--review-seed-count", type=int, default=5)

    status_parser = subparsers.add_parser("status", help="show a prior agentic research run")
    status_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    status_parser.add_argument("--research-id")
    status_parser.add_argument("--json", action="store_true")

    resume_parser = subparsers.add_parser("resume", help="resume an interrupted agentic run")
    resume_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    resume_parser.add_argument("--research-id")
    resume_parser.add_argument("--memory-dir", type=Path)
    resume_parser.add_argument("--repo-root", type=Path, default=Path("."))

    args = parser.parse_args(argv)

    if args.command == "run":
        task = load_task(args.task)
        summary = run_task(task, args.runs_dir)
        best = summary.best_result
        print(f"run_id={summary.run_id}")
        print(f"trials={summary.total_trials}")
        print(f"stop_reason={summary.stop_reason}")
        if best:
            print(f"best_trial={best.trial_id}")
            print(f"best_metrics={best.metrics}")
            print(f"best_params={best.params}")
        else:
            print("best_trial=None")
        return 0

    if args.command == "adaptive-run":
        result = run_adaptive_task(
            load_task(args.task),
            args.runs_dir,
            repo_root=args.repo_root.resolve(),
        )
        print(f"run_id={result['run_id']}")
        print(f"stop_reason={result['stop_reason']}")
        print(f"budget_usage={result['budget_usage']}")
        print(
            "pareto_candidates="
            f"{result['pareto_archive']['final_candidate_ids']}"
        )
        print(f"best_result={result['best_result']}")
        return 0

    if args.command == "verify-run":
        result = run_verification(
            load_task(args.task),
            load_parameter_set(args.baseline_params),
            load_parameter_set(args.candidate_params),
            args.runs_dir,
            repo_root=args.repo_root.resolve(),
        )
        interval = result["statistics"]["paired_interval"]
        print(f"verification_id={result['verification_id']}")
        print(f"decision={result['decision']['decision']}")
        print(f"stop_reason={result['stop_reason']}")
        print(f"fingerprint_id={result['fingerprint_id']}")
        print(f"paired_interval={interval}")
        print(f"replay_manifest={result['paths']['replay_manifest']}")
        return 0

    if args.command == "replay":
        result = replay_verification(
            args.manifest_or_dir,
            args.runs_dir,
            allow_drift=args.allow_drift,
        )
        print(f"replay_id={result['replay_id']}")
        print(f"status={result['status']}")
        print(f"matched={result['matched']}")
        print(f"drift_components={result['drift_components']}")
        print(f"mismatches={len(result['mismatches'])}")
        return 0

    if args.command == "memory-ingest":
        memory = ingest_verification_memory(
            args.verification_dir,
            args.replay_result,
            args.memory_dir,
            supersedes=args.supersedes,
            valid_days=args.valid_days,
        )
        print(f"memory_id={memory['memory_id']}")
        print(f"claim_type={memory['claim_type']}")
        print(f"status={memory['validity']['status']}")
        return 0

    if args.command == "memory-query":
        result = query_evidence_memory(
            load_task(args.task),
            args.memory_dir,
            repo_root=args.repo_root.resolve(),
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"total_memories={result['total_memories']}")
            print(f"matched={len(result['matched'])}")
            for match in result["matched"]:
                print(
                    f"memory={match['memory_id']} score={match['score']} "
                    f"claim_type={match['memory']['claim_type']}"
                )
        return 0

    if args.command == "memory-invalidate":
        memory = EvidenceMemoryStore(args.memory_dir).invalidate(
            args.memory_id,
            args.reason,
        )
        print(f"memory_id={memory['memory_id']}")
        print(f"status={memory['validity']['status']}")
        return 0

    if args.command == "memory-status":
        snapshot = EvidenceMemoryStore(args.memory_dir).snapshot()
        if args.json:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            statuses: dict[str, int] = {}
            for memory in snapshot["memories"]:
                status = memory["validity"]["status"]
                statuses[status] = statuses.get(status, 0) + 1
            print(f"events={snapshot['event_count']}")
            print(f"head_event_hash={snapshot['head_event_hash']}")
            print(f"memories={len(snapshot['memories'])}")
            print(f"statuses={statuses}")
        return 0

    if args.command == "patch-run":
        task = load_task(args.task)
        patch_plan = load_patch_plan(args.patch_plan)
        result = run_patch_experiment(
            task,
            patch_plan,
            repo_root=args.repo_root.resolve(),
            runs_dir=args.runs_dir,
            workspaces_dir=args.workspaces_dir,
            base_commit=args.base_commit,
            graph_dir=args.graph_dir,
            graph_id=args.graph_id,
            node_id=args.node_id,
            parent_node_ids=args.parent_node,
        )
        print(f"experiment_id={result['experiment_id']}")
        print(f"base_commit={result['base_commit']}")
        print(f"workspace={result['workspace']['workspace_path']}")
        print(f"candidate_run_id={result['candidate_run_id']}")
        print(f"best_result={result['candidate']['best_result']}")
        return 0

    if args.command == "graph-status":
        snapshot = rebuild_experiment_graph(args.graph_dir)
        if args.json:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            print(f"graph_id={snapshot['graph_id']}")
            print(f"events={snapshot['event_count']}")
            print(f"head_event_hash={snapshot['head_event_hash']}")
            print(f"nodes={len(snapshot['nodes'])}")
            for node in snapshot["nodes"]:
                print(
                    f"node={node['node_id']} status={node['status']} "
                    f"parents={','.join(node['parent_ids']) or '-'}"
                )
        return 0

    if args.command == "research":
        task = load_task(args.task)
        result = run_agentic_research(
            task=task,
            runs_dir=args.runs_dir,
            repo_root=args.repo_root.resolve(),
            memory_dir=args.memory_dir,
            branch_mode=args.branch_mode,
            agent_kind=args.agent,
        )
        decision = result.get("decision", {})
        print(f"research_id={result['research_id']}")
        print(f"hypothesis={result['hypothesis']['title']}")
        print(f"branch={result['branch']['experiment_branch']}")
        print(f"recommendation={decision.get('decision', result.get('effect', {}).get('recommendation'))}")
        print(f"reason={'; '.join(decision.get('reasons', []))}")
        return 0

    if args.command == "status":
        status = load_research_status(args.runs_dir, args.research_id)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            state = status["state"]
            print(f"research_id={status['research_id']}")
            print(f"status={state.get('status')}")
            print(f"phase={state.get('phase')}")
            print(f"agent={state.get('agent_kind')}")
            print(f"baseline_run_id={state.get('baseline_run_id')}")
            print(f"candidate_run_id={state.get('candidate_run_id')}")
            branch_lifecycle = state.get("branch_lifecycle") or {}
            print(f"branch_lifecycle={branch_lifecycle.get('status')}")
            print(f"branch_disposition={branch_lifecycle.get('disposition')}")
            print(f"recommendation={state.get('recommendation')}")
            print(f"events={len(status['events'])}")
            print(f"artifacts={len(status['artifacts'])}")
            print(f"provenance={len(status['provenance'])}")
            print(f"decision_evidence={len(state.get('decision_evidence', []))}")
        return 0

    if args.command == "multi-round":
        task = load_task(args.task)
        result = run_multi_round_research(
            task=task,
            runs_dir=args.runs_dir,
            repo_root=args.repo_root.resolve(),
            memory_dir=args.memory_dir,
            branch_mode=args.branch_mode,
            agent_kind=args.agent,
            max_rounds=args.max_rounds,
            review_seed_count=args.review_seed_count,
        )
        print(f"multi_round_id={result['multi_round_id']}")
        print(f"rounds_completed={result['rounds_completed']}")
        print(f"final_decision={result['final_decision']}")
        print(f"stop_reason={result['stop_reason']}")
        return 0

    if args.command == "resume":
        result = resume_agentic_research(
            runs_dir=args.runs_dir,
            research_id=args.research_id,
            repo_root=args.repo_root.resolve(),
            memory_dir=args.memory_dir,
        )
        decision = result.get("decision", {})
        print(f"research_id={result['research_id']}")
        print(f"recommendation={decision.get('decision', result.get('effect', {}).get('recommendation'))}")
        print(f"reason={'; '.join(decision.get('reasons', []))}")
        return 0

    return 1
