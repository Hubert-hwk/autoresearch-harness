from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.experiment_graph import (
    ExperimentGraphStore,
    rebuild_experiment_graph,
)


class ExperimentGraphTest(unittest.TestCase):
    def test_graph_rebuild_preserves_lineage_evidence_cost_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_dir = Path(tmp)
            store = ExperimentGraphStore(graph_dir, "search-graph")
            store.create_node(
                "root",
                base_commit="abc123",
                hypothesis={"claim": "increase quality"},
                mutation={"kind": "baseline"},
                fidelity={"seeds": 1},
            )
            store.transition("root", "running")
            store.attach_evaluation(
                "root",
                {"score": 0.8},
                feedback=[{"kind": "review", "text": "promising"}],
            )
            store.record_budget("root", {"trials": 3, "wall_time_seconds": 1.25})
            store.attach_artifacts("root", ["candidate/run-1", "mutation.diff"])
            store.transition("root", "evaluated")
            store.attach_decision("root", {"decision": "accept"})
            store.transition("root", "accepted")
            store.create_node(
                "child",
                parent_ids=["root"],
                base_commit="abc123",
                hypothesis={"claim": "follow-up"},
                mutation={"kind": "replace_text"},
                fidelity={"seeds": 3},
            )

            snapshot = store.snapshot()
            root = snapshot["nodes"][0]
            child = snapshot["nodes"][1]

            self.assertEqual("accepted", root["status"])
            self.assertEqual({"trials": 3.0, "wall_time_seconds": 1.25}, root["budget_spent"])
            self.assertEqual("promising", root["feedback"][0]["text"])
            self.assertEqual(["root"], child["parent_ids"])
            self.assertEqual(9, snapshot["event_count"])
            self.assertEqual(64, len(snapshot["head_event_hash"]))

            (graph_dir / "experiment_graph.json").unlink()
            rebuilt = rebuild_experiment_graph(graph_dir)
            self.assertEqual(snapshot, rebuilt)

    def test_hash_chain_detects_modified_event_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_dir = Path(tmp)
            store = ExperimentGraphStore(graph_dir, "tamper-check")
            store.create_node("root", base_commit="abc123")
            events_path = graph_dir / "experiment_events.jsonl"
            record = json.loads(events_path.read_text(encoding="utf-8"))
            record["payload"]["base_commit"] = "rewritten"
            events_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                rebuild_experiment_graph(graph_dir)

    def test_graph_rejects_missing_parent_and_invalid_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ExperimentGraphStore(Path(tmp), "validation-check")
            with self.assertRaisesRegex(ValueError, "parent nodes must exist"):
                store.create_node("child", parent_ids=["missing"], base_commit="abc123")

            store.create_node("root", base_commit="abc123")
            with self.assertRaisesRegex(ValueError, "invalid node status transition"):
                store.transition("root", "accepted")


if __name__ == "__main__":
    unittest.main()
