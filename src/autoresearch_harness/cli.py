from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agentic import resume_agentic_research, run_agentic_research
from .registry import load_research_status
from .runner import run_task
from .spec import load_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an autoresearch task")
    run_parser.add_argument("task", type=Path)
    run_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))

    research_parser = subparsers.add_parser("research", help="run an agentic research loop")
    research_parser.add_argument("task", type=Path)
    research_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    research_parser.add_argument("--memory-dir", type=Path, default=Path("memory"))
    research_parser.add_argument("--repo-root", type=Path, default=Path("."))
    research_parser.add_argument("--branch-mode", choices=["record", "create"], default="record")
    research_parser.add_argument("--agent", choices=["rule", "llm"], default="rule")

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
        effect = result["effect"]
        print(f"research_id={result['research_id']}")
        print(f"hypothesis={result['hypothesis']['title']}")
        print(f"branch={result['branch']['experiment_branch']}")
        print(f"recommendation={effect['recommendation']}")
        print(f"reason={effect['reason']}")
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
            print(f"recommendation={state.get('recommendation')}")
            print(f"events={len(status['events'])}")
            print(f"artifacts={len(status['artifacts'])}")
        return 0

    if args.command == "resume":
        result = resume_agentic_research(
            runs_dir=args.runs_dir,
            research_id=args.research_id,
            repo_root=args.repo_root.resolve(),
            memory_dir=args.memory_dir,
        )
        effect = result["effect"]
        print(f"research_id={result['research_id']}")
        print(f"recommendation={effect['recommendation']}")
        print(f"reason={effect['reason']}")
        return 0

    return 1
