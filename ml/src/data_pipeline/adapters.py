"""Source-specific adapters that emit canonical tables, never model features.

Adding a new vendor means adding a normalizer here (or a sibling adapter), not
forking XGBoost/LSTM/RDM extraction code.  The caller owns raw-file download,
credentials and retention; this module operates on a local export.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .contracts import validate_occupancy, validate_sessions, validate_telemetry


def _read_export(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Source export does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        text = path.read_text(encoding="utf-8")
        payload: Any = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("_items", payload.get("items", payload.get("sessions", payload)))
        if not isinstance(payload, list):
            raise ValueError("JSON export must be a records list or expose _items/items/sessions")
        return pd.json_normalize(payload)
    raise ValueError(f"Unsupported source export extension: {suffix}")


def _column(frame: pd.DataFrame, choices: tuple[str, ...], *, required: bool = True) -> pd.Series:
    for name in choices:
        if name in frame:
            return frame[name]
    if required:
        raise ValueError(f"Source export needs one of: {list(choices)}")
    return pd.Series(pd.NA, index=frame.index)


def _text(frame: pd.DataFrame, choices: tuple[str, ...], default: str | None = None) -> pd.Series:
    value = _column(frame, choices, required=default is None)
    if default is not None:
        value = value.fillna(default)
    return value.astype("string")


def _timestamp(frame: pd.DataFrame, choices: tuple[str, ...]) -> pd.Series:
    values = _column(frame, choices)
    converted = pd.to_datetime(values, utc=True, errors="coerce")
    if converted.isna().any():
        raise ValueError(f"Invalid timestamps in source column choices {list(choices)}")
    return converted


def normalize_occupancy_source(
    frame: pd.DataFrame,
    *,
    source: str,
    schema_version: str = "canonical-1",
    received_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Map an aggregate occupancy export, including UrbanEV, to canonical rows."""
    observed_at = _timestamp(frame, ("observed_at", "timestamp", "time"))
    total_source = _column(frame, ("total_ports", "capacity"), required=False)
    total = pd.to_numeric(total_source, errors="coerce")
    occupied = pd.to_numeric(_column(frame, ("occupied_ports", "busy")), errors="coerce")
    available_source = _column(frame, ("available_ports", "idle"), required=False)
    available = pd.to_numeric(available_source, errors="coerce")
    if available.isna().all():
        available = total - occupied
    offline_source = _column(frame, ("offline_ports",), required=False)
    offline = pd.to_numeric(offline_source, errors="coerce").fillna(0)
    if total.isna().all():
        total = occupied + available + offline
    ratio = occupied / total.where(total > 0)
    if received_at is None:
        received_source = _column(frame, ("received_at", "ingested_at"), required=False)
        observed_received = pd.to_datetime(received_source, utc=True, errors="coerce")
        received = observed_received.fillna(observed_at)
        quality_flag = pd.Series("validated", index=frame.index)
        quality_flag.loc[observed_received.isna()] = "backfilled_received_at_proxy"
    else:
        arrival = pd.Timestamp(received_at)
        if arrival.tzinfo is None:
            raise ValueError("received_at requires an explicit timezone")
        received = pd.Series(arrival.tz_convert("UTC"), index=frame.index)
        quality_flag = pd.Series("validated", index=frame.index)
    result = pd.DataFrame(
        {
            "observed_at": observed_at,
            "received_at": received,
            "station_id": _text(frame, ("station_id", "entity_id", "stationID")),
            "occupied_ports": occupied,
            "available_ports": available,
            "offline_ports": offline,
            "total_ports": total,
            "occupancy_ratio": ratio,
            "source": source,
            "schema_version": schema_version,
            "quality_flag": quality_flag,
            "is_backfilled": True,
        }
    )
    return validate_occupancy(result)


def normalize_urbanev_processed(path: Path) -> pd.DataFrame:
    """Adapter for the existing UrbanEV processed parquet; no model depends on it."""
    return normalize_occupancy_source(_read_export(path), source="urbanev")


