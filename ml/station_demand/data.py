"""Versioned training-table contract, validation, time features, and synthetic demo data."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import numpy as np
import pandas as pd

TIMEZONE = "Asia/Ho_Chi_Minh"
TARGET_UNITS = {
    "charging_sessions": "sessions_per_day",
    "charging_energy": "kwh_per_day",
}
BASE_FEATURE_COLUMNS = (
    "poi_sustenance_count",
    "poi_retail_count",
    "poi_education_count",
    "poi_healthcare_count",
    "poi_transit_count",
    "population_density_per_km2",
    "building_density_per_km2",
    "road_traffic_index",
    "road_accessibility_index",
    "fleet_activity_index",
    "home_charging_share",
    "nearby_compatible_ports",
    "nearby_station_uptime",
    "charger_power_kw",
)
TEMPORAL_FEATURE_COLUMNS = (
    "day_of_week_sin",
    "day_of_week_cos",
    "month_sin",
    "month_cos",
    "is_weekend",
)
FEATURE_COLUMNS = BASE_FEATURE_COLUMNS + TEMPORAL_FEATURE_COLUMNS
REQUIRED_COLUMNS = (
    "spatial_unit_id",
    "spatial_group",
    "time_window_start",
    "time_window_end",
    "target",
    "value",
    "unit",
    "status",
    "source_id",
    "data_snapshot_id",
    "is_synthetic",
    *BASE_FEATURE_COLUMNS,
)
VALID_DATA_STATUSES = {"observed", "proxy", "synthetic", "scenario", "unknown", "not_applicable"}


@dataclass(frozen=True, slots=True)
class DatasetSplits:
    train: pd.DataFrame
    validation: pd.DataFrame
    temporal_test: pd.DataFrame
    spatial_test: pd.DataFrame
    spatial_holdout_groups: tuple[str, ...]


def _aware_timestamp(value: object, field: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{field} timestamps must include a timezone")
    return stamp.tz_convert("UTC")


def validate_training_table(
    frame: pd.DataFrame,
    *,
    target: str,
    unit: str | None = None,
    allow_synthetic: bool = False,
) -> pd.DataFrame:
    """Validate M1's labeled training rows without turning missing values into zeros.

    Proxy/scenario records are deliberately rejected as labels. They may be features, but do not
    become observed demand targets by entering the training table.
    """
    if target not in TARGET_UNITS:
        raise ValueError(f"unsupported demand target: {target}")
    expected_unit = TARGET_UNITS[target]
    if unit is not None and unit != expected_unit:
        raise ValueError(f"target {target} requires unit {expected_unit}")
    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"training table is missing columns: {sorted(missing)}")

    result = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    for column in (
        "spatial_unit_id",
        "spatial_group",
        "target",
        "unit",
        "status",
        "source_id",
        "data_snapshot_id",
    ):
        result[column] = result[column].astype("string").str.strip()
        if result[column].isna().any() or result[column].eq("").any():
            raise ValueError(f"{column} must contain non-empty values")

    result["time_window_start"] = pd.to_datetime(
        [_aware_timestamp(value, "time_window_start") for value in result["time_window_start"]],
        utc=True,
    )
    result["time_window_end"] = pd.to_datetime(
        [_aware_timestamp(value, "time_window_end") for value in result["time_window_end"]],
        utc=True,
    )
    if (result["time_window_end"] <= result["time_window_start"]).any():
        raise ValueError("time_window_end must be after time_window_start")

    if not result["target"].eq(target).all() or not result["unit"].eq(expected_unit).all():
        raise ValueError("a training run must contain exactly one target and its compatible unit")
    if result["status"].isin({"proxy", "scenario", "unknown", "not_applicable"}).any():
        raise ValueError(
            "proxy, scenario, unknown, and not_applicable values cannot be demand labels"
        )
    if not result["status"].isin({"observed", "synthetic"}).all():
        raise ValueError("demand labels must be observed or explicitly synthetic")

    synthetic_flags = result["is_synthetic"].map(_parse_bool)
    result["is_synthetic"] = synthetic_flags
    synthetic_rows = result["status"].eq("synthetic")
    if not synthetic_flags.eq(synthetic_rows).all():
        raise ValueError("status=synthetic and is_synthetic must agree")
    if synthetic_rows.any() and (~synthetic_rows).any():
        raise ValueError("observed and synthetic demand labels cannot be mixed in one training run")
    if synthetic_rows.any() and not allow_synthetic:
        raise ValueError("synthetic labels require explicit allow_synthetic=True")

    result["value"] = pd.to_numeric(result["value"], errors="coerce")
    values = result["value"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("demand labels must be finite and non-negative")
    for column in BASE_FEATURE_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        values = result[column].to_numpy(dtype=float, na_value=np.nan)
        if np.isinf(values).any():
            raise ValueError(f"feature {column} contains infinity")
        if column in {"home_charging_share", "nearby_station_uptime"}:
            known = values[np.isfinite(values)]
            if (known < 0).any() or (known > 1).any():
                raise ValueError(f"feature {column} must be between 0 and 1")
        elif (values[np.isfinite(values)] < 0).any():
            raise ValueError(f"feature {column} must be non-negative")

    if result.duplicated(["spatial_unit_id", "time_window_start", "target"]).any():
        raise ValueError("duplicate spatial_unit_id/time_window_start/target rows")
    result = result.sort_values(["time_window_start", "spatial_unit_id"]).reset_index(drop=True)
    return result


def _parse_bool(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "1"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0"}:
        return False
    if value in (0, 1):
        return bool(value)
    raise ValueError("is_synthetic must be a boolean")


def add_temporal_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add local cyclic calendar features from the start of the target time window."""
    result = frame.copy()
    local = result["time_window_start"].dt.tz_convert(TIMEZONE)
    dow = local.dt.dayofweek.to_numpy(dtype=float)
    month = local.dt.month.to_numpy(dtype=float) - 1.0
    result["day_of_week_sin"] = np.sin(2.0 * np.pi * dow / 7.0)
    result["day_of_week_cos"] = np.cos(2.0 * np.pi * dow / 7.0)
    result["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    result["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)
    result["is_weekend"] = (dow >= 5).astype(float)
    return result


