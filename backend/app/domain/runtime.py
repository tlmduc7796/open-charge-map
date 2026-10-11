"""Thread-safe snapshot of current station status read from a status repository."""

from __future__ import annotations

from threading import RLock

from backend.app.domain.models import StationStatus
from backend.app.domain.repositories import StationStatusRepository


class RuntimeStateStore:
    def __init__(self, statuses: StationStatusRepository) -> None:
        self._status_repository = statuses
        self._statuses = {status.station_id: status for status in statuses.all()}
        self._lock = RLock()

    def all(self) -> tuple[StationStatus, ...]:
        with self._lock:
            return tuple(self._statuses.values())

    def get(self, station_id: str) -> StationStatus:
        with self._lock:
            return self._statuses[station_id]

    def refresh(self) -> None:
        """Reload the latest persisted telemetry."""
        statuses = self._status_repository.all()
        with self._lock:
            self._statuses = {status.station_id: status for status in statuses}
