from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.agent import LLMResearchAgent
from autoresearch_harness.agentic import resume_agentic_research, run_agentic_research
from autoresearch_harness.decision import make_decision
from autoresearch_harness.hypothesis import Hypothesis
from autoresearch_harness.llm import LLMMessage
from autoresearch_harness.memory import MemoryManager
from autoresearch_harness.memory_index import build_memory_context
from autoresearch_harness.mutation import apply_mutation_plan, build_mutation_plan
from autoresearch_harness.policy import generate_trials
from autoresearch_harness.provenance import evidence_for
from autoresearch_harness.registry import load_research_status
from autoresearch_harness.registry import ResearchRegistry
from autoresearch_harness.runner import run_task
from autoresearch_harness.spec import load_task
from autoresearch_harness.spec import task_to_dict


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
            self.assertTrue((research_dir / "mutation_plan.json").exists())
            self.assertTrue((research_dir / "effect.json").exists())
            self.assertTrue((research_dir / "decision.json").exists())
            self.assertTrue((research_dir / "state.json").exists())
            self.assertTrue((research_dir / "events.jsonl").exists())
            self.assertTrue((research_dir / "artifacts.jsonl").exists())
            self.assertTrue((root / "memory" / "lessons.jsonl").exists())
            self.assertEqual("accept", result["decision"]["decision"])
            self.assertEqual("record", result["branch"]["mode"])

            status = load_research_status(root / "runs", result["research_id"])
            self.assertEqual("completed", status["state"]["status"])
            self.assertEqual(result["candidate_run_id"], status["state"]["candidate_run_id"])
            self.assertGreaterEqual(len(status["events"]), 5)
            self.assertGreaterEqual(len(status["artifacts"]), 5)
            self.assertGreaterEqual(len(status["provenance"]), 5)
            self.assertTrue(status["state"]["decision_evidence"])
            evidence_ids = {
                record["artifact_id"] for record in evidence_for(status["provenance"], "decision")
            }
            self.assertIn("effect", evidence_ids)
            self.assertIn("mutation_plan", evidence_ids)
            self.assertIn("baseline_analysis", evidence_ids)
            self.assertIn("candidate_analysis", evidence_ids)

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
            research_dir = Path(result["paths"]["research_dir"])
            status = load_research_status(root / "runs", result["research_id"])
            provenance_ids = {record["artifact_id"] for record in status["provenance"]}

            self.assertTrue((research_dir / "memory_context.json").exists())
            self.assertTrue((research_dir / "mutation_plan.json").exists())
            self.assertIn("memory_context", provenance_ids)
            self.assertIn("mutation_plan", provenance_ids)
            self.assertTrue(status["state"]["memory_context"]["matches"])
            self.assertIn("stable cost-aware", hypothesis["title"])
            self.assertEqual([0.0, 0.2, 0.4], hypothesis["search_space"]["temperature"]["values"])
            self.assertEqual(
                [0.0, 0.2, 0.4],
                result["mutation_plan"]["candidate_search_space"]["temperature"]["values"],
            )
            self.assertEqual("accept", result["decision"]["decision"])

    def test_mutation_plan_validates_search_space_subset(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        hypothesis = Hypothesis(
            id="hyp_subset",
            title="Try a bounded subset",
            rationale="Validate mutation protocol subset enforcement.",
            expected_effects={"quality_score": "observe"},
            risks=[],
            search_space={
                "temperature": {"type": "categorical", "values": [0.2, 9.9]},
                "max_tokens": {"type": "categorical", "values": [512]},
                "unknown_param": {"type": "categorical", "values": ["x"]},
            },
            validation_plan="Build mutation plan only.",
            source_run_id="source_run",
        )

        plan = build_mutation_plan(task, hypothesis)
        candidate_task = apply_mutation_plan(task, plan)

        self.assertEqual("mutation.v1", plan.protocol_version)
        self.assertEqual([0.2], plan.candidate_search_space["temperature"]["values"])
        self.assertEqual([512], plan.candidate_search_space["max_tokens"]["values"])
        self.assertNotIn("unknown_param", plan.candidate_search_space)
        self.assertEqual(plan.candidate_budget, candidate_task.budget.max_trials)
        self.assertTrue(plan.operations)

    def test_memory_index_ranks_relevant_lessons(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        memories = [
            {
                "research_id": "prompt_run",
                "hypothesis_id": "prompt_hyp",
                "lesson": "Prompt tuning accepted a stricter evidence policy.",
                "recommendation": "accept",
            },
            {
                "research_id": "model_run",
                "hypothesis_id": "model_hyp",
                "lesson": "model_param_tuning failed because stability_score dropped at high temperature.",
                "recommendation": "retry",
                "supporting_decision": {"blocking_guardrails": ["stability_score"]},
            },
        ]

        context = build_memory_context(
            task,
            {"failure_reasons": {"stability_score": 4}},
            memories,
        )

        self.assertEqual("model_run:model_hyp", context["matches"][0]["memory_id"])
        self.assertIn("failure:stability_score", context["matches"][0]["reasons"])
        self.assertGreater(
            context["matches"][0]["score"],
            context["matches"][1]["score"],
        )

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

    def test_resume_continues_after_baseline(self) -> None:
        task = load_task(ROOT / "examples" / "prompt_tuning" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            research_id = "agentic_resume_test"
            research_dir = root / "runs" / research_id
            registry = ResearchRegistry(research_dir)
            registry.state(
                research_id=research_id,
                status="running",
                phase="baseline",
                task=task_to_dict(task),
                agent_kind="rule",
                branch_mode="record",
                memory_dir=str(root / "memory"),
            )
            baseline_summary = run_task(task, research_dir / "baseline")
            registry.state(phase="hypothesis", baseline_run_id=baseline_summary.run_id)

            result = resume_agentic_research(
                runs_dir=root / "runs",
                research_id=research_id,
                repo_root=ROOT,
                memory_dir=root / "memory",
            )
            status = load_research_status(root / "runs", research_id)

            self.assertEqual("completed", status["state"]["status"])
            self.assertEqual(baseline_summary.run_id, result["baseline_run_id"])
            self.assertTrue((research_dir / "agentic_result.json").exists())
            provenance_ids = {record["artifact_id"] for record in status["provenance"]}
            self.assertIn("baseline_analysis", provenance_ids)
            self.assertIn("decision", provenance_ids)

    def test_memory_records_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(Path(tmp))
            lesson = {
                "research_id": "research_1",
                "hypothesis_id": "hyp_1",
                "lesson": "same lesson",
            }
            memory.record_lesson(lesson)
            memory.record_lesson(lesson)

            self.assertEqual(1, len(memory.read_stream("lessons")))

    def test_decision_engine_flags_guardrail_tradeoff_for_review(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        decision = make_decision(
            task,
            baseline_analysis={"pass_rate": 0.8, "failure_reasons": {"latency_ms": 2}},
            candidate_analysis={"pass_rate": 0.6, "failure_reasons": {"latency_ms": 3}},
            effect={"primary_delta": 0.05, "pass_rate_delta": -0.2},
        )

        self.assertEqual("needs_review", decision.decision)
        self.assertIn("human_review", decision.next_action)

    def test_decision_engine_rejects_primary_regression(self) -> None:
        task = load_task(ROOT / "examples" / "model_param_tuning" / "task.json")
        decision = make_decision(
            task,
            baseline_analysis={"pass_rate": 0.8, "failure_reasons": {}},
            candidate_analysis={"pass_rate": 0.8, "failure_reasons": {}},
            effect={"primary_delta": -0.01, "pass_rate_delta": 0.0},
        )

        self.assertEqual("reject", decision.decision)


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response

    def complete(self, messages: list[LLMMessage]) -> str:
        self.messages = messages
        return self.response


if __name__ == "__main__":
    unittest.main()
