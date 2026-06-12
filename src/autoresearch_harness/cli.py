from __future__ import annotations

import argparse
from pathlib import Path

from .agentic import run_agentic_research
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

    return 1
