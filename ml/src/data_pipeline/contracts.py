"""Canonical table contracts used before feature engineering.

The contracts use portable pandas validation rather than a vendor SDK so a
new source needs only an adapter.  All timestamps are normalized to UTC in the
stored canonical datasets; source-local timestamps must be converted by the
adapter before reaching this layer.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

CANONICAL_OCCUPANCY_COLUMNS = (
    "observed_at",
    "received_at",
    "station_id",
    "occupied_ports",
    "available_ports",
    "offline_ports",
    "total_ports",
    "occupancy_ratio",
    "source",
    "schema_version",
    "quality_flag",
    "is_backfilled",
)

CANONICAL_SESSION_COLUMNS = (
    "session_id",
    "station_id",
    "port_id",
    "connector_type",
    "connection_at",
    "done_charging_at",
    "disconnect_at",
    "final_energy_delivered_kwh",
    "source",
    "schema_version",
    "quality_flag",
    "is_censored",
    "censoring_at",
)

CANONICAL_TELEMETRY_COLUMNS = (
    "session_id",
    "station_id",
    "port_id",
    "observed_at",
    "received_at",
    "energy_delivered_kwh",
    "current_power_kw",
    "source",
    "schema_version",
    "quality_flag",
    "is_backfilled",
)

CANONICAL_PORT_STATUS_COLUMNS = (
    "observed_at",
    "received_at",
    "station_id",
    "port_id",
    "connector_type",
    "state",
    "event_id",
    "event_sequence",
    "source",
    "schema_version",
    "quality_flag",
    "is_backfilled",
)

VALID_PORT_STATES = {
    "available",
    "charging",
    "reserved",
    "faulted",
    "offline",
    "maintenance",
}


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} misses canonical columns: {sorted(missing)}")


def _utc(frame: pd.DataFrame, columns: Iterable[str], label: str) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result:
            continue
        values = pd.to_datetime(result[column], utc=True, errors="coerce")
        invalid = result[column].notna() & values.isna()
        if invalid.any():
            raise ValueError(f"{label}.{column} has invalid timestamps")
        result[column] = values
    return result


def validate_occupancy(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate station-level snapshots without manufacturing missing capacity."""
    _require_columns(frame, CANONICAL_OCCUPANCY_COLUMNS, "occupancy")
    result = _utc(frame, ("observed_at", "received_at"), "occupancy")
    if result[["observed_at", "received_at", "station_id"]].isna().any().any():
        raise ValueError("occupancy has null key/timestamp fields")
    if result.duplicated(["station_id", "observed_at"]).any():
        raise ValueError("occupancy has duplicate station snapshots")
    counts = result[["occupied_ports", "available_ports", "offline_ports", "total_ports"]]
    if counts.isna().any().any() or (counts < 0).any().any():
        raise ValueError("occupancy port counts must be present and non-negative")
    if not (
        result["occupied_ports"] + result["available_ports"] + result["offline_ports"]
        == result["total_ports"]
    ).all():
        raise ValueError("occupancy port counts must sum to total_ports")
    expected = result["occupied_ports"] / result["total_ports"].where(result["total_ports"] > 0)
    if not result["occupancy_ratio"].fillna(expected).between(0, 1).all():
        raise ValueError("occupancy_ratio must be in [0, 1] when capacity is positive")
    return result.sort_values(["station_id", "observed_at"]).reset_index(drop=True)


def validate_sessions(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate lifecycle labels; disconnect is the physical port-release event."""
    _require_columns(frame, CANONICAL_SESSION_COLUMNS, "sessions")
    result = _utc(
        frame,
        ("connection_at", "done_charging_at", "disconnect_at", "censoring_at"),
        "sessions",
    )
    if result[["session_id", "station_id", "port_id", "connection_at"]].isna().any().any():
        raise ValueError("sessions has null identity or connection_at")
    if result["session_id"].duplicated().any():
        raise ValueError("sessions has duplicate session_id")
    if result["is_censored"].isna().any():
        raise ValueError("sessions.is_censored must be explicit")
    censored = result["is_censored"].astype(bool)
    if result.loc[~censored, "disconnect_at"].isna().any():
        raise ValueError("uncensored sessions require disconnect_at")
    if result.loc[censored, "censoring_at"].isna().any():
        raise ValueError("censored sessions require censoring_at")
    end_at = result["disconnect_at"].where(~censored, result["censoring_at"])
    if (end_at < result["connection_at"]).any():
        raise ValueError("session end/censoring timestamp cannot precede connection_at")
    if (
        result["done_charging_at"].notna().any()
        and (
            result.loc[result["done_charging_at"].notna(), "done_charging_at"]
            < result.loc[result["done_charging_at"].notna(), "connection_at"]
        ).any()
    ):
        raise ValueError("done_charging_at cannot precede connection_at")
    return result.sort_values("connection_at").reset_index(drop=True)


def validate_telemetry(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CANONICAL_TELEMETRY_COLUMNS, "telemetry")
    result = _utc(frame, ("observed_at", "received_at"), "telemetry")
    if result[["session_id", "station_id", "port_id", "observed_at"]].isna().any().any():
        raise ValueError("telemetry has null identity or observed_at")
    if result.duplicated(["session_id", "observed_at"]).any():
        raise ValueError("telemetry has duplicate session observations")
    numeric = result[["energy_delivered_kwh", "current_power_kw"]]
    if numeric.isna().any().any() or (numeric < 0).any().any():
        raise ValueError("telemetry energy and power must be present and non-negative")
    return result.sort_values(["session_id", "observed_at"]).reset_index(drop=True)


def validate_port_status(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CANONICAL_PORT_STATUS_COLUMNS, "port status")
    result = _utc(frame, ("observed_at", "received_at"), "port status")
    if result[["station_id", "port_id", "connector_type", "observed_at"]].isna().any().any():
        raise ValueError("port status has null identity or observed_at")
    if not result["state"].isin(VALID_PORT_STATES).all():
        raise ValueError("port status contains an unsupported state")
    if result.duplicated(["station_id", "port_id", "observed_at"]).any():
        raise ValueError("port status has duplicate port snapshots")
    return result.sort_values(["station_id", "port_id", "observed_at"]).reset_index(drop=True)
