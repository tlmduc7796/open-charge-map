"""Rebuild observed occupancy buckets from persisted operational snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

MAX_BATCH_DAYS = 31
_LATEST_SNAPSHOTS = """
    SELECT DISTINCT ON (
        snapshot.station_id,
        date_bin(interval '5 minutes', snapshot.observed_at,
                 timestamptz '2000-01-01 00:00:00+00')
    )
        snapshot.station_id,
        date_bin(interval '5 minutes', snapshot.observed_at,
                 timestamptz '2000-01-01 00:00:00+00') AS bucket_at,
        snapshot.snapshot
    FROM station_telemetry_snapshots AS snapshot
    JOIN stations AS station ON station.id=snapshot.station_id
    WHERE snapshot.data_source IN ('station_api', 'camera_vision', 'combined')
      AND snapshot.observed_at >= :start_at
      AND snapshot.observed_at < :end_at
      AND (CAST(:station_code AS text) IS NULL OR station.code=CAST(:station_code AS text))
    ORDER BY snapshot.station_id, bucket_at, snapshot.observed_at DESC
"""
_COUNT_BUCKETS = text(f"WITH latest AS ({_LATEST_SNAPSHOTS}) SELECT count(*) FROM latest")
_UPSERT_BUCKETS = text(
    f"""
    WITH latest AS ({_LATEST_SNAPSHOTS}), aggregated AS (
        SELECT latest.station_id, latest.bucket_at,
               count(port.value)::smallint AS total_ports,
               count(*) FILTER (
                   WHERE port.value->>'state' IN ('available', 'charging')
               )::smallint AS operational_ports,
               count(*) FILTER (
                   WHERE port.value->>'state' = 'charging'
               )::smallint AS occupied_ports,
               jsonb_array_length(
                   coalesce(latest.snapshot->'queue', '[]'::jsonb)
               )::integer AS queue_length
        FROM latest
        CROSS JOIN LATERAL jsonb_array_elements(latest.snapshot->'ports') AS port(value)
        GROUP BY latest.station_id, latest.bucket_at, latest.snapshot
    )
    INSERT INTO station_occupancy_5m AS occupancy (
        station_id, bucket_at, total_ports, operational_ports,
        occupied_ports, queue_length, data_origin
    )
    SELECT station_id, bucket_at, total_ports, operational_ports,
           occupied_ports, queue_length, 'observed'::data_origin
    FROM aggregated
    ON CONFLICT (station_id, bucket_at, simulation_run_id) DO UPDATE SET
        total_ports=EXCLUDED.total_ports,
        operational_ports=EXCLUDED.operational_ports,
        occupied_ports=EXCLUDED.occupied_ports,
        queue_length=EXCLUDED.queue_length,
        data_origin=EXCLUDED.data_origin
    WHERE occupancy.data_origin <> 'observed'
    RETURNING station_id
    """
)


def backfill_occupancy_from_telemetry(
    engine: Engine,
    *,
    start_at: datetime,
    end_at: datetime,
    station_code: str | None = None,
    batch_days: int = 1,
    apply: bool = False,
) -> dict[str, int]:
    """Preview or reconstruct observed buckets within a bounded time range.

    Snapshot rows are grouped into five-minute UTC buckets. The newest
    operational snapshot in each bucket wins. Existing observed occupancy is
    preserved, while synthetic/inferred rows can be replaced by observed data.
    """
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise ValueError("backfill range timestamps must include a timezone")
    if start_at >= end_at:
        raise ValueError("backfill start_at must precede end_at")
    if end_at.astimezone(UTC) > datetime.now(UTC):
        raise ValueError("backfill end_at cannot be in the future")
    if not 1 <= batch_days <= MAX_BATCH_DAYS:
        raise ValueError(f"batch_days must be between 1 and {MAX_BATCH_DAYS}")
    if station_code is not None and not station_code.strip():
        raise ValueError("station_code cannot be blank")

    cursor = start_at.astimezone(UTC)
    end_utc = end_at.astimezone(UTC)
    report = {"eligible": 0, "upserted": 0, "batches": 0}
    while cursor < end_utc:
        midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        batch_limit = (
            midnight + timedelta(days=batch_days)
            if cursor == midnight
            else midnight + timedelta(days=1)
        )
        batch_end = min(batch_limit, end_utc)
        params = {
            "start_at": cursor,
            "end_at": batch_end,
            "station_code": station_code,
        }
        with engine.connect() as connection:
            report["eligible"] += int(
                connection.execute(_COUNT_BUCKETS, params).scalar_one()
            )
        report["batches"] += 1
        if apply:
            with engine.begin() as connection:
                inserted = connection.execute(_UPSERT_BUCKETS, params)
                report["upserted"] += max(0, inserted.rowcount or 0)
        cursor = batch_end
    return report
