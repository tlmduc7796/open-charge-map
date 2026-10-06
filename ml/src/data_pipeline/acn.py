"""ACN-Data raw-export normalization, including nested charging-current series."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from .contracts import validate_sessions, validate_telemetry


def _raw_items(paths: Iterable[Path]) -> list[dict]:
    """Read one or more immutable ACN raw exports and de-duplicate by source ID."""
    items: dict[str, dict] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("_items")
        if not isinstance(records, list):
            raise ValueError(f"ACN export {path} does not contain an _items list")
        for record in records:
            identifier = str(record.get("_id") or record.get("sessionID") or "")
            if not identifier:
                raise ValueError(f"ACN export {path} has a session without _id/sessionID")
            if identifier in items and items[identifier] != record:
                raise ValueError(f"Conflicting duplicate ACN session {identifier}")
            items[identifier] = record
    return list(items.values())


def _timestamps(values: object) -> pd.Series:
    result = pd.Series(pd.to_datetime(values, utc=True, errors="coerce"))
    if result.isna().any():
        raise ValueError("ACN export contains invalid timestamps")
    return result


def _field(frame: pd.DataFrame, name: str) -> pd.Series:
    return frame.get(name, pd.Series(pd.NA, index=frame.index))


def normalize_acn_raw_sessions(items: list[dict]) -> pd.DataFrame:
    """Map ACN raw records to canonical lifecycle rows without inventing fields."""
    frame = pd.DataFrame(items)
    if frame.empty:
        raise ValueError("ACN export contains no sessions")
    connection = _timestamps(frame["connectionTime"])
    disconnect = pd.to_datetime(frame.get("disconnectTime"), utc=True, errors="coerce")
    done = pd.to_datetime(frame.get("doneChargingTime"), utc=True, errors="coerce")
    censored = disconnect.isna()
    censoring = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    censoring.loc[censored] = connection.loc[censored]
    sessions = pd.DataFrame(
        {
            "session_id": _field(frame, "_id").fillna(_field(frame, "sessionID")).astype("string"),
            "station_id": _field(frame, "siteID").fillna("ACN_UNKNOWN").astype("string"),
            "port_id": _field(frame, "stationID").fillna(_field(frame, "spaceID")).astype("string"),
            "connector_type": "ACN_L2_UNKNOWN",
            "connection_at": connection,
            "done_charging_at": done,
            "disconnect_at": disconnect,
            "final_energy_delivered_kwh": pd.to_numeric(frame.get("kWhDelivered"), errors="coerce"),
            "source": "acn_data",
            "schema_version": "acn-raw-timeseries-1",
            "quality_flag": "historical_backfill",
            "is_censored": censored,
            "censoring_at": censoring,
        }
    )
    sessions.loc[censored, "quality_flag"] = "censored_missing_disconnect"
    return validate_sessions(sessions)


def _telemetry_rows(item: dict, *, voltage_v: float, cadence: str) -> list[dict]:
    current = item.get("chargingCurrent")
    if not isinstance(current, dict):
        return []
    timestamps, amps = current.get("timestamps"), current.get("current")
    if (
        not isinstance(timestamps, list)
        or not isinstance(amps, list)
        or len(timestamps) != len(amps)
    ):
        return []
    frame = pd.DataFrame({"observed_at": _timestamps(timestamps), "current_a": amps})
    frame["current_a"] = pd.to_numeric(frame["current_a"], errors="coerce")
    frame = frame.dropna().sort_values("observed_at").drop_duplicates("observed_at", keep="last")
    if frame.empty:
        return []
    frame["current_power_kw"] = frame["current_a"].clip(lower=0) * voltage_v / 1000
    hours = frame["observed_at"].diff().dt.total_seconds().fillna(0).clip(lower=0) / 3600
    frame["energy_delivered_kwh"] = (
        ((frame["current_power_kw"] + frame["current_power_kw"].shift(fill_value=0)) / 2 * hours)
        .cumsum()
    )
    connection = _timestamps([item["connectionTime"]]).iloc[0]
    disconnect = pd.to_datetime(item.get("disconnectTime"), utc=True, errors="coerce")
    if pd.isna(disconnect):
        return []
    frame = frame.loc[(frame["observed_at"] >= connection) & (frame["observed_at"] < disconnect)]
    if frame.empty:
        return []
    sampled = (
        frame.set_index("observed_at")[["energy_delivered_kwh", "current_power_kw"]]
        .resample(cadence)
        .agg({"energy_delivered_kwh": "last", "current_power_kw": "mean"})
        .dropna()
        .reset_index()
    )
    identifier = str(item.get("_id") or item.get("sessionID"))
    return [
        {
            "session_id": identifier,
            "station_id": str(item.get("siteID") or "ACN_UNKNOWN"),
            "port_id": str(item.get("stationID") or item.get("spaceID") or "UNKNOWN_PORT"),
            "observed_at": row.observed_at,
            "received_at": row.observed_at,
            "energy_delivered_kwh": row.energy_delivered_kwh,
            "current_power_kw": row.current_power_kw,
            "source": "acn_data",
            "schema_version": "acn-raw-timeseries-1",
            "quality_flag": f"historical_backfill_power_estimated_{int(voltage_v)}v",
            "is_backfilled": True,
        }
        for row in sampled.itertuples(index=False)
    ]


def normalize_acn_raw_timeseries(
    paths: Iterable[Path], *, voltage_v: float = 208.0, cadence: str = "5min"
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Return canonical sessions, 5-minute telemetry, and source-quality counts.

    ACN current is converted to estimated kW using the declared nominal voltage.
    The estimate is labelled in ``quality_flag`` and is never represented as an
    operator-measured power value.
    """
    if voltage_v <= 0:
        raise ValueError("voltage_v must be positive")
    items = _raw_items(paths)
    sessions = normalize_acn_raw_sessions(items)
    rows = [
        row
        for item in items
        for row in _telemetry_rows(item, voltage_v=voltage_v, cadence=cadence)
    ]
    if not rows:
        raise ValueError("No usable chargingCurrent telemetry in the supplied ACN exports")
    telemetry = validate_telemetry(pd.DataFrame(rows))
    summary = {
        "source_sessions": len(items),
        "sessions_with_telemetry": int(telemetry["session_id"].nunique()),
        "telemetry_rows": len(telemetry),
        "censored_sessions": int(sessions["is_censored"].sum()),
    }
    return sessions, telemetry, summary
