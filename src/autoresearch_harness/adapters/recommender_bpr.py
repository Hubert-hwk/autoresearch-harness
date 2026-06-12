from __future__ import annotations

import csv
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..evaluation import passes_guardrails
from ..models import TaskSpec, Trial, TrialResult


class RecommenderBprExecutor:
    """Small NumPy BPR recommender used as a real training/evaluation adapter."""

    def __init__(self, task: TaskSpec):
        if not task.dataset:
            raise ValueError("recommender_bpr requires a dataset path")
        self.task = task
        self.train_pairs, self.test_items, self.user_train_items, self.n_users, self.n_items = (
            _load_leave_last_split(Path(task.dataset))
        )

    def run(self, trial: Trial) -> TrialResult:
        started = time.perf_counter()
        params = trial.params
        rng = np.random.default_rng(20260612)
        factors = int(params["factors"])
        learning_rate = float(params["learning_rate"])
        regularization = float(params["regularization"])
        epochs = int(params["epochs"])
        negative_samples = int(params["negative_samples"])

        user_factors = rng.normal(0.0, 0.05, size=(self.n_users, factors))
        item_factors = rng.normal(0.0, 0.05, size=(self.n_items, factors))
        train_pairs = np.array(self.train_pairs, dtype=np.int64)

        for _ in range(epochs):
            rng.shuffle(train_pairs)
            for user, positive_item in train_pairs:
                for _ in range(negative_samples):
                    negative_item = _sample_negative(rng, self.user_train_items[user], self.n_items)
                    _update_bpr(
                        user_factors,
                        item_factors,
                        int(user),
                        int(positive_item),
                        negative_item,
                        learning_rate,
                        regularization,
                    )

        recommendations = _recommend_top_k(
            user_factors,
            item_factors,
            self.user_train_items,
            k=10,
        )
        train_time_sec = time.perf_counter() - started
        metrics = {
            "ndcg_at_10": round(_ndcg_at_k(recommendations, self.test_items, 10), 6),
            "hit_rate_at_10": round(_hit_rate_at_k(recommendations, self.test_items, 10), 6),
            "coverage_at_10": round(_coverage(recommendations, self.n_items), 6),
            "train_time_sec": round(train_time_sec, 6),
        }
        passed, notes = passes_guardrails(self.task, metrics)
        return TrialResult(
            trial_id=trial.id,
            params=params,
            metrics=metrics,
            passed_guardrails=passed,
            notes=notes,
        )


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
