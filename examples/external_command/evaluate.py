from __future__ import annotations

import json
import os
import time
from pathlib import Path


def main() -> None:
    started = time.perf_counter()
    params = json.loads(Path(os.environ["AUTORESEARCH_TRIAL_PARAMS"]).read_text(encoding="utf-8"))
    dataset = [
        json.loads(line)
        for line in Path(os.environ["AUTORESEARCH_DATASET"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_count = min(len(dataset), int(params.get("case_count", len(dataset))))
    dataset = dataset[:case_count]
    output_dir = Path(os.environ["AUTORESEARCH_OUTPUT_DIR"])

    predictions = []
    for row in dataset:
        score = (
            float(row["signal"]) * float(params["signal_weight"])
            + float(row["context"]) * 0.2
            + float(params["bias"])
        )
        prediction = int(score >= float(params["threshold"]))
        predictions.append(
            {
                "id": row["id"],
                "score": round(score, 6),
                "prediction": prediction,
                "label": int(row["label"]),
            }
        )

    correct = sum(item["prediction"] == item["label"] for item in predictions)
    negatives = [item for item in predictions if item["label"] == 0]
    false_positives = sum(item["prediction"] == 1 for item in negatives)
    metrics = {
        "accuracy": correct / len(predictions),
        "false_positive_rate": false_positives / len(negatives),
        "evaluation_time_ms": (time.perf_counter() - started) * 1000,
        "evaluated_cases": float(len(dataset)),
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "details.json").write_text(
        json.dumps({"params": params, "predictions": predictions}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
