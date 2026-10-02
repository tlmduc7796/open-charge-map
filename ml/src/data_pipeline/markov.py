"""Create connector-aware aggregate states for the future Markov fallback."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .contracts import validate_port_status
from .manifests import write_dataset_manifest
from .splits import TemporalSplitConfig, assign_temporal_split


def build_markov_state_dataset(
    port_status_path: Path,
    output_path: Path,
    *,
    split_config: TemporalSplitConfig,
) -> dict[str, object]:
    """Aggregate full port snapshots without collapsing incompatible connectors."""
    events = validate_port_status(pd.read_parquet(port_status_path))
    grouped = events.groupby(["station_id", "connector_type", "observed_at"], as_index=False)
    result = grouped.agg(
        compatible_ports=("port_id", "nunique"),
        available_ports=("state", lambda states: int((states == "available").sum())),
        busy_ports=("state", lambda states: int(states.isin(["charging", "reserved"]).sum())),
        unavailable_ports=(
            "state",
            lambda states: int(states.isin(["faulted", "offline", "maintenance"]).sum()),
        ),
    )
    result["is_full"] = result["available_ports"] == 0
    result = assign_temporal_split(result, split_config, timestamp_column="observed_at")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    manifest_path = write_dataset_manifest(
        output_path,
        result,
        dataset_kind="connector_aware_markov_states",
        source_paths=[port_status_path],
        extra={
            "state_definition": (
                "available/busy/unavailable counts per station, connector, timestamp"
            ),
            "not_for_precise_des": True,
        },
    )
    return {
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "records": int(len(result)),
    }
