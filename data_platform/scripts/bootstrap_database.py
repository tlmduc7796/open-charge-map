from __future__ import annotations

import argparse
import re
import subprocess
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from data_platform.config import load_settings
from data_platform.runtime_seed import load_runtime_seed, seed_runtime_data
from data_platform.synthetic_port_seed import seed_synthetic_port_statuses
from data_platform.vehicles import load_vehicle_seed, seed_vehicle_data
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PACKAGE_ROOT / "data" / "bootstrap" / "current_database.sql"
VEHICLE_CATALOG = PACKAGE_ROOT / "data" / "static" / "vehicles.json"
DEMO_VEHICLES = PACKAGE_ROOT / "data" / "demo" / "vehicles.json"
PLANNED_ARRIVALS = PACKAGE_ROOT / "data" / "runtime" / "planned_arrivals.json"
QUEUE_ASSUMPTIONS = PACKAGE_ROOT / "data" / "demo" / "queue_assumptions.json"
EXPECTED_COUNTS = {
    "app_config": 1,
    "connector_types": 4,
    "port_status": 826,
    "port_status_history": 826,
    "ports": 826,
    "predictions": 96,
    "planned_arrivals": 4,
    "station_arrival_rates": 16,
    "station_amenities": 714,
    "station_external_refs": 14,
    "station_live_metrics": 102,
    "station_occupancy_5m": 4624,
    "stations": 102,
    "trip_events": 0,
    "trip_positions": 0,
    "trips": 0,
    "vehicle_connectors": 41,
    "vehicle_models": 21,
}


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=PACKAGE_ROOT,
        check=check,
        text=True,
        capture_output=not check,
    )


def _wait_for_postgres() -> None:
    for _ in range(60):
        result = _docker(
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            "smart_ev",
            "-d",
            "postgres",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready within 60 seconds")


def _ensure_database(database_name: str) -> None:
    result = _docker(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "smart_ev",
        "-d",
        "postgres",
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname = '{database_name}'",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unable to inspect PostgreSQL databases")
    if result.stdout.strip() == "1":
        return
    _docker("exec", "-T", "postgres", "createdb", "-U", "smart_ev", database_name)


def _database_url(database_name: str) -> str:
    return make_url(load_settings().database_url).set(database=database_name).render_as_string(
        hide_password=False
    )


def _migrate(database_url: str) -> None:
    config = Config(PACKAGE_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _table_counts(database_url: str) -> dict[str, int]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return {
                table: int(connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
                for table in EXPECTED_COUNTS
            }
    finally:
        engine.dispose()


def _restore(snapshot: Path, database_name: str) -> None:
    with snapshot.open("rb") as source:
        subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "--quiet",
                "-v",
                "ON_ERROR_STOP=1",
                "--single-transaction",
                "-U",
                "smart_ev",
                "-d",
                database_name,
            ],
            cwd=PACKAGE_ROOT,
            stdin=source,
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the database and restore the repository's complete demo snapshot."
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--database-name", default="smart_ev_data")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_]+", args.database_name):
        raise ValueError("database name may contain only letters, digits and underscores")
    snapshot = args.snapshot.resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(f"database snapshot not found: {snapshot}")
    load_vehicle_seed(VEHICLE_CATALOG, DEMO_VEHICLES)
    load_runtime_seed(PLANNED_ARRIVALS, QUEUE_ASSUMPTIONS)

    _docker("up", "-d", "postgres")
    _wait_for_postgres()
    _ensure_database(args.database_name)
    database_url = _database_url(args.database_name)
    _migrate(database_url)

    before = _table_counts(database_url)
    populated = {table: count for table, count in before.items() if count}
    if populated:
        details = ", ".join(f"{table}={count}" for table, count in populated.items())
        raise RuntimeError(
            "Bootstrap requires an empty migrated database; existing rows found: " + details
        )

    _restore(snapshot, args.database_name)
    engine = create_engine(database_url)
    try:
        seed_vehicle_data(engine, VEHICLE_CATALOG, DEMO_VEHICLES)
        seed_runtime_data(engine, PLANNED_ARRIVALS, QUEUE_ASSUMPTIONS)
        seed_synthetic_port_statuses(engine, PACKAGE_ROOT / "data/runtime/station_status.json")
    finally:
        engine.dispose()
    actual = _table_counts(database_url)
    if actual != EXPECTED_COUNTS:
        differences = {
            table: {"expected": EXPECTED_COUNTS[table], "actual": actual[table]}
            for table in EXPECTED_COUNTS
            if actual[table] != EXPECTED_COUNTS[table]
        }
        raise RuntimeError(f"restored row counts do not match snapshot: {differences}")

    print(
        "Database bootstrap complete: "
        f"{actual['stations']} stations, {actual['ports']} ports, "
        f"{actual['station_amenities']} amenities, "
        f"{actual['vehicle_models']} vehicles, "
        f"{actual['planned_arrivals']} planned arrivals"
    )


if __name__ == "__main__":
    main()
