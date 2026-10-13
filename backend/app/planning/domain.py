"""Framework-free inputs and ports for the planning application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class PlanningRunConfig:
    city_id: str
    boundary_version: str
    pilot_extent_id: str
    as_of: datetime
    horizon_years: int
    data_snapshot_id: str
    seed: int
    config_version: str | None
    candidate_ids: tuple[str, ...]
    profile: str
    coverage_minutes: int
    charger_options: tuple[Mapping[str, Any], ...]
    budget_vnd: float | None


class PlanningDataError(Exception):
    """The requested versioned planning data is missing or invalid for this run."""


class PlanningInfrastructureError(Exception):
    """The planning data repository could not be reached."""


class PlanningEngineError(Exception):
    """A controlled planning-engine failure that can be reported as a failed run."""


class PlanningDataRepository(Protocol):
    """Resolve one immutable snapshot, its pinned boundary and only the requested candidates.

    M1's adapter owns the source schema. Returned data should include the versioned boundary,
    candidate coordinates/features/provenance, and any existing-site/demand context required by
    the engine; it must not load the full station catalog into the browser.
    """

    def load_dataset(self, config: PlanningRunConfig) -> Mapping[str, Any]: ...


class PlanningEngine(Protocol):
    """Pure M2 port. Output keys are status, recommendations, unranked_candidates,
    excluded_candidates and warnings, matching the shared HTTP response fields.
    """

    algorithm_version: str
    config_version: str

    def recommend(
        self, config: PlanningRunConfig, dataset: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...
