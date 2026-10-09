"""Validated handoff contract for a Phase 04 occupancy model artifact."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel


class ModelMetric(DomainModel):
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)


class OccupancyModelMetadata(DomainModel):
    model_version: str = Field(min_length=1)
    training_data_source: str = Field(min_length=1)
    feature_order: tuple[str, ...] = Field(min_length=1)
    lookback_steps: int = Field(default=12)
    resolution_min: int = Field(default=5)
    supported_horizons_min: tuple[int, ...] = Field(min_length=1)
    metrics_by_horizon: dict[int, ModelMetric]

    @model_validator(mode="after")
    def validate_contract(self) -> OccupancyModelMetadata:
        if self.lookback_steps != 12:
            raise ValueError("model metadata must declare a 12-step lookback")
        if self.resolution_min != 5:
            raise ValueError("model metadata must declare a 5-minute resolution")
        if len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("feature_order values must be unique")
        supported = set(self.supported_horizons_min)
        if not supported <= {5, 10, 15, 20, 25, 30}:
            raise ValueError("unsupported forecast horizon")
        if set(self.metrics_by_horizon) != supported:
            raise ValueError("metrics must cover every supported horizon exactly")
        return self


def load_model_metadata(path: Path) -> OccupancyModelMetadata:
    with path.open(encoding="utf-8") as source:
        return OccupancyModelMetadata.model_validate(json.load(source))
