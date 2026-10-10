"""Reconcile vehicle JSON files and seed an existing migrated database."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_platform.config import load_settings
from data_platform.vehicles import seed_vehicle_data
from sqlalchemy import create_engine

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=PACKAGE_ROOT / "data/static/vehicles.json")
    parser.add_argument("--demo", type=Path, default=PACKAGE_ROOT / "data/demo/vehicles.json")
    args = parser.parse_args()
    engine = create_engine(load_settings().database_url)
    try:
        result = seed_vehicle_data(engine, args.catalog, args.demo)
    finally:
        engine.dispose()
    print("Vehicle seed complete: " + ", ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
