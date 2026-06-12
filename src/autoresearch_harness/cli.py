from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_task
from .spec import load_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an autoresearch task")
    run_parser.add_argument("task", type=Path)
    run_parser.add_argument("--runs-dir", type=Path, default=Path("runs"))

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

    return 1

