#!/usr/bin/env python3
"""Validate ML artifacts and feature-data provenance without training a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:  # Supports both `python ml/src/...py` and package imports in tests/notebooks.
    from .feature_contract import CONTRACT_VERSION, HORIZONS_MIN, get_feature_profile, target_column
except ImportError:  # pragma: no cover - direct script invocation.
    from feature_contract import CONTRACT_VERSION, HORIZONS_MIN, get_feature_profile, target_column

ROOT_DIR = Path(__file__).resolve().parents[2]


def validate(dataset_path: Path) -> dict[str, object]:
    meta_path = dataset_path.with_suffix(".meta.json")
    if not dataset_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError("Build the feature dataset before validating it")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Unsupported feature contract version")
    profile = get_feature_profile(str(meta.get("profile")))
    columns = ["split", *profile.feature_names, *(target_column(h) for h in HORIZONS_MIN)]
    frame = pd.read_parquet(dataset_path, columns=columns)
    if frame.isna().any().any():
        raise ValueError("Feature dataset has null values")
    if not frame["split"].isin(["train", "val", "test"]).all():
        raise ValueError("Feature dataset has invalid split values")
    return {
        "result": "PASS",
        "profile": profile.name,
        "serving_ready": profile.serving_ready,
        "serving_reason": profile.serving_reason,
        "records": int(len(frame)),
        "records_by_split": {
            key: int(value) for key, value in frame["split"].value_counts().items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT_DIR / "ml/artifacts/occupancy_features_baseline.parquet",
    )
    args = parser.parse_args()
    print(json.dumps(validate(args.dataset), indent=2))


if __name__ == "__main__":
    main()
