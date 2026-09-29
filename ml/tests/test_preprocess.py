"""Tests for Phase 03 UrbanEV preprocessing and invariants."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = ROOT_DIR / "ml" / "artifacts"
PARQUET_PATH = ARTIFACTS_DIR / "urbanev_processed.parquet"
MANIFEST_PATH = ARTIFACTS_DIR / "split_manifest.json"
META_PATH = ARTIFACTS_DIR / "preprocessing_meta.json"


def test_phase3_artifacts_exist():
    assert PARQUET_PATH.is_file(), "urbanev_processed.parquet must exist"
    assert MANIFEST_PATH.is_file(), "split_manifest.json must exist"
    assert META_PATH.is_file(), "preprocessing_meta.json must exist"


def test_split_manifest_contents():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["source_dataset"] == "UrbanEV"
    assert manifest["temporal_resolution_min"] == 5
    assert manifest["total_stations"] == 50
    assert manifest["total_records"] == 2_606_400
    assert "train" in manifest["splits"]
    assert "val" in manifest["splits"]
    assert "test" in manifest["splits"]


def test_processed_parquet_invariants():
    df = pd.read_parquet(PARQUET_PATH)

    # Invariants
    assert len(df) == 2_606_400
    assert set(df.columns) == {
        "timestamp",
        "entity_id",
        "entity_level",
        "interval_min",
        "total_ports",
        "occupied_ports",
        "occupancy_ratio",
        "split",
        "data_source",
    }
    assert (df["occupied_ports"] >= 0).all()
    assert (df["occupied_ports"] <= df["total_ports"]).all()
    assert (df["occupancy_ratio"] >= 0.0).all()
    assert (df["occupancy_ratio"] <= 1.0).all()
    assert df["timestamp"].notnull().all()

    # Temporal split boundaries (no leakage)
    train_max = df[df["split"] == "train"]["timestamp"].max()
    val_min = df[df["split"] == "val"]["timestamp"].min()
    val_max = df[df["split"] == "val"]["timestamp"].max()
    test_min = df[df["split"] == "test"]["timestamp"].min()

    assert train_max < val_min, f"Train max {train_max} must precede Val min {val_min}"
    assert val_max < test_min, f"Val max {val_max} must precede Test min {test_min}"
