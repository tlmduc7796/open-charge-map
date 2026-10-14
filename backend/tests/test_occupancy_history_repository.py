from datetime import UTC, datetime, timedelta

import pytest

pd = pytest.importorskip("pandas")

from backend.app.occupancy_history_repository import (  # noqa: E402
    DatabaseOccupancyHistoryRepository,
)
from ml.geo_features import GEO_COLUMNS, NEAREST_STATION_ID_COLUMN  # noqa: E402

T0 = datetime(2026, 9, 15, 10, tzinfo=UTC)


def _repository(monkeypatch, neighbor_rows):
    table = pd.DataFrame(
        {column: [0.0, 0.0] for column in GEO_COLUMNS}, index=["A", "B"]
    )
    table[NEAREST_STATION_ID_COLUMN] = ["B", "A"]
    repository = DatabaseOccupancyHistoryRepository(None, table)
    own_rows = [
        {"bucket_at": T0 - timedelta(minutes=5 * i), "total_ports": 4,
         "operational_ports": 4, "occupied_ports": 2}
        for i in range(12)
    ]
    monkeypatch.setattr(
        repository, "_rows",
        lambda station_id, as_of, limit: own_rows if station_id == "A" else neighbor_rows,
    )
    return repository


@pytest.mark.parametrize("neighbor_rows", [
    [],
    [{"bucket_at": T0 - timedelta(minutes=5), "operational_ports": 4, "occupied_ports": 1}],
    [{"bucket_at": T0, "operational_ports": 0, "occupied_ports": 0}],
    [{"bucket_at": T0, "operational_ports": 4, "occupied_ports": 5}],
    [{"bucket_at": T0, "operational_ports": 4, "occupied_ports": -1}],
])
def test_missing_or_invalid_neighbor_disables_model_window(monkeypatch, neighbor_rows):
    assert _repository(monkeypatch, neighbor_rows).window("A", T0) is None


def test_exact_neighbor_bucket_supplies_spatial_lag(monkeypatch):
    rows = [{"bucket_at": T0, "operational_ports": 4, "occupied_ports": 1}]
    window = _repository(monkeypatch, rows).window("A", T0)
    assert window is not None
    assert window.nearest_station_occupancy == 0.25
    assert window.lags[0] == 0.5


def test_neighbor_bucket_arriving_later_recovers_the_window(monkeypatch):
    rows = []
    repository = _repository(monkeypatch, rows)
    assert repository.window("A", T0) is None
    rows.append({"bucket_at": T0, "operational_ports": 4, "occupied_ports": 1})
    assert repository.window("A", T0).nearest_station_occupancy == 0.25
