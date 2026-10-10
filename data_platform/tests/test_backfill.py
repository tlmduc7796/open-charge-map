from datetime import UTC, datetime

import pytest
from data_platform.backfill import MAX_BATCH_DAYS, backfill_occupancy_from_telemetry


@pytest.mark.parametrize(
    ("start_at", "end_at", "batch_days", "message"),
    [
        (datetime(2020, 1, 1), datetime(2020, 1, 2, tzinfo=UTC), 1, "timezone"),
        (
            datetime(2099, 1, 1, tzinfo=UTC),
            datetime(2099, 1, 2, tzinfo=UTC),
            1,
            "future",
        ),
        (
            datetime(2020, 1, 2, tzinfo=UTC),
            datetime(2020, 1, 1, tzinfo=UTC),
            1,
            "precede",
        ),
        (
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 2, tzinfo=UTC),
            MAX_BATCH_DAYS + 1,
            "batch_days",
        ),
    ],
)
def test_backfill_validates_range_before_database_access(
    start_at: datetime,
    end_at: datetime,
    batch_days: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        backfill_occupancy_from_telemetry(
            None,  # type: ignore[arg-type]
            start_at=start_at,
            end_at=end_at,
            batch_days=batch_days,
        )


def test_backfill_rejects_blank_station_code() -> None:
    with pytest.raises(ValueError, match="station_code"):
        backfill_occupancy_from_telemetry(
            None,  # type: ignore[arg-type]
            start_at=datetime(2020, 1, 1, tzinfo=UTC),
            end_at=datetime(2020, 1, 2, tzinfo=UTC),
            station_code="  ",
        )
