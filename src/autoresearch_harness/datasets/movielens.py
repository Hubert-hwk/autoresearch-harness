from __future__ import annotations

import csv
import hashlib
import json
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


MOVIELENS_100K_URL = "https://files.grouplens.org/datasets/movielens/ml-100k.zip"


@dataclass(frozen=True)
class MovieLensPreparation:
    dataset: str
    source: str
    min_rating: int
    output_path: str
    summary_path: str
    raw_path: str
    rows: int
    n_users: int
    n_items: int
    sha256: str


def prepare_movielens_100k(
    output_root: Path,
    *,
    min_rating: int = 4,
    source_zip: Path | None = None,
    download: bool = True,
    force: bool = False,
) -> MovieLensPreparation:
    """Prepare MovieLens 100K as implicit positive-feedback interactions.

    The recommender BPR executor consumes a compact CSV contract:
    user_id,item_id,timestamp. This helper keeps the public benchmark data
    outside git while making the converted input reproducible.
    """

    dataset_root = output_root / "ml-100k"
    raw_root = dataset_root / "raw"
    output_path = dataset_root / "interactions.csv"
    summary_path = dataset_root / "dataset_summary.json"

    if output_path.exists() and summary_path.exists() and not force:
        prepared = _read_summary(summary_path)
        if prepared.min_rating == min_rating:
            return prepared

    raw_root.mkdir(parents=True, exist_ok=True)
    dataset_root.mkdir(parents=True, exist_ok=True)
    u_data = _resolve_u_data(raw_root, source_zip, download)
    rows, n_users, n_items = _convert_u_data(u_data, output_path, min_rating)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    prepared = MovieLensPreparation(
        dataset="movielens_100k",
        source=str(source_zip.resolve()) if source_zip else MOVIELENS_100K_URL,
        min_rating=min_rating,
        output_path=str(output_path.resolve()),
        summary_path=str(summary_path.resolve()),
        raw_path=str(u_data.resolve()),
        rows=rows,
        n_users=n_users,
        n_items=n_items,
        sha256=digest,
    )
    summary_path.write_text(json.dumps(asdict(prepared), ensure_ascii=False, indent=2), encoding="utf-8")
    return prepared


def _resolve_u_data(raw_root: Path, source_zip: Path | None, download: bool) -> Path:
    existing = raw_root / "ml-100k" / "u.data"
    if existing.exists():
        return existing

    if source_zip:
        _extract_zip(source_zip, raw_root)
        if existing.exists():
            return existing
        raise FileNotFoundError(f"MovieLens zip did not contain expected file: {existing}")

    zip_path = raw_root / "ml-100k.zip"
    if not zip_path.exists():
        if not download:
            raise FileNotFoundError(
                "MovieLens 100K raw data is missing. Re-run with download enabled "
                "or pass --source-zip to an existing ml-100k.zip."
            )
        urllib.request.urlretrieve(MOVIELENS_100K_URL, zip_path)

    _extract_zip(zip_path, raw_root)
    if not existing.exists():
        raise FileNotFoundError(f"MovieLens archive did not contain expected file: {existing}")
    return existing


def _extract_zip(zip_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if root != target and root not in target.parents:
                raise ValueError(f"Refusing to extract zip member outside destination: {member.filename}")
        archive.extractall(destination)


def _convert_u_data(u_data: Path, output_path: Path, min_rating: int) -> tuple[int, int, int]:
    rows = 0
    users: set[str] = set()
    items: set[str] = set()
    with u_data.open("r", encoding="latin-1", newline="") as source:
        reader = csv.reader(source, delimiter="\t")
        with output_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=["user_id", "item_id", "timestamp"])
            writer.writeheader()
            for user_id, item_id, rating, timestamp in reader:
                if int(rating) < min_rating:
                    continue
                writer.writerow(
                    {
                        "user_id": user_id,
                        "item_id": item_id,
                        "timestamp": timestamp,
                    }
                )
                users.add(user_id)
                items.add(item_id)
                rows += 1
    if rows == 0:
        raise ValueError(f"No MovieLens interactions met min_rating={min_rating}")
    return rows, len(users), len(items)


def _read_summary(summary_path: Path) -> MovieLensPreparation:
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    return MovieLensPreparation(**data)
