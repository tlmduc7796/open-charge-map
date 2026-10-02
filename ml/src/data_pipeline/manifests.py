"""Run manifests make data lineage and test access auditable."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_dataset_manifest(
    output_path: Path,
    frame: pd.DataFrame,
    *,
    dataset_kind: str,
    source_paths: list[Path],
    split_column: str = "split",
    extra: dict[str, object] | None = None,
) -> Path:
    """Persist immutable lineage adjacent to a generated parquet dataset."""
    manifest = {
        "format_version": "data-manifest-1",
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_kind": dataset_kind,
        "output": str(output_path),
        "output_sha256": file_sha256(output_path),
        "records": int(len(frame)),
        "columns": list(frame.columns),
        "records_by_split": (
            {str(key): int(value) for key, value in frame[split_column].value_counts().items()}
            if split_column in frame
            else {}
        ),
        "source_files": [
            {"path": str(path), "sha256": file_sha256(path)}
            for path in source_paths
            if path.is_file()
        ],
        **(extra or {}),
    }
    path = output_path.with_suffix(".manifest.json")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path
