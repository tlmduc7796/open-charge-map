"""Bounded-batch retention for operational observation history."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, text

RETENTION_TABLES = {
    "predictions": "run_at",
    "station_occupancy_5m": "bucket_at",
    "port_status_history": "changed_at",
    "station_telemetry_snapshots": "observed_at",
}
MAX_BATCH_SIZE = 100_000


def prune_observation_history(
    engine: Engine,
    *,
    cutoff: datetime,
    apply: bool = False,
    batch_size: int = 10_000,
) -> dict[str, dict[str, int]]:
    """Preview or remove observation rows older than a timezone-aware cutoff.

    Each apply batch is committed separately so the command bounds transaction
    size and row-lock duration. Journey and incident records are intentionally
    outside this telemetry retention policy.
    """
    if cutoff.tzinfo is None:
        raise ValueError("retention cutoff must include a timezone")
    if cutoff.astimezone(UTC) > datetime.now(UTC):
        raise ValueError("retention cutoff cannot be in the future")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")

    report: dict[str, dict[str, int]] = {}
    for table, timestamp_column in RETENTION_TABLES.items():
        with engine.connect() as connection:
            candidate_count = int(
                connection.execute(
                    text(
                        f"SELECT count(*) FROM {table} "
                        f"WHERE {timestamp_column} < :cutoff"
                    ),
                    {"cutoff": cutoff},
                ).scalar_one()
            )
        deleted_count = 0
        if apply:
            delete_batch = text(
                f"WITH expired AS ("
                f"SELECT tableoid, ctid FROM {table} "
                f"WHERE {timestamp_column} < :cutoff "
                f"ORDER BY {timestamp_column}, tableoid, ctid LIMIT :batch_size) "
                f"DELETE FROM {table} AS target USING expired "
                f"WHERE target.tableoid=expired.tableoid AND target.ctid=expired.ctid"
            )
            while True:
                with engine.begin() as connection:
                    result = connection.execute(
                        delete_batch,
                        {"cutoff": cutoff, "batch_size": batch_size},
                    )
                    batch_deleted = max(0, result.rowcount or 0)
                deleted_count += batch_deleted
                if batch_deleted == 0:
                    break
        report[table] = {
            "eligible": candidate_count,
            "deleted": deleted_count,
        }
    return report