def normalize_acn_sessions(path: Path, *, default_station_id: str = "ACN_UNKNOWN") -> pd.DataFrame:
    """Normalize an offline ACN-Data session export into lifecycle labels.

    ACN field spelling varies between API/export versions.  This adapter accepts
    official-style ``connectionTime``, ``doneChargingTime``, ``disconnectTime``
    and ``kWhDelivered`` as well as canonical snake-case equivalents.  It does
    not invent a disconnect timestamp: rows without one are marked censored.
    """
    frame = _read_export(path)
    connection_at = _timestamp(frame, ("connectionTime", "connection_at"))
    disconnect_source = _column(frame, ("disconnectTime", "disconnect_at"), required=False)
    disconnect_at = pd.to_datetime(disconnect_source, utc=True, errors="coerce")
    done_source = _column(frame, ("doneChargingTime", "done_charging_at"), required=False)
    done_charging_at = pd.to_datetime(done_source, utc=True, errors="coerce")
    censored = disconnect_at.isna()
    censoring_at = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    # An export timestamp is an acceptable censoring point; otherwise retain
    # the observed connection timestamp so the row remains explicitly censored.
    export_seen = _column(frame, ("received_at", "retrieved_at", "lastUpdate"), required=False)
    parsed_seen = pd.to_datetime(export_seen, utc=True, errors="coerce")
    censoring_at.loc[censored] = parsed_seen.loc[censored].fillna(connection_at.loc[censored])
    result = pd.DataFrame(
        {
            "session_id": _text(frame, ("_id", "sessionID", "session_id")),
            "station_id": _text(
                frame, ("stationID", "station_id", "siteID"), default=default_station_id
            ),
            "port_id": _text(
                frame, ("spaceID", "portID", "port_id", "EVSEID"), default="UNKNOWN_PORT"
            ),
            "connector_type": _text(frame, ("connectorType", "connector_type"), default="UNKNOWN"),
            "connection_at": connection_at,
            "done_charging_at": done_charging_at,
            "disconnect_at": disconnect_at,
            "final_energy_delivered_kwh": pd.to_numeric(
                _column(frame, ("kWhDelivered", "final_energy_delivered_kwh"), required=False),
                errors="coerce",
            ),
            "source": "acn_data",
            "schema_version": "acn-adapter-1",
            "quality_flag": "validated",
            "is_censored": censored,
            "censoring_at": censoring_at,
        }
    )
    # A row-level quality flag makes missing disconnect visible without using
    # it as a numerical feature.  pandas permits the aligned Series assignment.
    result.loc[censored, "quality_flag"] = "censored_missing_disconnect"
    return validate_sessions(result)


def normalize_operator_sessions(path: Path, *, source: str) -> pd.DataFrame:
    """Normalize a real operator lifecycle export without vendor-specific model code.

    This intentionally accepts only a local export. Authentication, OCPP polling
    and retention remain an operator integration concern. Missing disconnects
    are retained as censored observations, never guessed as labels.
    """
    if not source.strip() or "synthetic" in source.lower():
        raise ValueError("operator session source must identify a non-synthetic provider")
    frame = _read_export(path)
    connection_at = _timestamp(frame, ("connection_at", "connectionTime", "plugged_in_at"))
    disconnect_source = _column(
        frame, ("disconnect_at", "disconnectTime", "unplugged_at"), required=False
    )
    disconnect_at = pd.to_datetime(disconnect_source, utc=True, errors="coerce")
    done_source = _column(
        frame, ("done_charging_at", "doneChargingTime", "charging_stopped_at"), required=False
    )
    done_charging_at = pd.to_datetime(done_source, utc=True, errors="coerce")
    censored = disconnect_at.isna()
    export_seen = _column(frame, ("received_at", "retrieved_at", "lastUpdate"), required=False)
    seen_at = pd.to_datetime(export_seen, utc=True, errors="coerce")
    censoring_at = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    censoring_at.loc[censored] = seen_at.loc[censored].fillna(connection_at.loc[censored])
    result = pd.DataFrame(
        {
            "session_id": _text(frame, ("session_id", "sessionID", "_id")),
            "station_id": _text(frame, ("station_id", "stationID", "siteID")),
            "port_id": _text(frame, ("port_id", "portID", "EVSEID", "spaceID")),
            "connector_type": _text(
                frame, ("connector_type", "connectorType"), default="UNKNOWN"
            ),
            "connection_at": connection_at,
            "done_charging_at": done_charging_at,
            "disconnect_at": disconnect_at,
            "final_energy_delivered_kwh": pd.to_numeric(
                _column(
                    frame,
                    ("final_energy_delivered_kwh", "kWhDelivered", "energy_kwh"),
                    required=False,
                ),
                errors="coerce",
            ),
            "source": source,
            "schema_version": "operator-adapter-1",
            "quality_flag": "validated",
            "is_censored": censored,
            "censoring_at": censoring_at,
        }
    )
    result.loc[censored, "quality_flag"] = "censored_missing_disconnect"
    return validate_sessions(result)


