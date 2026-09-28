"""Data manifest: content hashes, shapes and provenance of every dataset under ``data/``.

The manifest is the lightweight data-versioning contract: training runs log it
to MLflow (artifact + ``data_version`` tag) for lineage, and the data-quality
test suite fails when a file drifts from its recorded hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

MANIFEST_VERSION = 2
DATA_SUBDIRS = ("raw", "reference", "processed")

DATASET_SOURCE: dict[str, str] = {
    "name": "Default of Credit Card Clients (UCI ML Repository, id 350)",
    "url": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
    "license": "CC BY 4.0",
    "citation": "Yeh, I. C., & Lien, C. H. (2009). Expert Systems with Applications, 36(2), 2473-2480.",
}

FILE_SOURCES: dict[str, str] = {
    "raw/credit_default.csv": "UCI dataset id 350 (curated copy, 30,000 rows)",
    "reference/train_baseline.csv": "derived from raw/credit_default.csv by scripts/split_data.py (AGE >= 30)",
    "processed/stream_normal.csv": "derived from raw/credit_default.csv by scripts/split_data.py (AGE >= 30)",
    "processed/stream_drifted.csv": "derived from raw/credit_default.csv by scripts/split_data.py (AGE < 30)",
    "processed/ground_truth_feedback.csv": "delayed labels of processed/stream_drifted.csv (scripts/split_data.py)",
}


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    """Return the hex SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Path, data_dir: Path) -> dict[str, Any]:
    """Describe a CSV file by hash, size, row count, column names and provenance."""
    frame = pd.read_csv(path)
    relative = path.relative_to(data_dir).as_posix()
    return {
        "path": relative,
        "sha256": sha256_of(path),
        "bytes": path.stat().st_size,
        "rows": int(frame.shape[0]),
        "columns": list(frame.columns),
        "source": FILE_SOURCES.get(relative, "unknown"),
    }


def manifest_fingerprint(files: list[dict[str, Any]]) -> str:
    """Stable short identifier of a dataset snapshot: SHA-256 over sorted ``path:sha256`` pairs."""
    joined = "\n".join(f"{entry['path']}:{entry['sha256']}" for entry in sorted(files, key=lambda e: e["path"]))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_manifest(data_dir: Path) -> dict[str, Any]:
    """Build a manifest for all CSV files in the standard data sub-directories."""
    files = [
        describe_file(path, data_dir) for subdir in DATA_SUBDIRS for path in sorted((data_dir / subdir).glob("*.csv"))
    ]
    return {
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fingerprint": manifest_fingerprint(files),
        "dataset": DATASET_SOURCE,
        "files": files,
    }


def write_manifest(data_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Build and write the manifest as pretty-printed JSON."""
    manifest = build_manifest(data_dir)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Read a manifest JSON file."""
    content: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return content


def find_entry(manifest: dict[str, Any], relative_path: str) -> dict[str, Any] | None:
    """Return the manifest entry for ``relative_path`` (relative to ``data/``), if any."""
    return next((entry for entry in manifest.get("files", []) if entry["path"] == relative_path), None)


def verify_file(manifest: dict[str, Any], data_dir: Path, relative_path: str) -> bool:
    """Whether the file on disk still matches the hash recorded in the manifest."""
    entry = find_entry(manifest, relative_path)
    path = data_dir / relative_path
    return entry is not None and path.exists() and sha256_of(path) == entry["sha256"]
