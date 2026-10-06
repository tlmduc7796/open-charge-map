"""Build leakage-safe remaining-port-release (RDM) datasets from sessions."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .contracts import validate_sessions, validate_telemetry
from .manifests import write_dataset_manifest
from .splits import TemporalSplitConfig, assign_session_temporal_split

RDM_FEATURE_COLUMNS = (
    "session_elapsed_min",
    "energy_delivered_kwh",
    "current_power_kw",
    "station_id",
    "port_id",
    "connector_type",
)
RDM_LIVE_SAFE_FEATURE_COLUMNS = (
    *RDM_FEATURE_COLUMNS,
    "port_max_power_kw",
    "observation_hour_local",
    "observation_weekday_local",
    "is_drawing_power",
)
RDM_TARGET_COLUMN = "remaining_port_release_min"


def build_rdm_dataset(
    sessions_path: Path,
    telemetry_path: Path,
    output_path: Path,
    *,
    split_config: TemporalSplitConfig,
) -> dict[str, object]:
    """Generate one supervised row per observed live-session telemetry point.

    ``final_energy_delivered_kwh`` is retained in the session source for audit
    only and is never joined into the model feature matrix: it is unknowable
    before the session finishes.  The label is always ``disconnect_at -
    observed_at``; done_charging_at is deliberately not a substitute.
    """
    sessions = validate_sessions(pd.read_parquet(sessions_path))
    telemetry = validate_telemetry(pd.read_parquet(telemetry_path))
    session_split, observations = assign_session_temporal_split(sessions, telemetry, split_config)
    labels = session_split.loc[
        ~session_split["is_censored"].astype(bool),
        [
            "session_id",
            "station_id",
            "port_id",
            "connector_type",
            "connection_at",
            "disconnect_at",
            "split",
        ],
    ]
    result = observations.merge(
        labels, on=["session_id", "station_id", "port_id", "split"], how="inner"
    )
    result = result.loc[
        (result["observed_at"] >= result["connection_at"])
        & (result["observed_at"] < result["disconnect_at"])
    ].copy()
    result["session_elapsed_min"] = (
        result["observed_at"] - result["connection_at"]
    ).dt.total_seconds() / 60
    result[RDM_TARGET_COLUMN] = (
        result["disconnect_at"] - result["observed_at"]
    ).dt.total_seconds() / 60
    required = [*RDM_FEATURE_COLUMNS, RDM_TARGET_COLUMN, "split", "session_id", "observed_at"]
    result = result.dropna(subset=required).copy()
    if result.empty:
        raise ValueError("No trainable RDM observations after lifecycle and null filtering")
    if (result[RDM_TARGET_COLUMN] <= 0).any():
        raise ValueError("RDM target must be strictly positive before port release")
    session_membership = result.groupby("session_id")["split"].nunique()
    if (session_membership != 1).any():
        raise ValueError("RDM split leakage: one session appears in multiple splits")
    if not {"train", "val", "test"}.issubset(set(result["split"])):
        raise ValueError("RDM dataset needs train, val and test sessions")
    keep = [
        "session_id",
        "observed_at",
        "split",
        *RDM_FEATURE_COLUMNS,
        RDM_TARGET_COLUMN,
        "disconnect_at",
        "source",
        "schema_version",
        "quality_flag",
    ]
    output = result.loc[:, keep].sort_values(["session_id", "observed_at"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False)
    manifest_path = write_dataset_manifest(
        output_path,
        output,
        dataset_kind="rdm_session_observations",
        source_paths=[sessions_path, telemetry_path],
        extra={
            "target": RDM_TARGET_COLUMN,
            "target_semantics": "disconnect_at - observed_at; physical port release",
            "excluded": "censored sessions and observations at/after disconnect",
            "split_policy": "all rows of each session assigned by disconnect_at",
            "feature_columns": list(RDM_FEATURE_COLUMNS),
        },
    )
    return {
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "records": int(len(output)),
        "sessions": int(output["session_id"].nunique()),
    }


def _read_port_inventory(path: Path) -> pd.DataFrame:
    """Read the minimum static port facts required by the live-safe profile."""
    if path.suffix.lower() == ".parquet":
        inventory = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        inventory = pd.read_csv(path)
    else:
        raise ValueError("Port inventory must be a CSV or Parquet file")
    aliases = {
        "stationID": "station_id",
        "portID": "port_id",
        "EVSEID": "port_id",
        "maxPowerKw": "max_power_kw",
        "max_power": "max_power_kw",
    }
    rename_columns = {old: new for old, new in aliases.items() if old in inventory}
    inventory = inventory.rename(columns=rename_columns)
    required = {"station_id", "port_id", "max_power_kw"}
    if missing := required - set(inventory):
        raise ValueError(f"Port inventory misses columns: {sorted(missing)}")
    result = inventory.loc[:, ["station_id", "port_id", "max_power_kw"]].copy()
    result["station_id"] = result["station_id"].astype("string")
    result["port_id"] = result["port_id"].astype("string")
    result["max_power_kw"] = pd.to_numeric(result["max_power_kw"], errors="coerce")
    if result.isna().any().any() or (result["max_power_kw"] <= 0).any():
        raise ValueError("Port inventory requires a positive max_power_kw for every port")
    if result.duplicated(["station_id", "port_id"]).any():
        raise ValueError("Port inventory has duplicate station_id/port_id rows")
    return result


def build_live_safe_rdm_dataset(
    sessions_path: Path,
    telemetry_path: Path,
    port_inventory_path: Path,
    output_path: Path,
    *,
    split_config: TemporalSplitConfig,
    local_timezone: str = "Asia/Ho_Chi_Minh",
) -> dict[str, object]:
    """Build an RDM dataset using only telemetry/inventory facts observable live.

    Unlike the old six-column RDM contract, this profile joins static port
    capacity and derives local clock plus drawing-power state at observation
    time. It never joins final session fields such as disconnect, final energy
    or idle duration as features.
    """
    build_rdm_dataset(
        sessions_path, telemetry_path, output_path, split_config=split_config
    )
    result = pd.read_parquet(output_path)
    inventory = _read_port_inventory(port_inventory_path)
    result = result.merge(
        inventory,
        on=["station_id", "port_id"],
        how="left",
        validate="many_to_one",
    )
    if result["max_power_kw"].isna().any():
        unknown = result.loc[result["max_power_kw"].isna(), "port_id"].unique().tolist()
        raise ValueError(f"RDM observations reference ports absent from inventory: {unknown}")
    local_observed_at = result["observed_at"].dt.tz_convert(local_timezone)
    result["port_max_power_kw"] = result.pop("max_power_kw")
    result["observation_hour_local"] = local_observed_at.dt.hour.astype("int8")
    result["observation_weekday_local"] = local_observed_at.dt.weekday.astype("int8")
    # This is a meter fact, not a claim that the vehicle has physically unplugged.
    result["is_drawing_power"] = (result["current_power_kw"] > 0).astype("int8")
    result.to_parquet(output_path, index=False)
    manifest_path = write_dataset_manifest(
        output_path,
        result,
        dataset_kind="rdm_live_safe_session_observations",
        source_paths=[sessions_path, telemetry_path, port_inventory_path],
        extra={
            "target": RDM_TARGET_COLUMN,
            "target_semantics": "disconnect_at - observed_at; physical port release",
            "feature_columns": list(RDM_LIVE_SAFE_FEATURE_COLUMNS),
            "local_timezone": local_timezone,
            "prohibited_future_features": [
                "disconnect_at",
                "done_charging_at",
                "final_energy_delivered_kwh",
                "idle_min",
            ],
        },
    )
    return {
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "records": int(len(result)),
        "sessions": int(result["session_id"].nunique()),
        "feature_columns": list(RDM_LIVE_SAFE_FEATURE_COLUMNS),
    }
