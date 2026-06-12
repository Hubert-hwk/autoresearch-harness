from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autoresearch_harness.agentic import run_agentic_research
from autoresearch_harness.policy import generate_trials
from autoresearch_harness.runner import run_task
from autoresearch_harness.spec import load_task


ROOT = Path(__file__).resolve().parents[1]


class MvpHarnessTest(unittest.TestCase):
    def test_ranking_task_generates_budgeted_trials(self) -> None:
        task = load_task(ROOT / "examples" / "ranking_param_tuning" / "task.json")
        trials = list(generate_trials(task))

        self.assertEqual(30, len(trials))
        self.assertEqual("trial_0001", trials[0].id)

    def test_prompt_tuning_run_writes_analysis(self) -> None:
        task = load_task(ROOT / "examples" / "prompt_tuning" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_task(task, Path(tmp))
            run_dir = Path(tmp) / summary.run_id
            analysis = json.loads((run_dir / "analysis.json").read_text(encoding="utf-8"))

        self.assertEqual(18, summary.total_trials)
        self.assertIsNotNone(summary.best_result)
        self.assertGreater(analysis["pass_rate"], 0)
        self.assertLess(analysis["pass_rate"], 1)
        self.assertTrue(analysis["failure_reasons"])

    def test_agentic_research_records_hypothesis_effect_and_memory(self) -> None:
        task = load_task(ROOT / "examples" / "prompt_tuning" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_agentic_research(
                task=task,
                runs_dir=root / "runs",
                repo_root=ROOT,
                memory_dir=root / "memory",
                branch_mode="record",
            )
            research_dir = Path(result["paths"]["research_dir"])

            self.assertTrue((research_dir / "hypothesis.json").exists())
            self.assertTrue((research_dir / "effect.json").exists())
            self.assertTrue((root / "memory" / "lessons.jsonl").exists())
            self.assertEqual("accept", result["effect"]["recommendation"])
            self.assertEqual("record", result["branch"]["mode"])


if __name__ == "__main__":
    unittest.main()
