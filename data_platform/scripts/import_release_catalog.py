"""Preview or import an explicitly reviewed release station and vehicle catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> None:
    from data_platform.connection import release_database_url
    from data_platform.release_catalog import import_release_catalog, load_release_catalog
    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stations", type=Path, required=True, help="Reviewed StationCollection JSON"
    )
    parser.add_argument(
        "--vehicles", type=Path, required=True, help="Reviewed Vehicle array JSON"
    )
    parser.add_argument(
        "--port-map",
        type=Path,
        help=(
            "Optional reviewed JSON mapping station IDs and catalog port labels "
            "to stable provider port IDs"
        ),
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write the validated catalog to PostgreSQL"
    )
    parser.add_argument(
        "--replace-snapshot",
        action="store_true",
        help=(
            "Treat the files as complete snapshots: deactivate missing previously "
            "reviewed stations from included providers and missing reviewed VN vehicles"
        ),
    )
    parser.add_argument(
        "--reviewed-by", help="Operator identity recorded in provenance when applying"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPOSITORY_ROOT / ".env.release",
        help="Release env file used to connect to the local Compose database",
    )
    args = parser.parse_args()
    if args.apply and not args.reviewed_by:
        parser.error("--reviewed-by is required with --apply")

    try:
        stations, vehicles = load_release_catalog(args.stations, args.vehicles)
        port_external_ids = (
            json.loads(args.port_map.read_text(encoding="utf-8"))
            if args.port_map
            else None
        )
    except (OSError, ValueError) as exc:
        parser.error(f"catalog or port-map loading failed: {exc}")
    if port_external_ids is not None and not isinstance(port_external_ids, dict):
        parser.error("--port-map must contain a JSON object keyed by station ID")
    if not args.apply:
        result = import_release_catalog(
            None,
            stations,
            vehicles,
            replace_snapshot=args.replace_snapshot,
            port_external_ids=port_external_ids,
        )
    else:
        database_url = release_database_url(
            args.env_file
        )
        engine = create_engine(database_url)
        try:
            result = import_release_catalog(
                engine,
                stations,
                vehicles,
                apply=True,
                reviewed_by=args.reviewed_by,
                replace_snapshot=args.replace_snapshot,
                port_external_ids=port_external_ids,
            )
        finally:
            engine.dispose()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
