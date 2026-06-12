from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .models import TaskSpec


@dataclass(frozen=True)
class MemoryMatch:
    memory_id: str
    score: int
    reasons: list[str]
    record: dict[str, Any]


def build_memory_context(
    task: TaskSpec,
    analysis: dict[str, Any],
    memories: list[dict[str, Any]],
    limit: int = 5,
) -> dict[str, Any]:
    """Rank durable lessons by relevance to the current task and baseline failures."""

    query = _query_terms(task, analysis)
    matches: list[MemoryMatch] = []
    for index, memory in enumerate(memories):
        score, reasons = _score_memory(query, memory)
        if score > 0:
            matches.append(
                MemoryMatch(
                    memory_id=_memory_id(memory, index),
                    score=score,
                    reasons=reasons,
                    record=memory,
                )
            )

    matches.sort(key=lambda item: (-item.score, item.memory_id))
    selected = matches[:limit]
    return {
        "query": query,
        "total_memories": len(memories),
        "matched_memories": len(matches),
        "matches": [asdict(match) for match in selected],
    }


def records_from_context(memory_context: dict[str, Any]) -> list[dict[str, Any]]:
    return [match["record"] for match in memory_context.get("matches", [])]


def compact_memory_context(memory_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_memories": memory_context.get("total_memories", 0),
        "matched_memories": memory_context.get("matched_memories", 0),
        "matches": [
            {
                "memory_id": match["memory_id"],
                "score": match["score"],
                "reasons": match["reasons"],
            }
            for match in memory_context.get("matches", [])
        ],
    }


def _query_terms(task: TaskSpec, analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "executor": task.executor,
        "primary_metric": task.primary_metric.name,
        "guardrails": [metric.name for metric in task.guardrail_metrics],
        "failure_reasons": sorted(analysis.get("failure_reasons", {}).keys()),
        "params": sorted(task.search_space.keys()),
    }


def _score_memory(query: dict[str, Any], memory: dict[str, Any]) -> tuple[int, list[str]]:
    text = json.dumps(memory, ensure_ascii=False, sort_keys=True).lower()
    score = 0
    reasons: list[str] = []

    executor = str(query["executor"]).lower()
    if executor and executor in text:
        score += 5
        reasons.append(f"executor:{query['executor']}")

    for failure in query["failure_reasons"]:
        if _contains(text, failure):
            score += 4
            reasons.append(f"failure:{failure}")

    for guardrail in query["guardrails"]:
        if _contains(text, guardrail):
            score += 3
            reasons.append(f"guardrail:{guardrail}")

    primary_metric = query["primary_metric"]
    if _contains(text, primary_metric):
        score += 2
        reasons.append(f"primary_metric:{primary_metric}")

    for param in query["params"]:
        if _contains(text, param):
            score += 2
            reasons.append(f"param:{param}")

    recommendation = str(memory.get("recommendation", "")).lower()
    if recommendation:
        score += 1
        reasons.append(f"recommendation:{recommendation}")

    return score, reasons


def _contains(text: str, term: str) -> bool:
    return str(term).lower() in text


def _memory_id(memory: dict[str, Any], index: int) -> str:
    research_id = memory.get("research_id")
    hypothesis_id = memory.get("hypothesis_id")
    if research_id and hypothesis_id:
        return f"{research_id}:{hypothesis_id}"
    if hypothesis_id:
        return str(hypothesis_id)
    created_at = memory.get("created_at")
    if created_at:
        return str(created_at)
    return f"memory_{index:04d}"
