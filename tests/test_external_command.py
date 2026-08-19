from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.runner import run_task
from autoresearch_harness.spec import load_task, task_to_dict


class ExternalCommandExecutorTest(unittest.TestCase):
    def test_command_backed_task_writes_replayable_evidence(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")

        self.assertEqual("task.v2", task.schema_version)
        self.assertEqual("external_command", task.executor)
        self.assertIsNotNone(task.execution)
        self.assertEqual(30.0, task.budget.max_wall_time_seconds)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = run_task(task, root)
            run_dir = root / summary.run_id
            manifest = [
                json.loads(line)
                for line in (run_dir / "executor_artifacts.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            first_execution = json.loads(
                (run_dir / "executor_artifacts" / "trial_0001" / "execution.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(8, summary.total_trials)
            self.assertIsNotNone(summary.best_result)
            self.assertIn("accuracy", summary.best_result.metrics)
            self.assertTrue(
                (run_dir / "executor_artifacts" / "trial_0001" / "details.json").is_file()
            )
            self.assertEqual("completed", first_execution["status"])
            self.assertTrue(any(record["kind"] == "execution_manifest" for record in manifest))
            self.assertTrue(all(record["metadata"]["sha256"] for record in manifest))

        serialized = task_to_dict(task)
        self.assertEqual("task.v2", serialized["schema_version"])
        self.assertEqual(30.0, serialized["budget"]["max_wall_time_seconds"])
        self.assertEqual(44.0, serialized["budget"]["max_fidelity_units"])
        self.assertEqual(["{python}", "evaluate.py"], serialized["execution"]["command"])
        self.assertEqual(
            ["examples/external_command/evaluate.py"],
            serialized["mutation"]["editable_paths"],
        )
        self.assertEqual("scheduling.v1", serialized["scheduling"]["protocol_version"])
        self.assertEqual("verification.v1", serialized["verification"]["protocol_version"])

    def test_task_rejects_output_path_escape(self) -> None:
        source = json.loads(
            (ROOT / "examples" / "external_command" / "task.json").read_text(
                encoding="utf-8"
            )
        )
        source["execution"]["metrics_path"] = "../metrics.json"
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "task.json"
            source["execution"]["working_directory"] = str(
                ROOT / "examples" / "external_command"
            )
            task_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "must stay inside"):
                load_task(task_path)

    def test_task_rejects_non_finite_global_budget(self) -> None:
        source = json.loads(
            (ROOT / "examples" / "external_command" / "task.json").read_text(
                encoding="utf-8"
            )
        )
        source["budget"]["max_fidelity_units"] = float("nan")
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "task.json"
            source["execution"]["working_directory"] = str(
                ROOT / "examples" / "external_command"
            )
            task_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "finite number"):
                load_task(task_path)

    def test_task_round_trip_preserves_guardrail_thresholds(self) -> None:
        original = load_task(ROOT / "examples" / "external_command" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            task_path = Path(tmp) / "round_trip.json"
            task_path.write_text(json.dumps(task_to_dict(original)), encoding="utf-8")
            reloaded = load_task(task_path)

        self.assertEqual(original.guardrail_metrics, reloaded.guardrail_metrics)
        self.assertEqual(original.mutation_policy, reloaded.mutation_policy)
        self.assertEqual(original.scheduling, reloaded.scheduling)
        self.assertEqual(original.verification, reloaded.verification)
        self.assertEqual(0.25, reloaded.guardrail_metrics[0].max_value)

    def test_timeout_is_recorded_as_trial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "schema_version": "task.v2",
                        "name": "timeout_fixture",
                        "objective": "Exercise timeout recording.",
                        "executor": "external_command",
                        "budget": {"max_trials": 1},
                        "search_space": {
                            "value": {"type": "categorical", "values": [1]}
                        },
                        "metrics": {
                            "primary": {"name": "score", "direction": "maximize"},
                            "guardrails": [],
                        },
                        "execution": {
                            "command": ["{python}", "-c", "import time; time.sleep(0.2)"],
                            "working_directory": ".",
                            "timeout_seconds": 0.01,
                        },
                    }
                ),
                encoding="utf-8",
            )
            task = load_task(task_path)
            summary = run_task(task, root / "runs")
            run_dir = root / "runs" / summary.run_id
            trial = json.loads(
                (run_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            execution = json.loads(
                (run_dir / "executor_artifacts" / "trial_0001" / "execution.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertIsNone(summary.best_result)
            self.assertFalse(trial["passed_guardrails"])
            self.assertTrue(any("executor_timeout" in note for note in trial["notes"]))
            self.assertEqual("timed_out", execution["status"])


if __name__ == "__main__":
    unittest.main()
