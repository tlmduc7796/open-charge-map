#!/usr/bin/env python3
"""Compare live-safe and simulator-enhanced RDM feature profiles.

This is deliberately an offline simulator experiment, not a production trainer.
Every simulation seed is assigned wholly to train, validation, or test, so a
near-identical session from the same simulated world cannot cross a split.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator"))
from simulator.arrivals import generate_arrivals  # noqa: E402
from simulator.sessions import simulate_sessions  # noqa: E402
from simulator.weather import load_weather_categories  # noqa: E402

TARGET = "remaining_port_release_min"
QUANTILES = (0.1, 0.5, 0.9)

# These columns can be obtained from port inventory, a live meter/status feed,
# and the observation clock. They are the only profile eligible for future
# production work, once it is retrained on real Vietnamese operator data.
BASIC_NUMERIC = (
    "session_elapsed_min",
    "energy_delivered_kwh",
    "current_power_kw",
    "port_max_power_kw",
    "observation_hour",
    "observation_weekday",
    "is_charging",
)
BASIC_CATEGORICAL = ("station_id", "port_id", "connector_type")

# These values are available at/after plug-in in this simulator, but need
# explicit provider/user consent in a real system. They are kept in an
# isolated experimental profile and are never written into canonical RDM data.
ENHANCED_NUMERIC = BASIC_NUMERIC + (
    "soc_on_arrival",
    "current_soc",
    "vehicle_max_power_kw",
    "vehicle_usable_battery_kwh",
)
ENHANCED_CATEGORICAL = BASIC_CATEGORICAL + ("vehicle_segment",)


def _load_inputs() -> tuple[dict, dict, list[dict], dict]:
    config = json.loads((ROOT / "simulator/config/simulator.json").read_text(encoding="utf-8"))
    # A two-week window keeps this regression experiment quick while retaining
    # day/night and weekday effects. Seeds, not individual rows, are split.
    config.update({"start_date": "2026-08-01", "end_date": "2026-08-14"})
    stations = json.loads((ROOT / "simulator/inputs/stations.geojson").read_text(encoding="utf-8"))
    vehicles = json.loads((ROOT / "simulator/inputs/vehicles.json").read_text(encoding="utf-8"))
    weather = load_weather_categories(
        ROOT / "simulator/inputs/weather_hcmc.json", config["weather"]
    )
    return config, stations, vehicles, weather


def _session_observations(
    sessions: pd.DataFrame, ports: pd.DataFrame, vehicles: list[dict], seed: int, split: str
) -> pd.DataFrame:
    """Create only information that was available at each five-minute observation."""
    vehicle = pd.DataFrame(vehicles).set_index("vehicle_id")
    port = ports.set_index("port_id")
    rows: list[dict[str, object]] = []
    for item in sessions.itertuples(index=False):
        connect = pd.Timestamp(item.t_connect, tz="UTC")
        charge_start = pd.Timestamp(item.t_charge_start, tz="UTC")
        charge_end = pd.Timestamp(item.t_charge_end, tz="UTC")
        disconnect = pd.Timestamp(item.t_disconnect, tz="UTC")
        profile = vehicle.loc[item.vehicle_id]
        port_profile = port.loc[item.port_id]
        vehicle_max_power = float(
            profile.max_ac_power_kw if port_profile.current == "AC" else profile.max_dc_power_kw
        )
        observation_times = pd.date_range(
            connect.ceil("5min"), disconnect, freq="5min", inclusive="left"
        )
        for observed_at in observation_times:
            charging_until = min(observed_at, charge_end)
            charged_minutes = max(0.0, (charging_until - charge_start).total_seconds() / 60)
            is_charging = int(charge_start <= observed_at < charge_end)
            current_power = float(item.avg_power_kw) if is_charging else 0.0
            delivered = max(0.0, float(item.avg_power_kw) * charged_minutes / 60)
            rows.append(
                {
                    "simulation_seed": seed,
                    "split": split,
                    "session_id": f"{seed}_{item.session_id}",
                    "observed_at": observed_at,
                    TARGET: (disconnect - observed_at).total_seconds() / 60,
                    "session_elapsed_min": (observed_at - connect).total_seconds() / 60,
                    "energy_delivered_kwh": delivered,
                    "current_power_kw": current_power,
                    "port_max_power_kw": float(port_profile.max_power_kw),
                    "observation_hour": observed_at.hour,
                    "observation_weekday": observed_at.weekday(),
                    "is_charging": is_charging,
                    "station_id": item.station_id,
                    "port_id": item.port_id,
                    "connector_type": port_profile.connector,
                    # Simulator-only / consent-gated features below this line.
                    "soc_on_arrival": float(item.soc_start),
                    "current_soc": float(item.soc_start)
                    + delivered
                    * float(profile.charging_efficiency)
                    / float(profile.usable_battery_kwh),
                    "vehicle_max_power_kw": vehicle_max_power,
                    "vehicle_usable_battery_kwh": float(profile.usable_battery_kwh),
                    "vehicle_segment": item.vehicle_id,
                }
            )
    return pd.DataFrame(rows)


def build_experiment_data(seed_sets: dict[str, tuple[int, ...]]) -> pd.DataFrame:
    config, stations, vehicles, weather = _load_inputs()
    frames: list[pd.DataFrame] = []
    for split, seeds in seed_sets.items():
        for seed in seeds:
            run_config = {**config, "seed": seed}
            raw = simulate_sessions(
                run_config,
                stations,
                vehicles,
                generate_arrivals(run_config, stations, vehicles, weather),
            )
            frames.append(
                _session_observations(
                    pd.DataFrame(raw["sessions"]), pd.DataFrame(raw["ports"]), vehicles, seed, split
                )
            )
    result = pd.concat(frames, ignore_index=True)
    if result.empty or (result[TARGET] <= 0).any():
        raise ValueError("Simulator experiment produced invalid RDM labels")
    if result.groupby("session_id")["split"].nunique().gt(1).any():
        raise ValueError("A simulated session crossed a split")
    return result


def _model(numeric: tuple[str, ...], categorical: tuple[str, ...], quantile: float) -> Pipeline:
    from xgboost import XGBRegressor

    features = ColumnTransformer(
        [
            ("numeric", SimpleImputer(strategy="median"), list(numeric)),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                list(categorical),
            ),
        ],
        sparse_threshold=0,
    )
    regressor = XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=quantile,
        n_estimators=180,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline([("features", features), ("model", regressor)])


def _metrics(actual: pd.Series, predicted: dict[float, np.ndarray]) -> dict[str, float]:
    middle = predicted[0.5]
    values = actual.to_numpy()
    return {
        "mae_p50_min": round(float(mean_absolute_error(values, middle)), 4),
        "median_absolute_error_p50_min": round(float(np.median(np.abs(values - middle))), 4),
        "rmse_p50_min": round(float(mean_squared_error(values, middle) ** 0.5), 4),
        "interval_coverage_p10_p90": round(
            float(np.mean((values >= predicted[0.1]) & (values <= predicted[0.9]))), 4
        ),
        "quantile_crossing_rate": round(
            float(np.mean((predicted[0.1] > middle) | (middle > predicted[0.9]))), 4
        ),
    }


def _train_profile(
    data: pd.DataFrame, numeric: tuple[str, ...], categorical: tuple[str, ...], name: str
) -> tuple[dict[str, object], dict[str, Pipeline]]:
    columns = [*numeric, *categorical]
    train = data.loc[data.split == "train"]
    models = {
        quantile: _model(numeric, categorical, quantile).fit(train[columns], train[TARGET])
        for quantile in QUANTILES
    }
    result: dict[str, object] = {
        "profile": name,
        "numeric_features": list(numeric),
        "categorical_features": list(categorical),
    }
    for split in ("val", "test"):
        observed = data.loc[data.split == split]
        predictions = {
            quantile: model.predict(observed[columns]) for quantile, model in models.items()
        }
        result[f"{split}_metrics"] = _metrics(observed[TARGET], predictions)
    return result, {str(quantile): model for quantile, model in models.items()}


def run(output_dir: Path) -> dict[str, object]:
    seed_sets = {
        "train": (20261011, 20261012, 20261013, 20261014),
        "val": (20261015, 20261016),
        "test": (20261017, 20261018),
    }
    data = build_experiment_data(seed_sets)
    basic, basic_models = _train_profile(data, BASIC_NUMERIC, BASIC_CATEGORICAL, "live_safe")
    enhanced, enhanced_models = _train_profile(
        data, ENHANCED_NUMERIC, ENHANCED_CATEGORICAL, "simulator_enhanced"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "simulator_rdm_feature_profiles.parquet"
    report_path = output_dir / "report.json"
    data.to_parquet(data_path, index=False)
    joblib.dump(basic_models, output_dir / "live_safe_models.joblib")
    joblib.dump(enhanced_models, output_dir / "simulator_enhanced_models.joblib")
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "offline_synthetic_experiment_not_for_serving",
        "target": "time from observation until physical port release (disconnect)",
        "seed_split": {name: list(seeds) for name, seeds in seed_sets.items()},
        "split_rule": "entire simulator seeds are isolated across train, validation and test",
        "records_by_split": {name: int((data.split == name).sum()) for name in seed_sets},
        "sessions_by_split": {
            name: int(data.loc[data.split == name, "session_id"].nunique()) for name in seed_sets
        },
        "profiles": [basic, enhanced],
        "production_rule": (
            "Only the live_safe profile may later be retrained on real operator data. "
            "The simulator_enhanced profile is a feature-value study, not a serving candidate."
        ),
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"report_path": str(report_path), "dataset_path": str(data_path), **report}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "ml/results/rdm/feature_profile_experiment",
    )
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
