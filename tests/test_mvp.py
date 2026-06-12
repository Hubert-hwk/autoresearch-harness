from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.agent import LLMResearchAgent
from autoresearch_harness.agentic import run_agentic_research
from autoresearch_harness.llm import LLMMessage
from autoresearch_harness.memory import MemoryManager
from autoresearch_harness.policy import generate_trials
from autoresearch_harness.registry import load_research_status
from autoresearch_harness.runner import run_task
from autoresearch_harness.spec import load_task


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
            self.assertTrue((research_dir / "state.json").exists())
            self.assertTrue((research_dir / "events.jsonl").exists())
            self.assertTrue((research_dir / "artifacts.jsonl").exists())
            self.assertTrue((root / "memory" / "lessons.jsonl").exists())
            self.assertEqual("accept", result["effect"]["recommendation"])
            self.assertEqual("record", result["branch"]["mode"])

            status = load_research_status(root / "runs", result["research_id"])
            self.assertEqual("completed", status["state"]["status"])
            self.assertEqual(result["candidate_run_id"], status["state"]["candidate_run_id"])
            self.assertGreaterEqual(len(status["events"]), 5)
            self.assertGreaterEqual(len(status["artifacts"]), 5)

    def test_model_param_tuning_agentic_loop_uses_memory(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = MemoryManager(root / "memory")
            memory.record_lesson(
                {
                    "lesson": "Prior model tuning failed because stability_score dropped.",
                    "recommendation": "retry",
                }
            )
            result = run_agentic_research(
                task=task,
                runs_dir=root / "runs",
                repo_root=ROOT,
                memory_dir=root / "memory",
                branch_mode="record",
            )

            hypothesis = result["hypothesis"]
            self.assertIn("stable cost-aware", hypothesis["title"])
            self.assertEqual([0.0, 0.2, 0.4], hypothesis["search_space"]["temperature"]["values"])
            self.assertEqual("accept", result["effect"]["recommendation"])

    def test_llm_agent_validates_search_space(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        agent = LLMResearchAgent(
            FakeLLMClient(
                """
                {
                  "title": "LLM narrows stable decoding",
                  "rationale": "Keep low temperature and moderate token budget.",
                  "expected_effects": {"quality_score": "improve"},
                  "risks": ["May miss long-answer cases"],
                  "search_space": {
                    "temperature": {"type": "categorical", "values": [0.2, 9.9]},
                    "max_tokens": {"type": "categorical", "values": [1024, 9999]},
                    "unknown_param": {"type": "categorical", "values": ["x"]}
                  },
                  "validation_plan": "Run model_param_tuning candidate trials."
                }
                """
            )
        )

        hypothesis = agent.propose(task, {"failure_reasons": {}}, "source_run")

        self.assertEqual([0.2], hypothesis.search_space["temperature"]["values"])
        self.assertEqual([1024], hypothesis.search_space["max_tokens"]["values"])
        self.assertNotIn("unknown_param", hypothesis.search_space)


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response

    def complete(self, messages: list[LLMMessage]) -> str:
        self.messages = messages
        return self.response


if __name__ == "__main__":
    unittest.main()
