"""Load a versioned M2A artifact and emit the shared M2A → M2B demand payload."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from ml.station_demand.data import FEATURE_COLUMNS, TARGET_UNITS, feature_matrix


def load_model(model_dir: Path) -> tuple[Any, dict[str, Any]]:
    """Load the XGBoost JSON artifact and its lineage card."""
    try:
        from xgboost import Booster
    except ImportError as exc:  # pragma: no cover - exercised on minimal installs
        raise RuntimeError("M2A inference requires xgboost; install ml/requirements.txt") from exc
    card_path = model_dir / "model_card.json"
    model_path = model_dir / "demand_model.json"
    if not card_path.is_file() or not model_path.is_file():
        raise FileNotFoundError("M2A model artifact and model_card.json are both required")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    artifact_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if artifact_hash != card.get("model_sha256"):
        raise ValueError("model artifact hash does not match model_card.json")
    if card.get("feature_columns") != list(FEATURE_COLUMNS):
        raise ValueError("model card feature schema does not match this M2A pipeline")
    if card.get("target") not in TARGET_UNITS or card.get("unit") != TARGET_UNITS[card["target"]]:
        raise ValueError("model card target/unit pair is unsupported")
    model = Booster()
    model.load_model(model_path)
    return model, card


def predict_demand_payload(
    model: Any,
    model_card: Mapping[str, Any],
    *,
    subject_id: str,
    subject_type: str,
    features: Mapping[str, Any],
    time_window: Mapping[str, str],
    data_snapshot_id: str,
    scenario: str,
) -> dict[str, Any]:
    """Predict one record and return contract fields consumed directly by M2B.

    No uncertainty interval is emitted: this baseline pipeline has not calibrated predictive
    intervals. ``proxy`` marks inference from observed training data; synthetic-trained artifacts
    remain ``synthetic`` end-to-end.
    """
    if subject_type not in {"candidate", "demand_cell"} or not subject_id.strip():
        raise ValueError("subject_type must be candidate or demand_cell and subject_id is required")
    if not data_snapshot_id.strip() or not scenario.strip():
        raise ValueError("data_snapshot_id and scenario are required")
    if not isinstance(features, Mapping):
        raise ValueError("features must be a mapping")
    if (
        not isinstance(time_window, Mapping)
        or not time_window.get("start")
        or not time_window.get("end")
    ):
        raise ValueError("time_window.start and time_window.end are required")
    start = pd.Timestamp(time_window["start"])
    end = pd.Timestamp(time_window["end"])
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("demand time-window timestamps must include a timezone")
    if end <= start:
        raise ValueError("time_window.end must be after start")

    row = {
        column: features.get(column)
        for column in FEATURE_COLUMNS
        if column
        not in {"day_of_week_sin", "day_of_week_cos", "month_sin", "month_cos", "is_weekend"}
    }
    row["time_window_start"] = start
    row["time_window_end"] = end
    frame = pd.DataFrame([row])
    x = feature_matrix(frame)
    try:
        from xgboost import Booster, DMatrix
    except ImportError:  # pragma: no cover - xgboost is needed to load a trained artifact
        Booster = ()  # type: ignore[assignment]
        DMatrix = None  # type: ignore[assignment]
    if isinstance(model, Booster):
        prediction = float(
            model.predict(
                DMatrix(x, feature_names=list(FEATURE_COLUMNS)),
                iteration_range=(0, int(model.best_iteration) + 1),
            )[0]
        )
    else:
        prediction = float(model.predict(x)[0])
    prediction = max(0.0, prediction)
    model_version = model_card.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        raise ValueError("model card is missing model_version")
    target = str(model_card["target"])
    payload = {
        "target": target,
        "value": prediction,
        "unit": str(model_card["unit"]),
        "time_window": {"start": start.isoformat(), "end": end.isoformat()},
        "status": "synthetic" if model_card.get("is_synthetic") else "proxy",
        "source_id": model_version,
        "model_version": model_version,
        "data_snapshot_id": data_snapshot_id,
        "scenario": scenario,
    }
    payload[f"{subject_type}_id"] = subject_id
    return payload


def predict_many(
    model: Any,
    model_card: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map a sequence of M1 candidate/cell feature records to M2B payloads."""
    result = []
    for record in records:
        subject_type = str(record.get("subject_type", ""))
        result.append(
            predict_demand_payload(
                model,
                model_card,
                subject_id=str(record.get("subject_id", "")),
                subject_type=subject_type,
                features=record.get("features", {}),
                time_window=record.get("time_window", {}),
                data_snapshot_id=str(record.get("data_snapshot_id", "")),
                scenario=str(record.get("scenario", "")),
            )
        )
    return result
