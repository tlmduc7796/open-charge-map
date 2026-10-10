from datetime import UTC, datetime, timedelta

import pytest
from data_platform.retention import (
    MAX_BATCH_SIZE,
    RETENTION_TABLES,
    prune_observation_history,
)


def test_prediction_rows_share_the_approved_observation_retention_window() -> None:
    assert RETENTION_TABLES["predictions"] == "run_at"


@pytest.mark.parametrize(
    ("cutoff", "batch_size", "message"),
    [
        (datetime(2020, 1, 1), 10, "timezone"),
        (datetime.now(UTC) + timedelta(days=1), 10, "future"),
        (datetime(2020, 1, 1, tzinfo=UTC), 0, "batch_size"),
        (datetime(2020, 1, 1, tzinfo=UTC), MAX_BATCH_SIZE + 1, "batch_size"),
    ],
)
def test_retention_rejects_unsafe_cutoffs_and_batches(cutoff, batch_size, message) -> None:
    with pytest.raises(ValueError, match=message):
        prune_observation_history(
            None,
            cutoff=cutoff,
            batch_size=batch_size,
        )
