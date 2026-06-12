from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation import passes_guardrails
from ..models import TaskSpec, Trial, TrialResult


SEEDS = [20260612, 20260613, 20260614]


@dataclass(frozen=True)
class ArtifactRecord:
    created_at: str
    trial_id: str
    kind: str
    path: str
    description: str
    metadata: dict[str, Any]


class RecommenderBprExecutor:
    """Small NumPy BPR recommender used as a real training/evaluation adapter."""

    def __init__(self, task: TaskSpec):
        if not task.dataset:
            raise ValueError("recommender_bpr requires a dataset path")
        self.task = task
        self.dataset_path = Path(task.dataset)
        self.run_dir: Path | None = None
        self.train_pairs, self.test_items, self.user_train_items, self.n_users, self.n_items = (
            _load_leave_last_split(self.dataset_path)
        )
        self.dataset_fingerprint = _dataset_fingerprint(self.dataset_path, self.n_users, self.n_items)

    def set_run_dir(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def run(self, trial: Trial) -> TrialResult:
        started = time.perf_counter()
        params = trial.params
        factors = int(params["factors"])
        learning_rate = float(params["learning_rate"])
        regularization = float(params["regularization"])
        epochs = int(params["epochs"])
        negative_samples = int(params["negative_samples"])

        seed_results: list[dict[str, Any]] = []
        best_seed_model: tuple[int, np.ndarray, np.ndarray] | None = None
        best_seed_ndcg = -1.0
        for seed in SEEDS:
            seed_started = time.perf_counter()
            user_factors, item_factors = _train_bpr(
                seed=seed,
                n_users=self.n_users,
                n_items=self.n_items,
                factors=factors,
                train_pairs=self.train_pairs,
                user_train_items=self.user_train_items,
                epochs=epochs,
                negative_samples=negative_samples,
                learning_rate=learning_rate,
                regularization=regularization,
            )
            recommendations = _recommend_top_k(
                user_factors,
                item_factors,
                self.user_train_items,
                k=10,
            )
            seed_metrics = {
                "seed": seed,
                "ndcg_at_10": _ndcg_at_k(recommendations, self.test_items, 10),
                "hit_rate_at_10": _hit_rate_at_k(recommendations, self.test_items, 10),
                "coverage_at_10": _coverage(recommendations, self.n_items),
                "train_time_sec": time.perf_counter() - seed_started,
            }
            seed_results.append(seed_metrics)
            if seed_metrics["ndcg_at_10"] > best_seed_ndcg:
                best_seed_ndcg = seed_metrics["ndcg_at_10"]
                best_seed_model = (seed, user_factors, item_factors)

        train_time_sec = time.perf_counter() - started
        metrics = {
            "ndcg_at_10": round(_mean(seed_results, "ndcg_at_10"), 6),
            "ndcg_at_10_std": round(_std(seed_results, "ndcg_at_10"), 6),
            "hit_rate_at_10": round(_mean(seed_results, "hit_rate_at_10"), 6),
            "hit_rate_at_10_std": round(_std(seed_results, "hit_rate_at_10"), 6),
            "coverage_at_10": round(_mean(seed_results, "coverage_at_10"), 6),
            "coverage_at_10_std": round(_std(seed_results, "coverage_at_10"), 6),
            "train_time_sec": round(train_time_sec, 6),
            "seed_count": float(len(SEEDS)),
        }
        if self.run_dir and best_seed_model:
            self._write_trial_artifacts(trial, metrics, seed_results, best_seed_model)
        passed, notes = passes_guardrails(self.task, metrics)
        return TrialResult(
            trial_id=trial.id,
            params=params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )

    def _write_trial_artifacts(
        self,
        trial: Trial,
        metrics: dict[str, float],
        seed_results: list[dict[str, Any]],
        best_seed_model: tuple[int, np.ndarray, np.ndarray],
    ) -> None:
        assert self.run_dir is not None
        artifact_dir = self.run_dir / "executor_artifacts" / trial.id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        seed, user_factors, item_factors = best_seed_model
        model_path = artifact_dir / "model.npz"
        training_log_path = artifact_dir / "training_log.json"
        fingerprint_path = artifact_dir / "dataset_fingerprint.json"

        np.savez_compressed(
            model_path,
            user_factors=user_factors,
            item_factors=item_factors,
            seed=np.array([seed], dtype=np.int64),
        )
        training_log = {
            "trial_id": trial.id,
            "params": trial.params,
            "seeds": SEEDS,
            "seed_results": seed_results,
            "aggregate_metrics": metrics,
            "best_seed": seed,
        }
        training_log_path.write_text(json.dumps(training_log, ensure_ascii=False, indent=2), encoding="utf-8")
        fingerprint_path.write_text(
            json.dumps(self.dataset_fingerprint, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _append_artifact_record(
            self.run_dir,
            ArtifactRecord(
                created_at=_now(),
                trial_id=trial.id,
                kind="model_artifact",
                path=str(model_path),
                description="Best-seed NumPy BPR factor matrices for this trial",
                metadata={"best_seed": seed, "params": trial.params},
            ),
        )
        _append_artifact_record(
            self.run_dir,
            ArtifactRecord(
                created_at=_now(),
                trial_id=trial.id,
                kind="training_log",
                path=str(training_log_path),
                description="Per-seed BPR training and evaluation metrics",
                metadata={"seeds": SEEDS, "aggregate_metrics": metrics},
            ),
        )
        _append_artifact_record(
            self.run_dir,
            ArtifactRecord(
                created_at=_now(),
                trial_id=trial.id,
                kind="dataset_fingerprint",
                path=str(fingerprint_path),
                description="Dataset fingerprint used by this BPR trial",
                metadata=self.dataset_fingerprint,
            ),
        )


def _train_bpr(
    seed: int,
    n_users: int,
    n_items: int,
    factors: int,
    train_pairs: list[tuple[int, int]],
    user_train_items: dict[int, set[int]],
    epochs: int,
    negative_samples: int,
    learning_rate: float,
    regularization: float,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    user_factors = rng.normal(0.0, 0.05, size=(n_users, factors))
    item_factors = rng.normal(0.0, 0.05, size=(n_items, factors))
    pairs = np.array(train_pairs, dtype=np.int64)
    for _ in range(epochs):
        rng.shuffle(pairs)
        for user, positive_item in pairs:
            for _ in range(negative_samples):
                negative_item = _sample_negative(rng, user_train_items[user], n_items)
                _update_bpr(
                    user_factors,
                    item_factors,
                    int(user),
                    int(positive_item),
                    negative_item,
                    learning_rate,
                    regularization,
                )
    return user_factors, item_factors


def _load_leave_last_split(
    path: Path,
) -> tuple[list[tuple[int, int]], dict[int, int], dict[int, set[int]], int, int]:
    rows: list[tuple[str, str, int]] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            rows.append((row["user_id"], row["item_id"], int(row["timestamp"])))

    users = {user_id: index for index, user_id in enumerate(sorted({row[0] for row in rows}))}
    items = {item_id: index for index, item_id in enumerate(sorted({row[1] for row in rows}))}
    by_user: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for user_id, item_id, timestamp in rows:
        by_user[users[user_id]].append((timestamp, items[item_id]))

    train_pairs: list[tuple[int, int]] = []
    test_items: dict[int, int] = {}
    user_train_items: dict[int, set[int]] = {}
    for user, interactions in by_user.items():
        ordered = sorted(interactions)
        *train_items, test_item = [item for _, item in ordered]
        user_train_items[user] = set(train_items)
        test_items[user] = test_item
        for item in train_items:
            train_pairs.append((user, item))

    return train_pairs, test_items, user_train_items, len(users), len(items)


def _dataset_fingerprint(path: Path, n_users: int, n_items: int) -> dict[str, Any]:
    content = path.read_bytes()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "rows": max(0, len(lines) - 1),
        "n_users": n_users,
        "n_items": n_items,
    }


def _append_artifact_record(run_dir: Path, record: ArtifactRecord) -> None:
    with (run_dir / "executor_artifacts.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def _mean(records: list[dict[str, Any]], key: str) -> float:
    return float(sum(float(record[key]) for record in records) / len(records))


def _std(records: list[dict[str, Any]], key: str) -> float:
    values = [float(record[key]) for record in records]
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _sample_negative(rng: np.random.Generator, positives: set[int], n_items: int) -> int:
    while True:
        item = int(rng.integers(0, n_items))
        if item not in positives:
            return item


def _update_bpr(
    user_factors: np.ndarray,
    item_factors: np.ndarray,
    user: int,
    positive_item: int,
    negative_item: int,
    learning_rate: float,
    regularization: float,
) -> None:
    user_vector = user_factors[user].copy()
    positive_vector = item_factors[positive_item].copy()
    negative_vector = item_factors[negative_item].copy()
    score_delta = float(user_vector @ (positive_vector - negative_vector))
    gradient = 1.0 / (1.0 + math.exp(score_delta))

    user_factors[user] += learning_rate * (
        gradient * (positive_vector - negative_vector) - regularization * user_vector
    )
    item_factors[positive_item] += learning_rate * (
        gradient * user_vector - regularization * positive_vector
    )
    item_factors[negative_item] += learning_rate * (
        -gradient * user_vector - regularization * negative_vector
    )


def _recommend_top_k(
    user_factors: np.ndarray,
    item_factors: np.ndarray,
    user_train_items: dict[int, set[int]],
    k: int,
) -> dict[int, list[int]]:
    scores = user_factors @ item_factors.T
    recommendations: dict[int, list[int]] = {}
    for user, seen_items in user_train_items.items():
        user_scores = scores[user].copy()
        for item in seen_items:
            user_scores[item] = -np.inf
        top_items = np.argsort(-user_scores)[:k]
        recommendations[user] = [int(item) for item in top_items]
    return recommendations


def _hit_rate_at_k(recommendations: dict[int, list[int]], test_items: dict[int, int], k: int) -> float:
    hits = sum(1 for user, item in test_items.items() if item in recommendations[user][:k])
    return hits / len(test_items)


def _ndcg_at_k(recommendations: dict[int, list[int]], test_items: dict[int, int], k: int) -> float:
    total = 0.0
    for user, item in test_items.items():
        top_k = recommendations[user][:k]
        if item in top_k:
            rank = top_k.index(item)
            total += 1.0 / math.log2(rank + 2)
    return total / len(test_items)


def _coverage(recommendations: dict[int, list[int]], n_items: int) -> float:
    recommended_items = {item for items in recommendations.values() for item in items}
    return len(recommended_items) / n_items


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