def make_temporal_spatial_splits(
    frame: pd.DataFrame,
    *,
    validation_start: str | pd.Timestamp,
    test_start: str | pd.Timestamp,
    seed: int = 42,
    spatial_holdout_fraction: float = 0.20,
) -> DatasetSplits:
    """Build leakage-aware temporal and spatial holdouts.

    Temporal rows whose full target window crosses a split boundary are dropped. Spatial test
    groups are held out from all training and validation rows, not sampled by row.
    """
    validation = _aware_timestamp(validation_start, "validation_start")
    test = _aware_timestamp(test_start, "test_start")
    if validation >= test:
        raise ValueError("validation_start must be earlier than test_start")
    if not 0 < spatial_holdout_fraction < 1:
        raise ValueError("spatial_holdout_fraction must be between 0 and 1")
    groups = sorted(frame["spatial_group"].astype(str).unique())
    if len(groups) < 2:
        raise ValueError("at least two spatial groups are required for a spatial holdout")
    holdout_count = max(1, round(len(groups) * spatial_holdout_fraction))
    holdout_count = min(holdout_count, len(groups) - 1)
    held_out = tuple(
        sorted(groups, key=lambda group: sha256(f"{seed}:{group}".encode()).hexdigest())[
            :holdout_count
        ]
    )

    start = frame["time_window_start"]
    end = frame["time_window_end"]
    is_spatial_test = frame["spatial_group"].astype(str).isin(held_out)
    train_mask = (~is_spatial_test) & (end <= validation)
    validation_mask = (~is_spatial_test) & (start >= validation) & (end <= test)
    temporal_test_mask = (~is_spatial_test) & (start >= test)
    spatial_test_mask = is_spatial_test
    splits = DatasetSplits(
        train=frame.loc[train_mask].copy(),
        validation=frame.loc[validation_mask].copy(),
        temporal_test=frame.loc[temporal_test_mask].copy(),
        spatial_test=frame.loc[spatial_test_mask].copy(),
        spatial_holdout_groups=held_out,
    )
    for name in ("train", "validation", "temporal_test", "spatial_test"):
        if getattr(splits, name).empty:
            raise ValueError(f"{name} split is empty; adjust data coverage or split dates")
    if set(splits.train["spatial_group"]) & set(splits.spatial_test["spatial_group"]):
        raise ValueError("spatial holdout groups leaked into training")
    return splits


