from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.evidence_memory import (
    EvidenceMemoryStore,
    ingest_verification_memory,
    query_evidence_memory,
)
from autoresearch_harness.agentic import run_agentic_research
from autoresearch_harness.models import MetricGoal
from autoresearch_harness.spec import load_task
from autoresearch_harness.verification import (
    load_parameter_set,
    replay_verification,
    run_verification,
)


class EvidenceMemoryTest(unittest.TestCase):
    def test_verified_memory_lifecycle_and_scope_query(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        baseline = load_parameter_set(
            ROOT / "examples" / "external_command" / "baseline_params.json"
        )
        candidate = load_parameter_set(
            ROOT / "examples" / "external_command" / "candidate_params.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verification = run_verification(
                task,
                baseline,
                candidate,
                root / "runs",
                repo_root=ROOT,
            )
            verification_dir = Path(verification["paths"]["verification_dir"])
            replay = replay_verification(verification_dir, root / "replays")
            replay_result_path = Path(replay["replay_dir"]) / "replay_result.json"
            memory = ingest_verification_memory(
                verification_dir,
                replay_result_path,
                root / "memory",
            )
            duplicate = ingest_verification_memory(
                verification_dir,
                replay_result_path,
                root / "memory",
            )
            query = query_evidence_memory(
                task,
                root / "memory",
                repo_root=ROOT,
            )
            agentic = run_agentic_research(
                task=task,
                runs_dir=root / "agentic_runs",
                repo_root=ROOT,
                memory_dir=root / "memory",
                branch_mode="record",
            )
            planner_context = json.loads(
                (
                    Path(agentic["paths"]["research_dir"])
                    / "memory_context.json"
                ).read_text(encoding="utf-8")
            )
            mismatched_task = replace(
                task,
                primary_metric=MetricGoal("different_metric", "maximize"),
            )
            mismatched_query = query_evidence_memory(
                mismatched_task,
                root / "memory",
                repo_root=ROOT,
            )

            archived_verification = Path(memory["evidence"]["verification_result"])
            original_evidence = archived_verification.read_text(encoding="utf-8")
            tampered_evidence = json.loads(original_evidence)
            tampered_evidence["decision"]["decision"] = "reject"
            archived_verification.write_text(
                json.dumps(tampered_evidence),
                encoding="utf-8",
            )
            integrity_query = query_evidence_memory(
                task,
                root / "memory",
                repo_root=ROOT,
            )
            archived_verification.write_text(original_evidence, encoding="utf-8")

            store = EvidenceMemoryStore(root / "memory")
            collision = deepcopy(memory)
            collision["claim"]["statement"] = "Different content under the same id."
            with self.assertRaisesRegex(ValueError, "different content"):
                store.record(collision)
            invalid_time = deepcopy(memory)
            invalid_time["memory_id"] = "mem_invalid_time"
            invalid_time["validity"]["valid_until"] = "2026-08-20T00:00:00"
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                store.record(invalid_time)
            revised = deepcopy(memory)
            revised["memory_id"] = "mem_revised_evidence"
            revised["claim_type"] = "inconclusive_effect"
            revised["claim"]["statement"] = "Superseding verified interpretation."
            with self.assertRaisesRegex(ValueError, "requires explicit supersession"):
                store.record(revised)
            store.record(revised, supersedes=[memory["memory_id"]])
            superseded = store.get(memory["memory_id"])
            active = store.get("mem_revised_evidence")
            invalidated = store.invalidate("mem_revised_evidence", "Evaluator retired")
            snapshot = store.snapshot()

            events_path = root / "memory" / "evidence_memory_events.jsonl"
            lines = events_path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[0])
            tampered["payload"]["memory"]["claim"]["statement"] = "tampered"
            lines[0] = json.dumps(tampered)
            events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                EvidenceMemoryStore(root / "memory")

        self.assertEqual("beneficial_effect", memory["claim_type"])
        self.assertEqual(memory["memory_id"], duplicate["memory_id"])
        self.assertEqual(1, len(query["matched"]))
        self.assertEqual(memory["memory_id"], query["matched"][0]["memory_id"])
        self.assertEqual(1, planner_context["evidence_memory"]["matched_memories"])
        self.assertIn(memory["memory_id"], planner_context["evidence_memory"]["memory_ids"])
        self.assertEqual([], mismatched_query["matched"])
        self.assertEqual([], integrity_query["matched"])
        self.assertEqual(
            "evidence_integrity_failed",
            integrity_query["excluded"][0]["reason"],
        )
        self.assertEqual("superseded", superseded["validity"]["status"])
        self.assertEqual("mem_revised_evidence", superseded["validity"]["superseded_by"])
        self.assertEqual("active", active["validity"]["status"])
        self.assertEqual("invalidated", invalidated["validity"]["status"])
        self.assertEqual(3, snapshot["event_count"])

    def test_ingest_rejects_unmatched_replay(self) -> None:
        task = load_task(ROOT / "examples" / "external_command" / "task.json")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verification = run_verification(
                task,
                load_parameter_set(
                    ROOT / "examples" / "external_command" / "baseline_params.json"
                ),
                load_parameter_set(
                    ROOT / "examples" / "external_command" / "candidate_params.json"
                ),
                root / "runs",
                repo_root=ROOT,
            )
            verification_dir = Path(verification["paths"]["verification_dir"])
            replay = replay_verification(verification_dir, root / "replays")
            replay_path = Path(replay["replay_dir"]) / "replay_result.json"
            payload = json.loads(replay_path.read_text(encoding="utf-8"))
            payload.pop("replay_result_sha256")
            payload["status"] = "mismatched"
            payload["matched"] = False
            payload["replay_result_sha256"] = _sha256_json(payload)
            fake_path = root / "unmatched_replay.json"
            fake_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "requires a matched replay"):
                ingest_verification_memory(
                    verification_dir,
                    fake_path,
                    root / "memory",
                )


def _sha256_json(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


if __name__ == "__main__":
    unittest.main()
