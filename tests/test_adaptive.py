from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.adaptive import (
    pareto_front,
    run_adaptive_task,
    sample_candidates,
)
from autoresearch_harness.adapters import EXECUTORS
from autoresearch_harness.models import (
    AdaptiveScheduling,
    Budget,
    CommandExecution,
    MetricGoal,
    TaskSpec,
    TrialResult,
)
from autoresearch_harness.spec import load_task


class AdaptiveSchedulingTest(unittest.TestCase):
    def test_seeded_candidate_sample_is_deterministic_and_unique(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        first = sample_candidates(task)
        second = sample_candidates(task)

        self.assertEqual(first, second)
        self.assertEqual(4, len(first))
        self.assertEqual(4, len({json.dumps(item.params, sort_keys=True) for item in first}))
        self.assertNotEqual(
            [0.4, 0.4, 0.4, 0.4],
            [candidate.params["threshold"] for candidate in first],
        )

    def test_pareto_front_respects_directions_and_guardrails(self) -> None:
        objectives = [
            MetricGoal("quality", "maximize"),
            MetricGoal("latency", "minimize"),
        ]
        results = [
            ("balanced", self._result("balanced", 0.9, 10.0)),
            ("fast", self._result("fast", 0.8, 5.0)),
            ("dominated", self._result("dominated", 0.7, 12.0)),
            ("invalid", self._result("invalid", 1.0, 1.0, passed=False)),
        ]

        self.assertEqual(["balanced", "fast"], pareto_front(results, objectives))

    def test_adaptive_run_promotes_candidates_and_builds_lineage(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_adaptive_task(task, Path(tmp), repo_root=ROOT)
            run_dir = Path(result["paths"]["run_dir"])
            graph = json.loads(
                (run_dir / "experiment_graph.json").read_text(encoding="utf-8")
            )

        self.assertEqual("completed_all_fidelities", result["stop_reason"])
        self.assertEqual(6, result["budget_usage"]["trials"])
        self.assertEqual(44.0, result["budget_usage"]["fidelity_units"])
        self.assertEqual(2, len(result["stages"]))
        self.assertEqual(2, len(result["stages"][0]["promoted_candidate_ids"]))
        self.assertTrue(result["pareto_archive"]["final_candidate_ids"])
        self.assertEqual(6, len(graph["nodes"]))
        stage_two = [node for node in graph["nodes"] if node["fidelity"]["stage"] == 2]
        self.assertTrue(all(len(node["parent_ids"]) == 1 for node in stage_two))

    def test_fidelity_budget_stops_before_unaffordable_stage(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        task = replace(task, budget=replace(task.budget, max_fidelity_units=24.0))
        with tempfile.TemporaryDirectory() as tmp:
            result = run_adaptive_task(task, Path(tmp), repo_root=ROOT)

        self.assertEqual("fidelity_budget_exhausted", result["stop_reason"])
        self.assertEqual(4, result["budget_usage"]["trials"])
        self.assertEqual(24.0, result["budget_usage"]["fidelity_units"])
        self.assertEqual(1, len(result["stages"]))

    def test_trial_budget_limits_initial_sample_and_blocks_next_stage(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        task = replace(
            task,
            budget=replace(task.budget, max_trials=3, max_fidelity_units=100.0),
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_adaptive_task(task, Path(tmp), repo_root=ROOT)

        self.assertEqual("trial_budget_exhausted", result["stop_reason"])
        self.assertEqual(3, result["budget_usage"]["trials"])
        self.assertEqual(1, len(result["stages"]))

    def test_executor_exception_becomes_failed_trial_evidence(self) -> None:
        class RaisingExecutor:
            def __init__(self, task: TaskSpec):
                self.task = task

            def run(self, trial: object) -> TrialResult:
                raise RuntimeError("synthetic failure")

        task = TaskSpec(
            name="raising_executor",
            objective="Preserve scheduler failures.",
            executor="raising_test",
            search_space={"value": {"type": "categorical", "values": [1, 2]}},
            budget=Budget(max_trials=2),
            primary_metric=MetricGoal("score", "maximize"),
            schema_version="task.v2",
            scheduling=AdaptiveScheduling(
                fidelity_parameter="epochs",
                fidelity_levels=[1.0, 2.0],
                objectives=[MetricGoal("score", "maximize")],
                initial_candidates=2,
            ),
        )
        EXECUTORS["raising_test"] = RaisingExecutor
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_adaptive_task(task, Path(tmp))
                records = [
                    json.loads(line)
                    for line in Path(result["paths"]["trials"])
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
        finally:
            EXECUTORS.pop("raising_test", None)

        self.assertEqual("no_guardrail_passing_candidates", result["stop_reason"])
        self.assertEqual(2, len(records))
        self.assertTrue(
            all("executor_exception=RuntimeError" in item["result"]["notes"][0] for item in records)
        )

    def test_external_timeout_is_clipped_to_remaining_global_wall_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = TaskSpec(
                name="adaptive_timeout",
                objective="Verify the hard external wall-time boundary.",
                executor="external_command",
                search_space={"value": {"type": "categorical", "values": [1, 2]}},
                budget=Budget(
                    max_trials=4,
                    max_wall_time_seconds=0.05,
                    max_fidelity_units=10,
                ),
                primary_metric=MetricGoal("score", "maximize"),
                schema_version="task.v2",
                execution=CommandExecution(
                    command=["{python}", "-c", "import time; time.sleep(1)"],
                    working_directory=str(root),
                    timeout_seconds=5,
                ),
                scheduling=AdaptiveScheduling(
                    fidelity_parameter="epochs",
                    fidelity_levels=[1.0, 2.0],
                    objectives=[MetricGoal("score", "maximize")],
                    initial_candidates=2,
                    reduction_factor=2,
                    random_seed=0,
                ),
            )
            result = run_adaptive_task(task, root / "runs")
            run_dir = Path(result["paths"]["run_dir"])
            execution = json.loads(
                (
                    run_dir
                    / "executor_artifacts"
                    / "stage_01_candidate_0001"
                    / "execution.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual("wall_time_budget_exhausted", result["stop_reason"])
        self.assertEqual(1, result["budget_usage"]["trials"])
        self.assertLessEqual(execution["timeout_seconds"], 0.05)
        self.assertEqual("timed_out", execution["status"])

    @staticmethod
    def _result(
        trial_id: str,
        quality: float,
        latency: float,
        *,
        passed: bool = True,
    ) -> TrialResult:
        return TrialResult(
            trial_id=trial_id,
            params={},
            metrics={"quality": quality, "latency": latency},
            passed_guardrails=passed,
        )


if __name__ == "__main__":
    unittest.main()
