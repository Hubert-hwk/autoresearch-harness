from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.adapters.recommender_bpr import RecommenderBprExecutor
from autoresearch_harness.models import (
    Budget,
    CommandExecution,
    MetricGoal,
    TaskSpec,
    Trial,
    VerificationPolicy,
)
from autoresearch_harness.spec import load_task
from autoresearch_harness.verification import (
    paired_bootstrap_interval,
    replay_verification,
    run_verification,
)


class VerificationTest(unittest.TestCase):
    def test_recommender_honors_injected_verification_seed(self) -> None:
        task = load_task(ROOT / "examples" / "recommender_bpr" / "task.json")
        task = replace(
            task,
            schema_version="task.v2",
            metadata={"seeds": [999, 1000]},
            verification=VerificationPolicy(
                seed_parameter="seed",
                seeds=[101, 202],
            ),
        )
        params = {
            "factors": 4,
            "learning_rate": 0.03,
            "regularization": 0.001,
            "epochs": 8,
            "negative_samples": 1,
            "seed": 123,
        }
        with tempfile.TemporaryDirectory() as tmp:
            executor = RecommenderBprExecutor(task)
            executor.set_run_dir(Path(tmp))
            result = executor.run(Trial(id="verification_seed", params=params))
            training_log = json.loads(
                (Path(tmp) / "executor_artifacts" / "verification_seed" / "training_log.json")
                .read_text(encoding="utf-8")
            )

        self.assertEqual(1.0, result.metrics["seed_count"])
        self.assertEqual([123], training_log["seeds"])
        self.assertEqual(123, training_log["seed_results"][0]["seed"])

    def test_paired_bootstrap_is_deterministic(self) -> None:
        first = paired_bootstrap_interval(
            [0.1, 0.2, 0.3],
            confidence_level=0.95,
            samples=500,
            seed=7,
        )
        second = paired_bootstrap_interval(
            [0.1, 0.2, 0.3],
            confidence_level=0.95,
            samples=500,
            seed=7,
        )

        self.assertEqual(first, second)
        self.assertAlmostEqual(0.2, first["mean"])
        self.assertLessEqual(first["lower"], first["mean"])
        self.assertGreaterEqual(first["upper"], first["mean"])

    def test_verification_promotes_replays_and_blocks_fingerprint_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, task = self._fixture(root)
            verification = run_verification(
                task,
                {"value": 0},
                {"value": 1},
                root / "runs",
                repo_root=repo,
            )
            verification_dir = Path(verification["paths"]["verification_dir"])
            fingerprint = json.loads(
                (verification_dir / "fingerprint_before.json").read_text(encoding="utf-8")
            )
            replay = replay_verification(verification_dir, root / "replays")

            manifest_path = verification_dir / "replay_manifest.json"
            original_manifest = manifest_path.read_text(encoding="utf-8")
            tampered_manifest = json.loads(original_manifest)
            tampered_manifest["trials"][0]["expected_metrics"]["score"] += 10
            manifest_path.write_text(json.dumps(tampered_manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest content hash mismatch"):
                replay_verification(verification_dir, root / "tampered")
            manifest_path.write_text(original_manifest, encoding="utf-8")

            evaluator = repo / "evaluate.py"
            evaluator.write_text(
                _EVALUATOR.replace('float(params["value"])', 'float(params["value"]) + 0.5'),
                encoding="utf-8",
            )
            blocked = replay_verification(verification_dir, root / "blocked")
            drifted = replay_verification(
                verification_dir,
                root / "drifted",
                allow_drift=True,
            )

        self.assertEqual("promote", verification["decision"]["decision"])
        self.assertEqual([], verification["fingerprint_drift_components"])
        self.assertAlmostEqual(
            1.0,
            verification["statistics"]["paired_interval"]["lower"],
        )
        self.assertTrue(fingerprint["components"]["evaluator_files"])
        self.assertEqual("matched", replay["status"])
        self.assertEqual(6, replay["trial_count"])
        self.assertEqual("drift_blocked", blocked["status"])
        self.assertEqual(0, blocked["trial_count"])
        self.assertIn("evaluator_files", blocked["drift_components"])
        self.assertEqual("mismatched", drifted["status"])
        self.assertTrue(drifted["drift_allowed"])
        self.assertTrue(drifted["mismatches"])

    def test_guardrail_failure_blocks_independent_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, task = self._fixture(root)
            result = run_verification(
                task,
                {"value": 0},
                {"value": 2},
                root / "runs",
                repo_root=repo,
            )

        self.assertEqual("reject", result["decision"]["decision"])
        self.assertIn(
            "candidate_guardrail_pass_rate",
            result["decision"]["blocking_gates"],
        )
        self.assertEqual(0.0, result["statistics"]["candidate_guardrail_pass_rate"])

    def _fixture(self, root: Path) -> tuple[Path, TaskSpec]:
        repo = root / "repo"
        repo.mkdir()
        self._git(repo, "init", "-b", "main")
        self._git(repo, "config", "user.email", "tests@example.com")
        self._git(repo, "config", "user.name", "AutoResearch Tests")
        (repo / "evaluate.py").write_text(_EVALUATOR, encoding="utf-8")
        self._git(repo, "add", "evaluate.py")
        self._git(repo, "commit", "-m", "verification fixture")
        task = TaskSpec(
            name="verification_fixture",
            objective="Verify a deterministic candidate independently.",
            executor="external_command",
            search_space={"value": {"type": "categorical", "values": [0, 1, 2]}},
            budget=Budget(max_trials=6, max_wall_time_seconds=10),
            primary_metric=MetricGoal("score", "maximize"),
            guardrail_metrics=[MetricGoal("risk", max_value=0.0)],
            schema_version="task.v2",
            execution=CommandExecution(
                command=["{python}", "evaluate.py"],
                working_directory=str(repo),
                metrics_path="metrics.json",
                timeout_seconds=2,
            ),
            verification=VerificationPolicy(
                seed_parameter="seed",
                seeds=[3, 5, 7],
                confidence_level=0.95,
                bootstrap_samples=500,
                bootstrap_seed=19,
                min_primary_improvement=0.1,
                min_guardrail_pass_rate=1.0,
                replay_metrics=["score", "risk"],
            ),
        )
        return repo, task

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


_EVALUATOR = """\
import json
import os
from pathlib import Path

params = json.loads(Path(os.environ["AUTORESEARCH_TRIAL_PARAMS"]).read_text())
score = float(params["value"]) + float(params["seed"]) * 0.001
risk = 1.0 if params["value"] == 2 else 0.0
output = Path(os.environ["AUTORESEARCH_OUTPUT_DIR"])
(output / "metrics.json").write_text(json.dumps({"score": score, "risk": risk}))
"""


if __name__ == "__main__":
    unittest.main()
