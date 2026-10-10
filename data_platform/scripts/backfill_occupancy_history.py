"""Preview or rebuild observed occupancy history from saved telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from data_platform.backfill import backfill_occupancy_from_telemetry
from data_platform.connection import release_database_url
from sqlalchemy import create_engine


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include timezone offset")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start_at", type=_timestamp, required=True)
    parser.add_argument("--to", dest="end_at", type=_timestamp, required=True)
    parser.add_argument("--station-code")
    parser.add_argument(
        "--batch-days", type=int, default=1, help="Days per transaction (1-31; default 1)"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env.release"),
        help="Release env file used to connect to the local Compose database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write buckets; without this flag only counts eligible buckets",
    )
    args = parser.parse_args()

    engine = create_engine(
        release_database_url(args.env_file), pool_pre_ping=True, pool_timeout=10
    )
    try:
        report = backfill_occupancy_from_telemetry(
            engine,
            start_at=args.start_at,
            end_at=args.end_at,
            station_code=args.station_code,
            batch_days=args.batch_days,
            apply=args.apply,
        )
    finally:
        engine.dispose()
    print(f"mode={'apply' if args.apply else 'preview'}")
    print(f"range=[{args.start_at.isoformat()}, {args.end_at.isoformat()})")
    print(f"eligible_buckets={report['eligible']}")
    print(f"upserted_buckets={report['upserted']}")
    print(f"batches={report['batches']}")


if __name__ == "__main__":
    main()
