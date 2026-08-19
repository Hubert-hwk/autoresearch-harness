from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import EXECUTORS
from .fingerprints import build_execution_fingerprint, fingerprint_differences
from .models import MetricGoal, TaskSpec, Trial, TrialResult
from .policy import search_space_values
from .spec import load_task, task_to_dict


def load_parameter_set(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"parameter set must be a non-empty JSON object: {path}")
    return payload


def paired_bootstrap_interval(
    improvements: list[float],
    *,
    confidence_level: float,
    samples: int,
    seed: int,
) -> dict[str, float]:
    if len(improvements) < 2:
        raise ValueError("paired bootstrap requires at least two observations")
    generator = random.Random(seed)
    size = len(improvements)
    means = sorted(
        statistics.fmean(generator.choice(improvements) for _ in range(size))
        for _ in range(samples)
    )
    tail = (1.0 - confidence_level) / 2.0
    lower_index = min(samples - 1, max(0, math.floor(tail * samples)))
    upper_index = min(samples - 1, max(0, math.ceil((1.0 - tail) * samples) - 1))
    return {
        "mean": statistics.fmean(improvements),
        "std": statistics.stdev(improvements) if size > 1 else 0.0,
        "lower": means[lower_index],
        "upper": means[upper_index],
        "confidence_level": confidence_level,
        "bootstrap_samples": samples,
    }


