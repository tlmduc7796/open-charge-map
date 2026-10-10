"""Validate and seed planned-arrival runtime fixtures into PostgreSQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

PLANNED_ARRIVALS_SOURCE_REF = "data/runtime/planned_arrivals.json"
QUEUE_ASSUMPTIONS_SOURCE_REF = "data/demo/queue_assumptions.json"
PLANNED_ARRIVAL_STATUSES = {"planned", "arrived", "cancelled", "expired"}
PLANNED_ARRIVAL_SOURCES = {"runtime", "synthetic"}


@dataclass(frozen=True)
class RuntimeSeedBundle:
    planned_arrivals: tuple[dict[str, Any], ...]
    station_rates: tuple[dict[str, Any], ...]
    planned_arrival_window_min: int


def _number(value: Any, field: str, *, minimum: float, inclusive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if result < minimum or (not inclusive and result == minimum):
        qualifier = "at least" if inclusive else "greater than"
        raise ValueError(f"{field} must be {qualifier} {minimum}")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def build_runtime_seed(
    planned_arrivals: Any, queue_assumptions: Any
) -> RuntimeSeedBundle:
    if not isinstance(planned_arrivals, list):
        raise ValueError("planned arrivals must be an array")
    if not isinstance(queue_assumptions, dict):
        raise ValueError("queue assumptions must be an object")

    normalized_arrivals: list[dict[str, Any]] = []
    arrival_ids: set[str] = set()
    for index, raw in enumerate(planned_arrivals):
        if not isinstance(raw, dict):
            raise ValueError(f"planned_arrivals[{index}] must be an object")
        prefix = f"planned_arrivals[{index}]"
        arrival_id = _nonempty(raw.get("arrival_id"), f"{prefix}.arrival_id")
        if arrival_id in arrival_ids:
            raise ValueError(f"duplicate planned arrival: {arrival_id}")
        arrival_ids.add(arrival_id)

        created_at = _timestamp(raw.get("created_at"), f"{prefix}.created_at")
        eta_at = _timestamp(raw.get("eta_at"), f"{prefix}.eta_at")
        eta_window_start = _timestamp(
            raw.get("eta_window_start"), f"{prefix}.eta_window_start"
        )
        eta_window_end = _timestamp(
            raw.get("eta_window_end"), f"{prefix}.eta_window_end"
        )
        expires_at = _timestamp(raw.get("expires_at"), f"{prefix}.expires_at")
        if not eta_window_start <= eta_at <= eta_window_end:
            raise ValueError(f"{arrival_id}.eta_at must be inside its ETA window")
        if expires_at <= created_at:
            raise ValueError(f"{arrival_id}.expires_at must be after created_at")

        probability = _number(
            raw.get("arrival_probability"),
            f"{prefix}.arrival_probability",
            minimum=0,
        )
        if probability > 1:
            raise ValueError(f"{arrival_id}.arrival_probability must be at most 1")
        status = _nonempty(raw.get("status"), f"{prefix}.status")
        if status not in PLANNED_ARRIVAL_STATUSES:
            raise ValueError(f"unsupported planned arrival status: {status}")
        data_source = _nonempty(raw.get("data_source"), f"{prefix}.data_source")
        if data_source not in PLANNED_ARRIVAL_SOURCES:
            raise ValueError(f"unsupported planned arrival data_source: {data_source}")

        vehicle_id = raw.get("vehicle_id")
        route_id = raw.get("route_id")
        normalized_arrivals.append(
            {
                "arrival_id": arrival_id,
                "station_code": _nonempty(raw.get("station_id"), f"{prefix}.station_id"),
                "vehicle_code": (
                    _nonempty(vehicle_id, f"{prefix}.vehicle_id")
                    if vehicle_id is not None
                    else None
                ),
                "route_id": (
                    _nonempty(route_id, f"{prefix}.route_id")
                    if route_id is not None
                    else None
                ),
                "created_at": created_at,
                "eta_at": eta_at,
                "eta_window_start": eta_window_start,
                "eta_window_end": eta_window_end,
                "expected_energy_kwh": _number(
                    raw.get("expected_energy_kwh"),
                    f"{prefix}.expected_energy_kwh",
                    minimum=0,
                ),
                "expected_charge_duration_min": _number(
                    raw.get("expected_charge_duration_min"),
                    f"{prefix}.expected_charge_duration_min",
                    minimum=0,
                    inclusive=False,
                ),
                "arrival_probability": probability,
                "expires_at": expires_at,
                "status": status,
                "data_source": data_source,
            }
        )

    window_min = queue_assumptions.get("planned_arrival_window_min")
    if isinstance(window_min, bool) or not isinstance(window_min, int) or window_min <= 0:
        raise ValueError("planned_arrival_window_min must be a positive integer")
    if queue_assumptions.get("data_source") != "synthetic":
        raise ValueError("queue assumptions data_source must be synthetic")
    raw_rates = queue_assumptions.get("station_rates")
    if not isinstance(raw_rates, list) or not raw_rates:
        raise ValueError("queue assumptions station_rates must be a non-empty array")

    station_rates: list[dict[str, Any]] = []
    rate_station_codes: set[str] = set()
    for index, raw in enumerate(raw_rates):
        if not isinstance(raw, dict):
            raise ValueError(f"station_rates[{index}] must be an object")
        station_code = _nonempty(raw.get("station_id"), f"station_rates[{index}].station_id")
        if station_code in rate_station_codes:
            raise ValueError(f"duplicate station arrival rate: {station_code}")
        rate_station_codes.add(station_code)
        station_rates.append(
            {
                "station_code": station_code,
                "baseline_arrival_rate_per_hour": _number(
                    raw.get("baseline_arrival_rate_per_hour"),
                    f"station_rates[{index}].baseline_arrival_rate_per_hour",
                    minimum=0,
                ),
            }
        )

    return RuntimeSeedBundle(
        tuple(normalized_arrivals), tuple(station_rates), window_min
    )


def load_runtime_seed(
    planned_arrivals_path: Path, queue_assumptions_path: Path
) -> RuntimeSeedBundle:
    return build_runtime_seed(
        json.loads(planned_arrivals_path.read_text(encoding="utf-8")),
        json.loads(queue_assumptions_path.read_text(encoding="utf-8")),
    )


def seed_runtime_data(
    engine: Engine,
    planned_arrivals_path: Path,
    queue_assumptions_path: Path,
) -> dict[str, int]:
    bundle = load_runtime_seed(planned_arrivals_path, queue_assumptions_path)
    with engine.begin() as connection:
        station_lookup = {
            row.code: row.id
            for row in connection.execute(text("SELECT id, code FROM stations")).all()
        }
        vehicle_lookup: dict[str, Any] = {}
        for row in connection.execute(
            text("SELECT id, code, provenance FROM vehicle_models")
        ).mappings():
            vehicle_lookup[row["code"]] = row["id"]
            legacy_id = (row["provenance"] or {}).get("_legacy_demo", {}).get("vehicle_id")
            if legacy_id:
                if legacy_id in vehicle_lookup and vehicle_lookup[legacy_id] != row["id"]:
                    raise ValueError(f"ambiguous legacy vehicle reference: {legacy_id}")
                vehicle_lookup[legacy_id] = row["id"]

        referenced_stations = {
            arrival["station_code"] for arrival in bundle.planned_arrivals
        } | {rate["station_code"] for rate in bundle.station_rates}
        missing_stations = sorted(referenced_stations - station_lookup.keys())
        if missing_stations:
            raise ValueError(f"unknown station references: {missing_stations}")
        missing_vehicles = sorted(
            {
                arrival["vehicle_code"]
                for arrival in bundle.planned_arrivals
                if arrival["vehicle_code"] is not None
            }
            - vehicle_lookup.keys()
        )
        if missing_vehicles:
            raise ValueError(f"unknown vehicle references: {missing_vehicles}")

        for rate in bundle.station_rates:
            connection.execute(
                text(
                    "INSERT INTO station_arrival_rates "
                    "(station_id, baseline_arrival_rate_per_hour, data_source, provenance) "
                    "VALUES (:station_id, :rate, 'synthetic', CAST(:provenance AS jsonb)) "
                    "ON CONFLICT (station_id) DO UPDATE SET "
                    "baseline_arrival_rate_per_hour=EXCLUDED.baseline_arrival_rate_per_hour, "
                    "data_source=EXCLUDED.data_source, provenance=EXCLUDED.provenance"
                ),
                {
                    "station_id": station_lookup[rate["station_code"]],
                    "rate": rate["baseline_arrival_rate_per_hour"],
                    "provenance": json.dumps(
                        {
                            "origin": "synthetic",
                            "provider": "queue_assumptions_fixture",
                            "source_ref": QUEUE_ASSUMPTIONS_SOURCE_REF,
                            "station_code": rate["station_code"],
                        }
                    ),
                },
            )

        for arrival in bundle.planned_arrivals:
            connection.execute(
                text(
                    "INSERT INTO planned_arrivals "
                    "(arrival_id, station_id, vehicle_model_id, route_id, created_at, eta_at, "
                    "eta_window_start, eta_window_end, expected_energy_kwh, "
                    "expected_charge_duration_min, arrival_probability, expires_at, status, "
                    "data_source, provenance) VALUES "
                    "(:arrival_id, :station_id, :vehicle_model_id, :route_id, :created_at, "
                    ":eta_at, :eta_window_start, :eta_window_end, :expected_energy_kwh, "
                    ":expected_charge_duration_min, :arrival_probability, :expires_at, "
                    ":status, :data_source, CAST(:provenance AS jsonb)) "
                    "ON CONFLICT (arrival_id) DO UPDATE SET "
                    "station_id=EXCLUDED.station_id, vehicle_model_id=EXCLUDED.vehicle_model_id, "
                    "route_id=EXCLUDED.route_id, created_at=EXCLUDED.created_at, "
                    "eta_at=EXCLUDED.eta_at, eta_window_start=EXCLUDED.eta_window_start, "
                    "eta_window_end=EXCLUDED.eta_window_end, "
                    "expected_energy_kwh=EXCLUDED.expected_energy_kwh, "
                    "expected_charge_duration_min=EXCLUDED.expected_charge_duration_min, "
                    "arrival_probability=EXCLUDED.arrival_probability, "
                    "expires_at=EXCLUDED.expires_at, status=EXCLUDED.status, "
                    "data_source=EXCLUDED.data_source, provenance=EXCLUDED.provenance "
                    "WHERE planned_arrivals.data_source = 'synthetic'"
                ),
                {
                    **arrival,
                    "station_id": station_lookup[arrival["station_code"]],
                    "vehicle_model_id": (
                        vehicle_lookup[arrival["vehicle_code"]]
                        if arrival["vehicle_code"] is not None
                        else None
                    ),
                    "provenance": json.dumps(
                        {
                            "origin": arrival["data_source"],
                            "provider": "planned_arrivals_fixture",
                            "source_ref": PLANNED_ARRIVALS_SOURCE_REF,
                            "station_code": arrival["station_code"],
                            "vehicle_ref": arrival["vehicle_code"],
                        }
                    ),
                },
            )

        connection.execute(
            text(
                "INSERT INTO app_config (key, value) "
                "VALUES ('planned_arrival_window_min', CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()"
            ),
            {"value": json.dumps(bundle.planned_arrival_window_min)},
        )

    return {
        "planned_arrivals": len(bundle.planned_arrivals),
        "station_arrival_rates": len(bundle.station_rates),
        "app_config": 1,
    }
