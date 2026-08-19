from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.applied import run_patch_experiment
from autoresearch_harness.models import MutationPolicy
from autoresearch_harness.patching import (
    PatchOperation,
    PatchPlan,
    apply_patch_plan,
    load_patch_plan,
)
from autoresearch_harness.spec import load_task
from autoresearch_harness.workspace import WorkspaceRecord, WorktreeManager


class PatchingTest(unittest.TestCase):
    def test_patch_experiment_isolated_from_source_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            self._git(repo, "init", "-b", "main")
            self._git(repo, "config", "user.email", "tests@example.com")
            self._git(repo, "config", "user.name", "AutoResearch Tests")
            (repo / "evaluator.py").write_text(_EVALUATOR, encoding="utf-8")
            (repo / "notes.txt").write_text("committed\n", encoding="utf-8")
            (repo / "task.json").write_text(json.dumps(_TASK), encoding="utf-8")
            self._git(repo, "add", "evaluator.py", "notes.txt", "task.json")
            self._git(repo, "commit", "-m", "fixture")
            base_commit = self._git(repo, "rev-parse", "HEAD")
            (repo / "notes.txt").write_text("user change\n", encoding="utf-8")

            plan_path = root / "patch.json"
            plan_path.write_text(json.dumps(_PATCH_PLAN), encoding="utf-8")
            result = run_patch_experiment(
                load_task(repo / "task.json"),
                load_patch_plan(plan_path),
                repo_root=repo,
                runs_dir=root / "runs",
                workspaces_dir=repo / "runs" / "worktrees",
                base_commit=base_commit,
            )
            workspace = Path(result["workspace"]["workspace_path"])
            experiment_dir = Path(result["paths"]["experiment_dir"])

            self.assertEqual("completed", result["status"])
            self.assertEqual("evaluated", result["experiment_node"]["status"])
            self.assertEqual(1.0, result["candidate"]["best_result"]["metrics"]["score"])
            self.assertIn("BONUS = 1.0", (workspace / "evaluator.py").read_text(encoding="utf-8"))
            self.assertIn("BONUS = 0.0", (repo / "evaluator.py").read_text(encoding="utf-8"))
            self.assertEqual("user change\n", (repo / "notes.txt").read_text(encoding="utf-8"))
            self.assertEqual("main", self._git(repo, "branch", "--show-current"))
            self.assertIn("BONUS = 1.0", (experiment_dir / "mutation.diff").read_text(encoding="utf-8"))
            self.assertTrue((experiment_dir / "patch_application.json").is_file())
            self.assertTrue((experiment_dir / "experiment_events.jsonl").is_file())
            self.assertTrue((experiment_dir / "experiment_graph.json").is_file())
            self.assertEqual(
                "verified",
                json.loads(
                    (experiment_dir / "workspace_audit_after.json").read_text(encoding="utf-8")
                )["status"],
            )

            follow_up = run_patch_experiment(
                load_task(repo / "task.json"),
                load_patch_plan(plan_path),
                repo_root=repo,
                runs_dir=root / "runs",
                workspaces_dir=repo / "runs" / "worktrees",
                base_commit=base_commit,
                graph_dir=experiment_dir,
                node_id="follow-up",
                parent_node_ids=["candidate"],
            )
            graph = json.loads(
                (experiment_dir / "experiment_graph.json").read_text(encoding="utf-8")
            )
            self.assertEqual(["candidate"], follow_up["experiment_node"]["parent_ids"])
            self.assertEqual(2, len(graph["nodes"]))

            manager = WorktreeManager(repo, repo / "runs" / "worktrees")
            manager.remove(WorkspaceRecord(**follow_up["workspace"]), force=True)
            manager.remove(WorkspaceRecord(**result["workspace"]), force=True)
            self.assertFalse(workspace.exists())

    def test_evaluator_workspace_side_effect_fails_audit_and_retains_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            self._git(repo, "init", "-b", "main")
            self._git(repo, "config", "user.email", "tests@example.com")
            self._git(repo, "config", "user.name", "AutoResearch Tests")
            evaluator = _EVALUATOR + '\nPath("unexpected.txt").write_text("side effect")\n'
            (repo / "evaluator.py").write_text(evaluator, encoding="utf-8")
            (repo / "task.json").write_text(json.dumps(_TASK), encoding="utf-8")
            self._git(repo, "add", "evaluator.py", "task.json")
            self._git(repo, "commit", "-m", "fixture")
            plan_path = root / "patch.json"
            plan_path.write_text(json.dumps(_PATCH_PLAN), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "diverged from patch plan"):
                run_patch_experiment(
                    load_task(repo / "task.json"),
                    load_patch_plan(plan_path),
                    repo_root=repo,
                    runs_dir=root / "runs",
                    workspaces_dir=root / "worktrees",
                )

            experiment_dir = next((root / "runs").glob("patch_*"))
            state = json.loads((experiment_dir / "state.json").read_text(encoding="utf-8"))
            graph = json.loads(
                (experiment_dir / "experiment_graph.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", state["status"])
            self.assertTrue(state["workspace_retained"])
            self.assertEqual("failed", graph["nodes"][0]["status"])
            self.assertFalse((repo / "unexpected.txt").exists())

    def test_patch_validation_is_atomic_when_later_operation_is_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            allowed = workspace / "allowed.txt"
            allowed.write_text("before\n", encoding="utf-8")
            plan = PatchPlan(
                id="atomic-check",
                protocol_version="patch.v1",
                rationale="",
                operations=[
                    PatchOperation(
                        op="replace_text",
                        path="allowed.txt",
                        old="before",
                        new="after",
                    ),
                    PatchOperation(
                        op="create_file",
                        path="forbidden.txt",
                        content="no",
                    ),
                ],
            )

            with self.assertRaisesRegex(ValueError, "outside editable paths"):
                apply_patch_plan(
                    workspace,
                    MutationPolicy(editable_paths=["allowed.txt"], allow_create=True),
                    plan,
                    workspace / "change.diff",
                )

            self.assertEqual("before\n", allowed.read_text(encoding="utf-8"))
            self.assertFalse((workspace / "forbidden.txt").exists())

    def test_patch_plan_rejects_parent_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            payload = dict(_PATCH_PLAN)
            payload["operations"] = [
                {
                    "op": "replace_text",
                    "path": "../outside.py",
                    "old": "a",
                    "new": "b",
                }
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "normalized relative"):
                load_patch_plan(path)

    def test_patch_plan_rejects_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            payload = dict(_PATCH_PLAN)
            payload["operations"] = [
                {
                    "op": "replace_text",
                    "path": ".git",
                    "old": "gitdir:",
                    "new": "broken:",
                }
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "protected Git metadata"):
                load_patch_plan(path)

    def test_patch_rejects_symlinked_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "real").mkdir()
            (workspace / "real" / "value.txt").write_text("before\n")
            (workspace / "config").symlink_to(workspace / "real", target_is_directory=True)
            plan = PatchPlan(
                id="symlink-check",
                protocol_version="patch.v1",
                rationale="",
                operations=[
                    PatchOperation(
                        op="replace_text",
                        path="config/value.txt",
                        old="before",
                        new="after",
                    )
                ],
            )

            with self.assertRaisesRegex(ValueError, "symlink component"):
                apply_patch_plan(
                    workspace,
                    MutationPolicy(editable_paths=["config"]),
                    plan,
                    workspace / "change.diff",
                )

            self.assertEqual("before\n", (workspace / "real" / "value.txt").read_text())

    def test_create_file_inside_editable_directory_records_new_file_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "config").mkdir()
            plan = PatchPlan(
                id="create-config",
                protocol_version="patch.v1",
                rationale="Exercise allowlisted file creation.",
                operations=[
                    PatchOperation(
                        op="create_file",
                        path="config/candidate.json",
                        content='{"enabled": true}\n',
                    )
                ],
            )

            application = apply_patch_plan(
                workspace,
                MutationPolicy(editable_paths=["config"], allow_create=True),
                plan,
                workspace / "change.diff",
            )

            self.assertEqual('{"enabled": true}\n', (workspace / "config/candidate.json").read_text())
            self.assertIsNone(application.changes[0].before_sha256)
            self.assertIn("--- /dev/null", (workspace / "change.diff").read_text())

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

