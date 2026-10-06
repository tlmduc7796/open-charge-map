#!/usr/bin/env python3
"""Replay RDM P10/P50/P90 through Queue Lab against fresh simulator truth."""
# ruff: noqa: E402, I001

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "simulator"))
from simulator.arrivals import generate_arrivals  # noqa: E402
from simulator.sessions import simulate_sessions  # noqa: E402
from simulator.weather import load_weather_categories  # noqa: E402
from backend.app.domain.queue_lab import (  # noqa: E402
    QueueLabPort,
    QueueLabSimulationRequest,
    QueueLabVehicle,
    SyntheticDuration,
    simulate_queue_lab,
)


def fixed(minutes: float) -> SyntheticDuration:
    return SyntheticDuration(kind="fixed", value_min=max(0.01, float(minutes)))


def run(output: Path) -> dict:
    config = json.loads((ROOT / "simulator/config/simulator.json").read_text(encoding="utf-8"))
    config.update({"seed": 20261007, "start_date": "2026-08-01", "end_date": "2026-08-14"})
    stations = json.loads((ROOT / "simulator/inputs/stations.geojson").read_text(encoding="utf-8"))
    vehicles = json.loads((ROOT / "simulator/inputs/vehicles.json").read_text(encoding="utf-8"))
    weather = load_weather_categories(
        ROOT / "simulator/inputs/weather_hcmc.json", config["weather"]
    )
    raw = simulate_sessions(
        config, stations, vehicles, generate_arrivals(config, stations, vehicles, weather)
    )
    sessions, ports = pd.DataFrame(raw["sessions"]), pd.DataFrame(raw["ports"])
    for raw_name, name in (
        ("t_connect", "connect"),
        ("t_charge_start", "charge_start"),
        ("t_charge_end", "charge_end"),
        ("t_disconnect", "disconnect"),
    ):
        sessions[name] = pd.to_datetime(sessions[raw_name], utc=True)
    models = joblib.load(
        ROOT / "ml/artifacts/rdm/gold_hcmc_q1_2026_quantile/rdm_quantile_models.joblib"
    )
    results = []
    for station_id in ports.station_id.unique():
        for when in pd.date_range(
            "2026-08-02T03:00:00Z", "2026-08-13T03:00:00Z", freq="12h", tz="UTC"
        ):
            active = sessions.loc[
                (sessions.station_id == station_id)
                & (sessions.connect <= when)
                & (when < sessions.disconnect)
            ].copy()
            if active.empty:
                continue
            station_ports = ports.loc[ports.station_id == station_id]
            connector = tuple(station_ports.connector.unique())
            actual_remaining = dict(
                zip(active.port_id, (active.disconnect - when).dt.total_seconds() / 60, strict=True)
            )
            elapsed = (when - active.connect).dt.total_seconds() / 60
            charge_minutes = (active.charge_end - active.charge_start).dt.total_seconds() / 60
            progress = ((when - active.charge_start).dt.total_seconds() / 60).clip(
                lower=0
            ) / charge_minutes.clip(lower=1)
            features = pd.DataFrame(
                {
                    "session_elapsed_min": elapsed,
                    "energy_delivered_kwh": pd.to_numeric(active.energy_kwh)
                    * progress.clip(upper=1),
                    "current_power_kw": pd.to_numeric(active.avg_power_kw),
                    "station_id": active.station_id,
                    "port_id": active.port_id,
                    "connector_type": active.port_id.map(
                        station_ports.set_index("port_id").connector
                    ),
                }
            )
            predicted = {
                q: dict(zip(active.port_id, np.maximum(0.01, model.predict(features)), strict=True))
                for q, model in models.items()
            }
            waits = {}
            for label, durations in {"actual": actual_remaining, **predicted}.items():
                request_ports = tuple(
                    QueueLabPort(
                        port_id=p.port_id,
                        connector_types=(p.connector,),
                        state="charging" if p.port_id in durations else "available",
                        remaining_port_release=fixed(durations[p.port_id])
                        if p.port_id in durations
                        else None,
                    )
                    for p in station_ports.itertuples(index=False)
                )
                request = QueueLabSimulationRequest(
                    evaluation_at=when.to_pydatetime(),
                    ports=request_ports,
                    confirmed_queue=(
                        QueueLabVehicle(
                            vehicle_id="CONFIRMED_1",
                            queue_position=1,
                            connector_types=connector,
                            charging_duration=fixed(30),
                        ),
                    ),
                    requester_connector_types=connector,
                    requester_charge_duration=fixed(30),
                    trials=1,
                )
                result = simulate_queue_lab(request)
                waits[label] = result.estimated_wait_min
            if all(waits[key] is not None for key in ("actual", "0.1", "0.5", "0.9")):
                results.append(waits)
    frame = pd.DataFrame(results)
    report = {
        "fresh_seed": config["seed"],
        "scenarios": len(frame),
        "queue_policy": "one confirmed 30-minute vehicle; no unobserved future arrivals",
        "p50_wait_mae_min": round(float(abs(frame["0.5"] - frame.actual).mean()), 3),
        "p10_p90_wait_coverage": round(
            float(((frame.actual >= frame["0.1"]) & (frame.actual <= frame["0.9"])).mean()), 4
        ),
        "actual_wait_median_min": round(float(frame.actual.median()), 3),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(ROOT / "ml/results/rdm/queue_lab_rdm_replay.json"), indent=2))
