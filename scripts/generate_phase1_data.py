#!/usr/bin/env python3
"""Generate deterministic synthetic runtime/demo inputs for Phase 1."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "data" / "runtime"
DEMO_DIR = ROOT / "data" / "demo"
STATIONS_PATH = ROOT / "data" / "static" / "stations.geojson"
ROUTE_CONFIG_PATH = ROOT / "config" / "demo_routes.json"

ORIGIN = {"lat": 10.7075, "lon": 106.705, "label": "Nguyen Huu Tho - Phuoc Kien"}
DESTINATION = {"lat": 10.806, "lon": 106.687, "label": "Phu Nhuan"}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    stations = json.loads(STATIONS_PATH.read_text(encoding="utf-8"))["features"]
    route_config = json.loads(ROUTE_CONFIG_PATH.read_text(encoding="utf-8"))
    route_ids = [definition["route_id"] for definition in route_config["routes"]]
    station_status = [
        {
            "station_id": "ST_EVO_AUDI_HCM",
            "timestamp": "2026-09-25T18:00:00+07:00",
            "total_ports": 4,
            "operational_ports": 3,
            "occupied_ports": 1,
            "available_ports": 2,
            "offline_ports": 1,
            "occupancy_ratio": 1 / 3,
            "queue_length": 0,
            "avg_session_duration_min": 35.0,
            "data_source": "synthetic",
        },
        {
            "station_id": "ST_EVO_DEUTSCHES_HAUS",
            "timestamp": "2026-09-25T18:00:00+07:00",
            "total_ports": 4,
            "operational_ports": 4,
            "occupied_ports": 3,
            "available_ports": 1,
            "offline_ports": 0,
            "occupancy_ratio": 0.75,
            "queue_length": 1,
            "avg_session_duration_min": 50.0,
            "data_source": "synthetic",
        },
        {
            "station_id": "ST_EVO_LAVIDA_Q7",
            "timestamp": "2026-09-25T18:00:00+07:00",
            "total_ports": 1,
            "operational_ports": 1,
            "occupied_ports": 0,
            "available_ports": 1,
            "offline_ports": 0,
            "occupancy_ratio": 0.0,
            "queue_length": 0,
            "avg_session_duration_min": 30.0,
            "data_source": "synthetic",
        },
    ]

    existing_status_ids = {status["station_id"] for status in station_status}
    for feature in stations:
        properties = feature["properties"]
        station_id = properties["station_id"]
        if station_id in existing_status_ids:
            continue
        total_ports = properties["total_ports"]
        station_status.append(
            {
                "station_id": station_id,
                "timestamp": "2026-09-27T00:00:00+07:00",
                "total_ports": total_ports,
                "operational_ports": total_ports,
                "occupied_ports": 0,
                "available_ports": total_ports,
                "offline_ports": 0,
                "occupancy_ratio": 0.0,
                "queue_length": 0,
                "avg_session_duration_min": 40.0,
                "data_source": "synthetic",
            }
        )

    planned_arrivals = [
        {
            "arrival_id": "ARR_DEUTSCHES_001",
            "station_id": "ST_EVO_DEUTSCHES_HAUS",
            "vehicle_id": "EV_VF5_PLUS",
            "created_at": "2026-09-25T18:00:00+07:00",
            "eta_at": "2026-09-25T18:18:00+07:00",
            "eta_window_start": "2026-09-25T18:15:00+07:00",
            "eta_window_end": "2026-09-25T18:21:00+07:00",
            "expected_energy_kwh": 20.0,
            "expected_charge_duration_min": 42.0,
            "arrival_probability": 0.9,
            "expires_at": "2026-09-25T18:30:00+07:00",
            "route_id": "ROUTE_VIA_DEUTSCHES_HAUS",
            "status": "planned",
            "data_source": "synthetic",
        },
        {
            "arrival_id": "ARR_DEUTSCHES_002",
            "station_id": "ST_EVO_DEUTSCHES_HAUS",
            "vehicle_id": "EV_VF7_ECO",
            "created_at": "2026-09-25T18:02:00+07:00",
            "eta_at": "2026-09-25T18:24:00+07:00",
            "eta_window_start": "2026-09-25T18:20:00+07:00",
            "eta_window_end": "2026-09-25T18:28:00+07:00",
            "expected_energy_kwh": 28.0,
            "expected_charge_duration_min": 55.0,
            "arrival_probability": 0.75,
            "expires_at": "2026-09-25T18:35:00+07:00",
            "route_id": "ROUTE_VIA_DEUTSCHES_HAUS",
            "status": "planned",
            "data_source": "synthetic",
        },
        {
            "arrival_id": "ARR_LAVIDA_CANCELLED",
            "station_id": "ST_EVO_LAVIDA_Q7",
            "vehicle_id": "EV_VF5_PLUS",
            "created_at": "2026-09-25T17:45:00+07:00",
            "eta_at": "2026-09-25T18:05:00+07:00",
            "eta_window_start": "2026-09-25T18:02:00+07:00",
            "eta_window_end": "2026-09-25T18:08:00+07:00",
            "expected_energy_kwh": 15.0,
            "expected_charge_duration_min": 20.0,
            "arrival_probability": 0.0,
            "expires_at": "2026-09-25T18:15:00+07:00",
            "route_id": "ROUTE_VIA_LAVIDA",
            "status": "cancelled",
            "data_source": "synthetic",
        },
        {
            "arrival_id": "ARR_LAVIDA_EXPIRED",
            "station_id": "ST_EVO_LAVIDA_Q7",
            "vehicle_id": "EV_VF7_ECO",
            "created_at": "2026-09-25T17:15:00+07:00",
            "eta_at": "2026-09-25T17:40:00+07:00",
            "eta_window_start": "2026-09-25T17:37:00+07:00",
            "eta_window_end": "2026-09-25T17:43:00+07:00",
            "expected_energy_kwh": 24.0,
            "expected_charge_duration_min": 24.0,
            "arrival_probability": 0.8,
            "expires_at": "2026-09-25T17:55:00+07:00",
            "route_id": "ROUTE_VIA_LAVIDA",
            "status": "expired",
            "data_source": "synthetic",
        },
    ]

    events = [
        {
            "event_id": "EVT_CONGEST_LA_VELA",
            "event_type": "congestion",
            "station_id": "ST_VF_LA_VELA",
            "start_at": "2026-09-25T18:12:00+07:00",
            "end_at": "2026-09-25T18:42:00+07:00",
            "severity": "high",
            "effects": {"queue_length_delta": 2, "occupied_ports_delta": 2},
            "description": "La Vela reaches full occupancy and gains a queue.",
            "is_synthetic": True,
        },
        {
            "event_id": "EVT_OUTAGE_LA_VELA",
            "event_type": "port_outage",
            "station_id": "ST_VF_LA_VELA",
            "start_at": "2026-09-25T18:10:00+07:00",
            "end_at": "2026-09-25T18:35:00+07:00",
            "severity": "high",
            "effects": {"offline_ports_delta": 2},
            "description": "Both La Vela charging ports become unavailable.",
            "is_synthetic": True,
        },
        {
            "event_id": "EVT_QUEUE_SPIKE_LAVIDA",
            "event_type": "queue_spike",
            "station_id": "ST_EVO_LAVIDA_Q7",
            "start_at": "2026-09-25T18:08:00+07:00",
            "end_at": "2026-09-25T18:28:00+07:00",
            "severity": "medium",
            "effects": {"queue_length_delta": 3},
            "description": "Three vehicles join the Lavida queue.",
            "is_synthetic": True,
        },
        {
            "event_id": "EVT_RECOVERY_AUDI",
            "event_type": "station_recovery",
            "station_id": "ST_EVO_AUDI_HCM",
            "start_at": "2026-09-25T18:20:00+07:00",
            "end_at": None,
            "severity": "low",
            "effects": {"offline_ports_delta": -1},
            "description": "The Audi internal station restores its offline port.",
            "is_synthetic": True,
        },
    ]

    preference = {
        "wait_weight": 0.4,
        "detour_weight": 0.25,
        "charging_time_weight": 0.25,
        "soc_risk_weight": 0.1,
    }

    def scenario(scenario_id: str, name: str, vehicle_id: str, initial_soc: float, event_ids: list[str]) -> dict:
        return {
            "scenario_id": scenario_id,
            "name": name,
            "vehicle_id": vehicle_id,
            "initial_soc": initial_soc,
            "target_soc": 0.8,
            "origin": ORIGIN,
            "destination": DESTINATION,
            "departure_at": "2026-09-25T18:00:00+07:00",
            "preference": preference,
            "event_ids": event_ids,
            "route_ids": route_ids,
        }

    scenarios = [
        scenario("SCN_NORMAL", "Normal journey", "EV_VF7_ECO", 0.55, []),
        scenario("SCN_LOW_SOC", "Low-SOC journey", "EV_VF5_PLUS", 0.14, []),
        scenario(
            "SCN_CONGESTION_REROUTE",
            "Congestion triggers reranking",
            "EV_VF7_ECO",
            0.32,
            ["EVT_CONGEST_LA_VELA"],
        ),
        scenario(
            "SCN_PORT_OUTAGE_REROUTE",
            "La Vela outage triggers reroute",
            "EV_VF5_PLUS",
            0.22,
            ["EVT_OUTAGE_LA_VELA"],
        ),
    ]

    baseline_rates = {
        "ST_EVO_AUDI_HCM": 0.4,
        "ST_EVO_DEUTSCHES_HAUS": 1.4,
        "ST_EVO_LAVIDA_Q7": 0.6,
    }
    queue_assumptions = {
        "planned_arrival_window_min": 15,
        "station_rates": [
            {
                "station_id": feature["properties"]["station_id"],
                "baseline_arrival_rate_per_hour": baseline_rates.get(
                    feature["properties"]["station_id"], 0.5
                ),
            }
            for feature in stations
        ],
        "scenario_overrides": [
            {
                "scenario_id": "SCN_CONGESTION_REROUTE",
                "station_id": "ST_VF_LA_VELA",
                "baseline_arrival_rate_per_hour": 2.8,
            },
        ],
        "data_source": "synthetic",
    }

    write_json(RUNTIME_DIR / "station_status.json", station_status)
    write_json(RUNTIME_DIR / "planned_arrivals.json", planned_arrivals)
    write_json(DEMO_DIR / "demo_events.json", events)
    write_json(DEMO_DIR / "demo_scenarios.json", scenarios)
    write_json(DEMO_DIR / "queue_assumptions.json", queue_assumptions)
    print("Generated Phase 1 runtime and demo data.")


if __name__ == "__main__":
    main()
