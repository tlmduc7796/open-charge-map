"""Preview or apply a configured retention cutoff to forecasts and telemetry history."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> None:
    from data_platform.config import load_settings
    from data_platform.connection import release_database_url
    from data_platform.retention import MAX_BATCH_SIZE, prune_observation_history
    from sqlalchemy import create_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--older-than-days",
        type=int,
        required=True,
        help="Approved retention age; there is intentionally no default policy",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10_000,
        help=f"Rows committed per table batch (1-{MAX_BATCH_SIZE}; default 10000)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPOSITORY_ROOT / ".env.release",
        help="Release env file used to connect to the local Compose database",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Permanently delete expired observation rows; otherwise only preview counts",
    )
    args = parser.parse_args()
    if not 1 <= args.older_than_days <= 36_500:
        parser.error("--older-than-days must be between 1 and 36500")
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")

    cutoff = datetime.now(UTC) - timedelta(days=args.older_than_days)
    database_url = release_database_url(args.env_file, load_settings().database_url)
    engine = create_engine(database_url)
    try:
        report = prune_observation_history(
            engine,
            cutoff=cutoff,
            apply=args.apply,
            batch_size=args.batch_size,
        )
    finally:
        engine.dispose()
    print(
        json.dumps(
            {"applied": args.apply, "cutoff": cutoff.isoformat(), "tables": report},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
