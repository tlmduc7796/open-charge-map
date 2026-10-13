"""Planning-data repository ports and the explicit pre-M1 unavailable adapter."""

from __future__ import annotations

from typing import Any, Mapping

from backend.app.planning.domain import PlanningDataError, PlanningRunConfig


class UnconfiguredPlanningDataRepository:
    """No candidate/boundary snapshot is present in the current application baseline."""

    def load_dataset(self, config: PlanningRunConfig) -> Mapping[str, Any]:
        raise PlanningDataError(
            "Planning data is not configured for snapshot "
            f"'{config.data_snapshot_id}'. M1 must provide matching versioned candidate "
            "and boundary data before spatial analysis can run."
        )
