from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autoresearch_harness.datasets.movielens import prepare_movielens_100k


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare MovieLens 100K for the BPR recommender adapter.")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "external")
    parser.add_argument("--source-zip", type=Path)
    parser.add_argument("--min-rating", type=int, default=4)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    prepared = prepare_movielens_100k(
        args.output_root,
        min_rating=args.min_rating,
        source_zip=args.source_zip,
        download=not args.no_download,
        force=args.force,
    )
    print(json.dumps(asdict(prepared), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