BONUS = 0.0
params = json.loads(Path(os.environ["AUTORESEARCH_TRIAL_PARAMS"]).read_text())
output = Path(os.environ["AUTORESEARCH_OUTPUT_DIR"])
(output / "metrics.json").write_text(json.dumps({"score": params["value"] + BONUS}))
"""

_TASK = {
    "schema_version": "task.v2",
    "name": "patch_fixture",
    "objective": "Improve an evaluator constant.",
    "executor": "external_command",
    "budget": {"max_trials": 1},
    "search_space": {"value": {"type": "categorical", "values": [0.0]}},
    "metrics": {"primary": {"name": "score", "direction": "maximize"}, "guardrails": []},
    "execution": {
        "command": ["{python}", "evaluator.py"],
        "working_directory": ".",
        "metrics_path": "metrics.json",
        "timeout_seconds": 5,
    },
    "mutation": {
        "editable_paths": ["evaluator.py"],
        "allow_create": False,
        "max_file_bytes": 10000,
    },
}

_PATCH_PLAN = {
    "protocol_version": "patch.v1",
    "id": "raise-bonus",
    "rationale": "Exercise isolated patch evaluation.",
    "operations": [
        {
            "op": "replace_text",
            "path": "evaluator.py",
            "old": "BONUS = 0.0",
            "new": "BONUS = 1.0",
            "expected_replacements": 1,
        }
    ],
}


if __name__ == "__main__":
    unittest.main()
