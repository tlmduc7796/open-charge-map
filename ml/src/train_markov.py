#!/usr/bin/env python3
"""Fit an interpretable connector-aware Markov transition table.

This is an aggregate fallback only.  It cannot replace DES when a provider has
per-port state, session durations and a confirmed queue.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

ROOT_DIR = Path(__file__).resolve().parents[2]


def _with_transitions(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"station_id", "connector_type", "observed_at", "available_ports", "split"}
    if missing := required - set(frame.columns):
        raise ValueError(f"Markov state dataset misses columns: {sorted(missing)}")
    result = frame.copy()
    result["observed_at"] = pd.to_datetime(result["observed_at"], utc=True, errors="raise")
    result = result.sort_values(["station_id", "connector_type", "observed_at"])
    grouped = result.groupby(["station_id", "connector_type"], sort=False)
    result["next_available_ports"] = grouped["available_ports"].shift(-1)
    result["next_observed_at"] = grouped["observed_at"].shift(-1)
    result["next_split"] = grouped["split"].shift(-1)
    cadence = (result["next_observed_at"] - result["observed_at"]).dt.total_seconds() / 60
    # Gaps must not masquerade as one Markov transition.
    modal_cadence = cadence.dropna().mode()
    if modal_cadence.empty or modal_cadence.iloc[0] <= 0:
        raise ValueError("Cannot infer Markov state cadence")
    result = result.loc[
        (cadence == modal_cadence.iloc[0]) & (result["split"] == result["next_split"])
    ].copy()
    result["next_available_ports"] = result["next_available_ports"].astype(int)
    result["has_available_next"] = result["next_available_ports"] > 0
    result["cadence_min"] = int(modal_cadence.iloc[0])
    return result


def _fit_transition_table(train: pd.DataFrame) -> pd.DataFrame:
    counts = (
        train.groupby(["station_id", "connector_type", "available_ports", "next_available_ports"])
        .size()
        .rename("count")
        .reset_index()
    )
    counts["probability"] = counts["count"] / counts.groupby(
        ["station_id", "connector_type", "available_ports"]
    )["count"].transform("sum")
    return counts


def _probability_available(table: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    available = table.loc[table["next_available_ports"] > 0]
    probability = (
        available.groupby(["station_id", "connector_type", "available_ports"])["probability"]
        .sum()
        .rename("probability_available_next")
        .reset_index()
    )
    joined = rows.merge(
        probability, on=["station_id", "connector_type", "available_ports"], how="left"
    )
    # No matching historical state is not a confident zero; return station's
    # validation-base availability rate as a transparent cold-state fallback.
    fallback = float(rows["has_available_next"].mean())
    return joined["probability_available_next"].fillna(fallback).to_numpy(dtype=float)


def train_markov(
    dataset_path: Path,
    artifact_path: Path,
    *,
    evaluate_test: bool = False,
) -> dict[str, object]:
    frame = _with_transitions(pd.read_parquet(dataset_path))
    train = frame.loc[frame["split"] == "train"]
    validation = frame.loc[frame["split"] == "val"]
    if train.empty or validation.empty:
        raise ValueError("Markov training requires transition rows in train and validation")
    table = _fit_transition_table(train)
    validation_probability = _probability_available(table, validation)
    metadata: dict[str, object] = {
        "format_version": "markov-transition-1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "experimental_aggregate_fallback_only",
        "dataset": str(dataset_path),
        "cadence_min": int(frame["cadence_min"].iloc[0]),
        "state": "available compatible ports per station and connector",
        "validation_brier_available_next": round(
            float(brier_score_loss(validation["has_available_next"], validation_probability)), 6
        ),
        "test_accessed": False,
        "limitations": [
            "Does not identify a specific port/session or queue order.",
            "Do not use when DES inputs are fresh and complete.",
        ],
    }
    if evaluate_test:
        test = frame.loc[frame["split"] == "test"]
        test_probability = _probability_available(table, test)
        metadata.update(
            {
                "test_accessed": True,
                "test_accessed_at": datetime.now(UTC).isoformat(),
                "test_status": "exploratory_until_protocol_is_frozen",
                "test_brier_available_next": round(
                    float(brier_score_loss(test["has_available_next"], test_probability)), 6
                ),
            }
        )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps({"metadata": metadata, "transitions": table.to_dict(orient="records")}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return {"artifact": str(artifact_path), **metadata}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/data/gold/markov/connector_states.parquet"
    )
    parser.add_argument(
        "--artifact", type=Path, default=ROOT_DIR / "ml/artifacts/markov/transitions.json"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evaluate-test", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "will_train": False,
                    "dataset": str(args.dataset),
                    "next_step": "Build connector-aware port states, then add --execute.",
                    "des_rule": "DES remains preferred when per-port/session/queue data exists.",
                },
                indent=2,
            )
        )
        return
    print(
        json.dumps(
            train_markov(args.dataset, args.artifact, evaluate_test=args.evaluate_test), indent=2
        )
    )


if __name__ == "__main__":
    main()
