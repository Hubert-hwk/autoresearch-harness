from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .adapters import EXECUTORS
from .analysis import build_run_analysis
from .evaluation import better
from .models import RunSummary, TrialResult
from .policy import generate_trials
from .spec import task_to_dict


def run_task(task, runs_dir: Path) -> RunSummary:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    (run_dir / "task.json").write_text(
        json.dumps(task_to_dict(task), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    executor_cls = EXECUTORS.get(task.executor)
    if executor_cls is None:
        raise ValueError(f"Unknown executor: {task.executor}")
    executor = executor_cls(task)
    if hasattr(executor, "set_run_dir"):
        executor.set_run_dir(run_dir)

    best: TrialResult | None = None
    results: list[TrialResult] = []
    total = 0
    started = time.monotonic()
    wall_time_exhausted = False
    with (run_dir / "trials.jsonl").open("w", encoding="utf-8") as trials_file:
        for trial in generate_trials(task):
            if (
                task.budget.max_wall_time_seconds is not None
                and time.monotonic() - started >= task.budget.max_wall_time_seconds
            ):
                wall_time_exhausted = True
                break
            result = executor.run(trial)
            results.append(result)
            total += 1
            trials_file.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
            if better(task.primary_metric, result, best):
                best = result

    analysis = build_run_analysis(results, task.primary_metric)
    (run_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if wall_time_exhausted:
        stop_reason = "wall_time_budget_exhausted"
    else:
        stop_reason = "budget_exhausted" if total >= task.budget.max_trials else "search_space_exhausted"
    summary = RunSummary(
        run_id=run_id,
        task_name=task.name,
        total_trials=total,
        best_result=best,
        stop_reason=stop_reason,
    )
    _write_decision_log(run_dir, summary)
    _write_report(run_dir, summary, task.primary_metric.name, analysis)
    return summary


def _write_decision_log(run_dir: Path, summary: RunSummary) -> None:
    decision = {
        "event": "run_completed",
        "run_id": summary.run_id,
        "total_trials": summary.total_trials,
        "stop_reason": summary.stop_reason,
        "best_trial_id": summary.best_result.trial_id if summary.best_result else None,
    }
    (run_dir / "decisions.jsonl").write_text(
        json.dumps(decision, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_report(
    run_dir: Path,
    summary: RunSummary,
    primary_metric: str,
    analysis: dict,
) -> None:
    lines = [
        f"# AutoResearch Harness Run: {summary.run_id}",
        "",
        f"- Task: `{summary.task_name}`",
        f"- Trials: `{summary.total_trials}`",
        f"- Stop reason: `{summary.stop_reason}`",
        f"- Pass rate: `{analysis['pass_rate']:.2%}`",
    ]
    if summary.best_result:
        lines.extend(
            [
                f"- Best trial: `{summary.best_result.trial_id}`",
                f"- Best {primary_metric}: `{summary.best_result.metrics[primary_metric]:.6f}`",
                "",
                "## Best Parameters",
                "",
                "```json",
                json.dumps(summary.best_result.params, ensure_ascii=False, indent=2),
                "```",
                "",
                "## Metrics",
                "",
                "```json",
                json.dumps(summary.best_result.metrics, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    else:
        lines.append("- Best trial: none passed guardrails")
    lines.extend(
        [
            "",
            "## Failure Reasons",
            "",
            "```json",
            json.dumps(analysis["failure_reasons"], ensure_ascii=False, indent=2),
            "```",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