def run_verification(
    task: TaskSpec,
    baseline_params: dict[str, Any],
    candidate_params: dict[str, Any],
    runs_dir: Path,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    policy = task.verification
    if policy is None:
        raise ValueError("verify-run requires a task verification block")
    _validate_verification_contract(task)
    _validate_parameter_set(task, baseline_params, "baseline")
    _validate_parameter_set(task, candidate_params, "candidate")
    if baseline_params == candidate_params:
        raise ValueError("baseline and candidate parameter sets must differ")

    verification_id = datetime.now(timezone.utc).strftime("verify_%Y%m%dT%H%M%S%fZ")
    verification_dir = runs_dir / verification_id
    verification_dir.mkdir(parents=True, exist_ok=False)
    task_path = verification_dir / "task_snapshot.json"
    _write_json(task_path, task_to_dict(task))
    _write_json(verification_dir / "baseline_params.json", baseline_params)
    _write_json(verification_dir / "candidate_params.json", candidate_params)
    fingerprint_before = build_execution_fingerprint(task, repo_root=repo_root)
    _write_json(verification_dir / "fingerprint_before.json", fingerprint_before)

    executor_cls = EXECUTORS.get(task.executor)
    if executor_cls is None:
        raise ValueError(f"Unknown executor: {task.executor}")
    executor = executor_cls(task)
    if hasattr(executor, "set_run_dir"):
        executor.set_run_dir(verification_dir)

    started = time.monotonic()
    records: list[dict[str, Any]] = []
    stop_reason = "verification_complete"
    for pair_index, seed in enumerate(policy.seeds, start=1):
        roles = ["baseline", "candidate"] if pair_index % 2 else ["candidate", "baseline"]
        for role in roles:
            elapsed = time.monotonic() - started
            remaining = (
                None
                if task.budget.max_wall_time_seconds is None
                else max(0.0, task.budget.max_wall_time_seconds - elapsed)
            )
            if len(records) >= task.budget.max_trials:
                stop_reason = "trial_budget_exhausted"
                break
            if remaining is not None and remaining <= 0:
                stop_reason = "wall_time_budget_exhausted"
                break
            base = baseline_params if role == "baseline" else candidate_params
            params = dict(base)
            params[policy.seed_parameter] = seed
            trial = Trial(id=f"pair_{pair_index:03d}_{role}", params=params)
            trial_started = time.monotonic()
            try:
                if task.executor == "external_command":
                    result = executor.run(trial, timeout_seconds=remaining)
                else:
                    result = executor.run(trial)
            except Exception as exc:
                result = TrialResult(
                    trial_id=trial.id,
                    params=trial.params,
                    metrics={},
                    passed_guardrails=False,
                    notes=[f"executor_exception={type(exc).__name__}: {exc}"],
                )
            record = {
                "pair_index": pair_index,
                "seed": seed,
                "role": role,
                "duration_seconds": time.monotonic() - trial_started,
                "result": asdict(result),
            }
            records.append(record)
            _append_jsonl(verification_dir / "verification_trials.jsonl", record)
        if stop_reason != "verification_complete":
            break

    fingerprint_after = build_execution_fingerprint(task, repo_root=repo_root)
    _write_json(verification_dir / "fingerprint_after.json", fingerprint_after)
    drift_components = fingerprint_differences(fingerprint_before, fingerprint_after)
    statistics_bundle = _verification_statistics(task, records)
    decision = _verification_decision(
        task,
        statistics_bundle,
        expected_records=len(policy.seeds) * 2,
        actual_records=len(records),
        drift_components=drift_components,
    )
    if stop_reason != "verification_complete":
        decision["decision"] = "reject"
        decision["reasons"].append(f"Verification stopped early: {stop_reason}.")

    comparison_metrics = policy.replay_metrics or [task.primary_metric.name]
    replay_manifest = {
        "schema_version": "replay.v1",
        "verification_id": verification_id,
        "task_snapshot": "task_snapshot.json",
        "repo_root": str(repo_root.resolve()) if repo_root is not None else None,
        "fingerprint": fingerprint_before,
        "metric_tolerance": policy.metric_tolerance,
        "comparison_metrics": comparison_metrics,
        "trials": [
            {
                "source_trial_id": record["result"]["trial_id"],
                "params": record["result"]["params"],
                "expected_metrics": {
                    name: record["result"]["metrics"][name]
                    for name in comparison_metrics
                    if name in record["result"]["metrics"]
                },
                "expected_passed_guardrails": record["result"]["passed_guardrails"],
            }
            for record in records
        ],
    }
    replay_manifest["manifest_sha256"] = _sha256_json(replay_manifest)
    _write_json(verification_dir / "replay_manifest.json", replay_manifest)
    result = {
        "verification_id": verification_id,
        "status": "completed",
        "stop_reason": stop_reason,
        "decision": decision,
        "statistics": statistics_bundle,
        "fingerprint_id": fingerprint_before["fingerprint_id"],
        "fingerprint_drift_components": drift_components,
        "trial_count": len(records),
        "paths": {
            "verification_dir": str(verification_dir),
            "trials": str(verification_dir / "verification_trials.jsonl"),
            "replay_manifest": str(verification_dir / "replay_manifest.json"),
            "report": str(verification_dir / "report.md"),
        },
    }
    result["verification_result_sha256"] = _sha256_json(result)
    _write_json(verification_dir / "verification_result.json", result)
    _write_report(verification_dir, result)
    return result


def replay_verification(
    manifest_or_dir: Path,
    runs_dir: Path,
    *,
    allow_drift: bool = False,
) -> dict[str, Any]:
    manifest_path = (
        manifest_or_dir / "replay_manifest.json"
        if manifest_or_dir.is_dir()
        else manifest_or_dir
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "replay.v1":
        raise ValueError("replay manifest schema_version must be replay.v1")
    recorded_manifest_hash = manifest.get("manifest_sha256")
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_sha256", None)
    if recorded_manifest_hash != _sha256_json(manifest_body):
        raise ValueError("replay manifest content hash mismatch")
    task_path = manifest_path.parent / manifest["task_snapshot"]
    task = load_task(task_path)
    repo_root_value = manifest.get("repo_root")
    repo_root = Path(repo_root_value) if repo_root_value else None
    current_fingerprint = build_execution_fingerprint(task, repo_root=repo_root)
    drift_components = fingerprint_differences(manifest["fingerprint"], current_fingerprint)

    replay_id = datetime.now(timezone.utc).strftime("replay_%Y%m%dT%H%M%S%fZ")
    replay_dir = runs_dir / replay_id
    replay_dir.mkdir(parents=True, exist_ok=False)
    _write_json(replay_dir / "fingerprint_current.json", current_fingerprint)
    if drift_components and not allow_drift:
        result = {
            "replay_id": replay_id,
            "verification_id": manifest["verification_id"],
            "manifest_sha256": manifest["manifest_sha256"],
            "status": "drift_blocked",
            "matched": False,
            "drift_components": drift_components,
            "post_replay_drift_components": [],
            "trial_count": 0,
            "mismatches": [],
            "replay_dir": str(replay_dir),
        }
        result["replay_result_sha256"] = _sha256_json(result)
        _write_json(replay_dir / "replay_result.json", result)
        return result

    executor_cls = EXECUTORS.get(task.executor)
    if executor_cls is None:
        raise ValueError(f"Unknown executor: {task.executor}")
    executor = executor_cls(task)
    if hasattr(executor, "set_run_dir"):
        executor.set_run_dir(replay_dir)
    tolerance = float(manifest["metric_tolerance"])
    comparison_metrics = manifest["comparison_metrics"]
    mismatches: list[dict[str, Any]] = []
    replayed: list[dict[str, Any]] = []
    started = time.monotonic()
    for expected in manifest["trials"]:
        elapsed = time.monotonic() - started
        remaining = (
            None
            if task.budget.max_wall_time_seconds is None
            else max(0.0, task.budget.max_wall_time_seconds - elapsed)
        )
        if len(replayed) >= task.budget.max_trials:
            mismatches.append({"reason": "replay_trial_budget_exhausted"})
            break
        if remaining is not None and remaining <= 0:
            mismatches.append({"reason": "replay_wall_time_budget_exhausted"})
            break
        trial = Trial(id=expected["source_trial_id"], params=expected["params"])
        try:
            if task.executor == "external_command":
                result = executor.run(trial, timeout_seconds=remaining)
            else:
                result = executor.run(trial)
        except Exception as exc:
            result = TrialResult(
                trial_id=trial.id,
                params=trial.params,
                metrics={},
                passed_guardrails=False,
                notes=[f"executor_exception={type(exc).__name__}: {exc}"],
            )
        trial_mismatches = _metric_mismatches(
            expected,
            result,
            comparison_metrics,
            tolerance,
        )
        mismatches.extend(trial_mismatches)
        record = {
            "source_trial_id": expected["source_trial_id"],
            "result": asdict(result),
            "mismatches": trial_mismatches,
        }
        replayed.append(record)
        _append_jsonl(replay_dir / "replay_trials.jsonl", record)
    fingerprint_after = build_execution_fingerprint(task, repo_root=repo_root)
    post_replay_drift = fingerprint_differences(current_fingerprint, fingerprint_after)
    if post_replay_drift:
        mismatches.append(
            {
                "reason": "fingerprint_changed_during_replay",
                "components": post_replay_drift,
            }
        )
    _write_json(replay_dir / "fingerprint_after.json", fingerprint_after)
    result = {
        "replay_id": replay_id,
        "verification_id": manifest["verification_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "status": "matched" if not mismatches else "mismatched",
        "matched": not mismatches,
        "drift_allowed": bool(drift_components and allow_drift),
        "drift_components": drift_components,
        "post_replay_drift_components": post_replay_drift,
        "trial_count": len(replayed),
        "mismatches": mismatches,
        "replay_dir": str(replay_dir),
    }
    result["replay_result_sha256"] = _sha256_json(result)
    _write_json(replay_dir / "replay_result.json", result)
    return result


def _verification_statistics(task: TaskSpec, records: list[dict[str, Any]]) -> dict[str, Any]:
    policy = task.verification
    assert policy is not None
    by_pair: dict[int, dict[str, TrialResult]] = {}
    for record in records:
        by_pair.setdefault(record["pair_index"], {})[record["role"]] = TrialResult(
            **record["result"]
        )
    improvements: list[float] = []
    complete_pairs = 0
    for roles in by_pair.values():
        if "baseline" not in roles or "candidate" not in roles:
            continue
        baseline = roles["baseline"]
        candidate = roles["candidate"]
        metric = task.primary_metric.name
        if metric not in baseline.metrics or metric not in candidate.metrics:
            continue
        difference = candidate.metrics[metric] - baseline.metrics[metric]
        if task.primary_metric.direction == "minimize":
            difference = -difference
        improvements.append(difference)
        complete_pairs += 1
    candidate_results = [
        TrialResult(**record["result"])
        for record in records
        if record["role"] == "candidate"
    ]
    baseline_results = [
        TrialResult(**record["result"])
        for record in records
        if record["role"] == "baseline"
    ]
    interval = (
        paired_bootstrap_interval(
            improvements,
            confidence_level=policy.confidence_level,
            samples=policy.bootstrap_samples,
            seed=policy.bootstrap_seed,
        )
        if len(improvements) >= 2
        else None
    )
    return {
        "primary_metric": task.primary_metric.name,
        "improvement_direction": "positive_is_better",
        "paired_improvements": improvements,
        "paired_interval": interval,
        "complete_pairs": complete_pairs,
        "baseline_metrics": _aggregate_metrics(baseline_results),
        "candidate_metrics": _aggregate_metrics(candidate_results),
        "baseline_guardrail_pass_rate": _pass_rate(baseline_results),
        "candidate_guardrail_pass_rate": _pass_rate(candidate_results),
    }


def _verification_decision(
    task: TaskSpec,
    statistics_bundle: dict[str, Any],
    *,
    expected_records: int,
    actual_records: int,
    drift_components: list[str],
) -> dict[str, Any]:
    policy = task.verification
    assert policy is not None
    reasons: list[str] = []
    blocking_gates: list[str] = []
    interval = statistics_bundle["paired_interval"]
    if actual_records != expected_records or statistics_bundle["complete_pairs"] != len(policy.seeds):
        blocking_gates.append("complete_seed_pairs")
        reasons.append("Not all declared baseline/candidate seed pairs produced primary metrics.")
    if interval is None or interval["lower"] <= policy.min_primary_improvement:
        blocking_gates.append("primary_confidence_interval")
        reasons.append(
            "Paired improvement confidence interval does not clear the minimum improvement gate."
        )
    pass_rate = statistics_bundle["candidate_guardrail_pass_rate"]
    if pass_rate < policy.min_guardrail_pass_rate:
        blocking_gates.append("candidate_guardrail_pass_rate")
        reasons.append(
            f"Candidate guardrail pass rate {pass_rate:.3f} is below "
            f"{policy.min_guardrail_pass_rate:.3f}."
        )
    if drift_components:
        blocking_gates.append("fingerprint_stability")
        reasons.append(f"Execution fingerprint drifted: {', '.join(drift_components)}.")
    promoted = not blocking_gates
    if promoted:
        reasons.append("All independent verification gates passed.")
    return {
        "decision": "promote" if promoted else "reject",
        "confidence_level": policy.confidence_level,
        "blocking_gates": blocking_gates,
        "reasons": reasons,
    }


def _aggregate_metrics(results: list[TrialResult]) -> dict[str, dict[str, float]]:
    names = sorted({name for result in results for name in result.metrics})
    aggregate: dict[str, dict[str, float]] = {}
    for name in names:
        values = [result.metrics[name] for result in results if name in result.metrics]
        aggregate[name] = {
            "count": float(len(values)),
            "mean": statistics.fmean(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
        }
    return aggregate


def _pass_rate(results: list[TrialResult]) -> float:
    return (
        sum(result.passed_guardrails for result in results) / len(results)
        if results
        else 0.0
    )


def _metric_mismatches(
    expected: dict[str, Any],
    actual: TrialResult,
    metric_names: list[str],
    tolerance: float,
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for name in metric_names:
        expected_value = expected["expected_metrics"].get(name)
        actual_value = actual.metrics.get(name)
        if expected_value is None or actual_value is None:
            if expected_value != actual_value:
                mismatches.append(
                    {"trial_id": actual.trial_id, "metric": name, "reason": "missing_metric"}
                )
            continue
        if abs(float(actual_value) - float(expected_value)) > tolerance:
            mismatches.append(
                {
                    "trial_id": actual.trial_id,
                    "metric": name,
                    "expected": expected_value,
                    "actual": actual_value,
                    "tolerance": tolerance,
                }
            )
    if actual.passed_guardrails != expected["expected_passed_guardrails"]:
        mismatches.append(
            {
                "trial_id": actual.trial_id,
                "reason": "guardrail_status_changed",
                "expected": expected["expected_passed_guardrails"],
                "actual": actual.passed_guardrails,
            }
        )
    return mismatches


def _validate_parameter_set(task: TaskSpec, params: dict[str, Any], role: str) -> None:
    policy = task.verification
    assert policy is not None
    if policy.seed_parameter in params:
        raise ValueError(f"{role} params may not set verification seed parameter")
    for name, specification in task.search_space.items():
        if name not in params:
            raise ValueError(f"{role} params are missing search-space parameter: {name}")
        if params[name] not in search_space_values(specification):
            raise ValueError(f"{role} parameter is outside search space: {name}")


def _validate_verification_contract(task: TaskSpec) -> None:
    policy = task.verification
    assert policy is not None
    if (
        len(policy.seeds) < 2
        or len(policy.seeds) != len(set(policy.seeds))
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in policy.seeds)
    ):
        raise ValueError("verification requires at least two unique seeds")
    if len(policy.seeds) * 2 > task.budget.max_trials:
        raise ValueError("verification seed pairs exceed max_trials budget")
    if not math.isfinite(policy.confidence_level) or not 0 < policy.confidence_level < 1:
        raise ValueError("verification confidence level is invalid")
    if policy.bootstrap_samples < 100:
        raise ValueError("verification bootstrap sample count is invalid")
    if (
        not math.isfinite(policy.min_guardrail_pass_rate)
        or not 0 <= policy.min_guardrail_pass_rate <= 1
    ):
        raise ValueError("verification guardrail pass-rate gate is invalid")
    if not math.isfinite(policy.metric_tolerance) or policy.metric_tolerance < 0:
        raise ValueError("verification metric tolerance is invalid")
    if not math.isfinite(policy.min_primary_improvement):
        raise ValueError("verification minimum primary improvement is invalid")
    if not isinstance(policy.bootstrap_seed, int) or isinstance(policy.bootstrap_seed, bool):
        raise ValueError("verification bootstrap seed is invalid")


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_report(verification_dir: Path, result: dict[str, Any]) -> None:
    interval = result["statistics"]["paired_interval"]
    lines = [
        f"# Verification Run: {result['verification_id']}",
        "",
        f"- Decision: `{result['decision']['decision']}`",
        f"- Stop reason: `{result['stop_reason']}`",
        f"- Trials: `{result['trial_count']}`",
        f"- Fingerprint: `{result['fingerprint_id']}`",
        f"- Fingerprint drift: `{', '.join(result['fingerprint_drift_components']) or 'none'}`",
    ]
    if interval is not None:
        lines.extend(
            [
                f"- Mean paired improvement: `{interval['mean']:.6f}`",
                f"- Confidence interval: `[{interval['lower']:.6f}, {interval['upper']:.6f}]`",
                f"- Confidence level: `{interval['confidence_level']:.1%}`",
            ]
        )
    lines.extend(["", "## Gate reasons", ""])
    lines.extend(f"- {reason}" for reason in result["decision"]["reasons"])
    (verification_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