def normalize_simulator_sessions(sessions_path: Path, ports_path: Path) -> pd.DataFrame:
    """Normalize simulator output for offline contract and DES evaluation only.

    The simulator's ``t_disconnect`` is deliberately mapped to the canonical
    physical port-release label.  Simulator rows must declare their synthetic
    provenance; this adapter never presents them as operator observations or a
    deployable training source.
    """
    sessions = _read_export(sessions_path)
    ports = _read_export(ports_path)
    required_session_columns = {
        "session_id",
        "station_id",
        "port_id",
        "t_connect",
        "t_charge_end",
        "t_disconnect",
        "energy_kwh",
        "is_synthetic",
    }
    missing = required_session_columns - set(sessions.columns)
    if missing:
        raise ValueError(f"Simulator sessions miss columns: {sorted(missing)}")
    if not sessions["is_synthetic"].astype("string").str.lower().eq("true").all():
        raise ValueError("Simulator adapter accepts only rows explicitly marked is_synthetic=true")
    required_port_columns = {"port_id", "station_id", "connector"}
    missing_ports = required_port_columns - set(ports.columns)
    if missing_ports:
        raise ValueError(f"Simulator ports miss columns: {sorted(missing_ports)}")
    if ports["port_id"].duplicated().any():
        raise ValueError("Simulator ports contain duplicate port_id values")

    connector_by_port = ports.set_index("port_id")["connector"]
    connector = sessions["port_id"].map(connector_by_port)
    if connector.isna().any():
        unknown = sessions.loc[connector.isna(), "port_id"].unique().tolist()
        raise ValueError(f"Simulator sessions reference unknown ports: {unknown}")
    port_station = sessions["port_id"].map(ports.set_index("port_id")["station_id"])
    if not port_station.eq(sessions["station_id"]).all():
        raise ValueError("Simulator session station_id does not match its port")

    connection_at = _timestamp(sessions, ("t_connect",))
    result = pd.DataFrame(
        {
            "session_id": _text(sessions, ("session_id",)),
            "station_id": _text(sessions, ("station_id",)),
            "port_id": _text(sessions, ("port_id",)),
            "connector_type": connector.astype("string"),
            "connection_at": connection_at,
            "done_charging_at": _timestamp(sessions, ("t_charge_end",)),
            "disconnect_at": _timestamp(sessions, ("t_disconnect",)),
            "final_energy_delivered_kwh": pd.to_numeric(sessions["energy_kwh"], errors="coerce"),
            "source": "simulator_hcmc_synthetic",
            "schema_version": "simulator-adapter-1",
            "quality_flag": "synthetic_for_evaluation_only",
            "is_censored": False,
            "censoring_at": pd.Series(pd.NaT, index=sessions.index, dtype="datetime64[ns, UTC]"),
        }
    )
    return validate_sessions(result)


def normalize_session_telemetry(
    path: Path,
    *,
    source: str,
    session_column: str = "session_id",
) -> pd.DataFrame:
    """Normalize a flat telemetry export; nested vendor time series should be flattened upstream."""
    frame = _read_export(path)
    observed_at = _timestamp(frame, ("observed_at", "timestamp", "time"))
    result = pd.DataFrame(
        {
            "session_id": _text(frame, (session_column, "sessionID", "_id")),
            "station_id": _text(frame, ("station_id", "stationID", "siteID")),
            "port_id": _text(frame, ("port_id", "portID", "spaceID", "EVSEID")),
            "observed_at": observed_at,
            "received_at": _timestamp(frame, ("received_at", "retrieved_at", "timestamp", "time")),
            "energy_delivered_kwh": pd.to_numeric(
                _column(frame, ("energy_delivered_kwh", "kwh_delivered_so_far", "energy_kwh")),
                errors="coerce",
            ),
            "current_power_kw": pd.to_numeric(
                _column(frame, ("current_power_kw", "power_kw", "power")), errors="coerce"
            ),
            "source": source,
            "schema_version": "canonical-1",
            "quality_flag": "validated",
            "is_backfilled": True,
        }
    )
    return validate_telemetry(result)
