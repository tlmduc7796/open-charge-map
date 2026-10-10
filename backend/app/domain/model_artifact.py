"""Validated handoff contract for a Phase 04 occupancy model artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from backend.app.domain.models import DomainModel


class ModelMetric(DomainModel):
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)


class ArtifactFile(DomainModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OccupancyModelMetadata(DomainModel):
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    task: Literal["occupancy_forecasting"]
    training_dataset: str = Field(min_length=1)
    training_level: Literal["station", "zone"]
    feature_order: tuple[str, ...] = Field(min_length=1)
    lookback_steps: int = Field(default=12)
    temporal_resolution_min: int = Field(default=5)
    supported_horizons_min: tuple[int, ...] = Field(min_length=1)
    target: Literal["occupancy_ratio"]
    metrics_by_horizon: dict[int, ModelMetric]
    persistence_metrics_by_horizon: dict[int, ModelMetric]
    serving_decision: Literal["model", "persistence"]
    random_seed: int
    model_artifact: ArtifactFile
    preprocessor_artifact: ArtifactFile
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> OccupancyModelMetadata:
        if self.lookback_steps != 12:
            raise ValueError("model metadata must declare a 12-step lookback")
        if self.temporal_resolution_min != 5:
            raise ValueError("model metadata must declare a 5-minute resolution")
        if len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("feature_order values must be unique")
        supported = set(self.supported_horizons_min)
        if not supported <= {5, 10, 15, 20, 25, 30}:
            raise ValueError("unsupported forecast horizon")
        if set(self.metrics_by_horizon) != supported:
            raise ValueError("metrics must cover every supported horizon exactly")
        if set(self.persistence_metrics_by_horizon) != supported:
            raise ValueError("persistence metrics must cover every supported horizon exactly")
        if self.serving_decision == "model":
            insufficient = [
                horizon
                for horizon in supported
                if self.persistence_metrics_by_horizon[horizon].mae <= 0
                or self.metrics_by_horizon[horizon].mae
                > self.persistence_metrics_by_horizon[horizon].mae * 0.95
            ]
            if insufficient:
                raise ValueError(
                    "serving model must improve persistence MAE by at least 5% "
                    f"for every supported horizon: {sorted(insufficient)}"
                )
        return self


def load_model_metadata(path: Path) -> OccupancyModelMetadata:
    with path.open(encoding="utf-8") as source:
        return OccupancyModelMetadata.model_validate(json.load(source))