def generate_synthetic_dataset(
    *,
    seed: int = 20261013,
    spatial_units: int = 40,
    days: int = 270,
    start_date: str = "2025-01-01",
    target: str = "charging_sessions",
) -> pd.DataFrame:
    """Create deterministic synthetic labels solely to exercise the M2A pipeline."""
    if target not in TARGET_UNITS:
        raise ValueError(f"unsupported demand target: {target}")
    if spatial_units < 10 or days < 30:
        raise ValueError("synthetic demo needs at least 10 spatial units and 30 days")
    rng = np.random.default_rng(seed)
    unit_features = {
        "poi_sustenance_count": rng.integers(1, 160, spatial_units),
        "poi_retail_count": rng.integers(1, 140, spatial_units),
        "poi_education_count": rng.integers(1, 75, spatial_units),
        "poi_healthcare_count": rng.integers(0, 45, spatial_units),
        "poi_transit_count": rng.integers(0, 60, spatial_units),
        "population_density_per_km2": rng.uniform(1500, 28000, spatial_units),
        "building_density_per_km2": rng.uniform(300, 8500, spatial_units),
        "road_traffic_index": rng.uniform(0.05, 1.0, spatial_units),
        "road_accessibility_index": rng.uniform(0.1, 1.0, spatial_units),
        "fleet_activity_index": rng.uniform(0.0, 1.0, spatial_units),
        "home_charging_share": rng.uniform(0.05, 0.75, spatial_units),
        "nearby_compatible_ports": rng.integers(0, 30, spatial_units),
        "nearby_station_uptime": rng.uniform(0.55, 1.0, spatial_units),
        "charger_power_kw": rng.choice([7.4, 11.0, 60.0, 120.0], spatial_units),
    }
    timestamps = pd.date_range(start_date, periods=days, freq="D", tz=TIMEZONE)
    rows: list[dict[str, object]] = []
    for index in range(spatial_units):
        poi = (
            0.025 * unit_features["poi_sustenance_count"][index]
            + 0.030 * unit_features["poi_retail_count"][index]
            + 0.020 * unit_features["poi_education_count"][index]
            + 0.040 * unit_features["poi_healthcare_count"][index]
            + 0.035 * unit_features["poi_transit_count"][index]
        )
        base = (
            2.0
            + poi
            + 8.0 * unit_features["road_traffic_index"][index]
            + 7.0 * unit_features["fleet_activity_index"][index]
            + 0.00025 * unit_features["population_density_per_km2"][index]
        )
        base *= 1.0 - 0.45 * unit_features["home_charging_share"][index]
        for timestamp in timestamps:
            local_day = timestamp.dayofweek
            season = 1.0 + 0.12 * np.sin(2.0 * np.pi * timestamp.dayofyear / 365.25)
            weekend = 0.90 if local_day >= 5 else 1.0
            sessions = max(0.0, base * season * weekend + rng.normal(0.0, max(0.3, base * 0.08)))
            value = (
                sessions if target == "charging_sessions" else sessions * rng.uniform(16.0, 27.0)
            )
            row: dict[str, object] = {
                "spatial_unit_id": f"cell-{index:03d}",
                "spatial_group": f"corridor-{index % 8:02d}",
                "time_window_start": timestamp.isoformat(),
                "time_window_end": (timestamp + pd.Timedelta(days=1)).isoformat(),
                "target": target,
                "value": round(float(value), 5),
                "unit": TARGET_UNITS[target],
                "status": "synthetic",
                "source_id": "m2a-synthetic-generator-v1",
                "data_snapshot_id": f"synthetic-demand-{seed}-v1",
                "is_synthetic": True,
            }
            row.update(
                {
                    name: values[index].item() if hasattr(values[index], "item") else values[index]
                    for name, values in unit_features.items()
                }
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=list(REQUIRED_COLUMNS))


def feature_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ordered numeric model inputs, preserving NaN for XGBoost's missing-value path."""
    enriched = add_temporal_features(frame)
    matrix = enriched.loc[:, list(FEATURE_COLUMNS)].astype("float32")
    values = matrix.to_numpy(dtype=np.float32)
    if np.isinf(values).any():
        raise ValueError("feature matrix contains infinity")
    for column in BASE_FEATURE_COLUMNS:
        known = matrix[column].dropna().to_numpy(dtype=float)
        if column in {"home_charging_share", "nearby_station_uptime"}:
            if (known < 0).any() or (known > 1).any():
                raise ValueError(f"feature {column} must be between 0 and 1")
        elif (known < 0).any():
            raise ValueError(f"feature {column} must be non-negative")
    return matrix
