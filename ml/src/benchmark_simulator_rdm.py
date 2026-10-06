#!/usr/bin/env python3
"""Benchmark persistence, occupancy XGBoost and RDM on a fresh simulator run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator"))
from simulator.arrivals import generate_arrivals  # noqa: E402
from simulator.sessions import simulate_sessions  # noqa: E402
from simulator.weather import load_weather_categories  # noqa: E402


def _state(sessions: pd.DataFrame, ports: pd.DataFrame, station: str, when: pd.Timestamp):
    station_sessions = sessions.loc[sessions.station_id == station]
    active = station_sessions.loc[
        (station_sessions.connect <= when) & (when < station_sessions.disconnect)
    ]
    occupied = set(active.port_id)
    total = ports.loc[ports.station_id == station]
    return active, total, len(occupied) / len(total)


def run(output: Path) -> dict:
    config = json.loads((ROOT / "simulator/config/simulator.json").read_text(encoding="utf-8"))
    config.update({"seed": 20261006, "start_date": "2026-08-01", "end_date": "2026-08-14"})
    stations = json.loads((ROOT / "simulator/inputs/stations.geojson").read_text(encoding="utf-8"))
    vehicles = json.loads((ROOT / "simulator/inputs/vehicles.json").read_text(encoding="utf-8"))
    weather = load_weather_categories(
        ROOT / "simulator/inputs/weather_hcmc.json", config["weather"]
    )
    raw = simulate_sessions(
        config, stations, vehicles, generate_arrivals(config, stations, vehicles, weather)
    )
    sessions = pd.DataFrame(raw["sessions"])
    ports = pd.DataFrame(raw["ports"])
    for name in ("t_connect", "t_charge_start", "t_charge_end", "t_disconnect"):
        sessions[name[2:]] = pd.to_datetime(sessions[name], utc=True)
    occupancy_bundle = joblib.load(
        ROOT / "ml/artifacts/occupancy/gold_hcmc_q1_2026_xgboost/occupancy_model.joblib"
    )
    rdm = joblib.load(
        ROOT / "ml/artifacts/rdm/gold_hcmc_q1_2026_quantile/rdm_quantile_models.joblib"
    )
    start = pd.Timestamp("2026-08-02T03:00:00Z")
    end = pd.Timestamp("2026-08-13T10:00:00Z")
    # Six-hour snapshots span day/night and weekdays while keeping inference bounded.
    times = pd.date_range(start, end, freq="6h", tz="UTC")
    records: list[dict] = []
    for station in ports.station_id.unique():
        history = []
        for when in times:
            active, total, ratio = _state(sessions, ports, station, when)
            history.append(ratio)
            if len(history) < 13 or active.empty:
                continue
            features = pd.DataFrame(
                [list(reversed(history[-13:-1]))], columns=[f"lag_{i}" for i in range(1, 13)]
            )
            for eta in (5, 15, 30, 45, 60):
                arrival = when + pd.Timedelta(minutes=eta)
                _, _, actual_ratio = _state(sessions, ports, station, arrival)
                actual_available = actual_ratio < 1
                persistence_available = ratio < 1
                xgb_available = float(occupancy_bundle["models"][eta].predict(features)[0]) < 1
                elapsed = (when - active.connect).dt.total_seconds() / 60
                charge = (active.charge_end - active.charge_start).dt.total_seconds() / 60
                progress = ((when - active.charge_start).dt.total_seconds() / 60).clip(
                    lower=0
                ) / charge.clip(lower=1)
                frame = pd.DataFrame(
                    {
                        "session_elapsed_min": elapsed,
                        "energy_delivered_kwh": pd.to_numeric(active.energy_kwh)
                        * progress.clip(upper=1),
                        "current_power_kw": pd.to_numeric(active.avg_power_kw),
                        "station_id": active.station_id,
                        "port_id": active.port_id,
                        "connector_type": active.port_id.map(ports.set_index("port_id").connector),
                    }
                )
                pred = {q: np.maximum(0, model.predict(frame)) for q, model in rdm.items()}
                true_remaining = (active.disconnect - when).dt.total_seconds().to_numpy() / 60
                # Current free ports stay free; only current sessions may release.
                snapshot_available = ratio < 1 or bool(np.any(true_remaining <= eta))
                rdm_available = ratio < 1 or bool(np.any(pred["0.5"] <= eta))
                records.append(
                    {
                        "eta": eta,
                        "actual_available": actual_available,
                        "persistence": persistence_available,
                        "xgboost": xgb_available,
                        "snapshot_actual": snapshot_available,
                        "rdm": rdm_available,
                        "covered": bool(
                            np.all(
                                (true_remaining >= pred["0.1"]) & (true_remaining <= pred["0.9"])
                            )
                        ),
                        "release_mae": float(
                            np.mean(abs(true_remaining - pred["0.5"])),
                        ),
                    }
                )
    frame = pd.DataFrame(records)
    report = {
        "fresh_seed": config["seed"],
        "sessions": len(sessions),
        "queries": len(frame),
        "by_eta": {},
    }
    for eta, group in frame.groupby("eta"):
        report["by_eta"][str(eta)] = {
            "persistence_availability_accuracy_full_station": round(
                float((group.actual_available == group.persistence).mean()), 4
            ),
            "xgboost_availability_accuracy_full_station": round(
                float((group.actual_available == group.xgboost).mean()), 4
            ),
            "rdm_availability_accuracy_snapshot_only": round(
                float((group.snapshot_actual == group.rdm).mean()), 4
            ),
            "rdm_release_mae_min": round(float(group.release_mae.mean()), 3),
            "rdm_interval_coverage_all_active_sessions": round(float(group.covered.mean()), 4),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    path = ROOT / "ml/results/rdm/simulator_queue_benchmark.json"
    print(json.dumps(run(path), indent=2))
