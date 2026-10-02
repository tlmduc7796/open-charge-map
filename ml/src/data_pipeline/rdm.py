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
