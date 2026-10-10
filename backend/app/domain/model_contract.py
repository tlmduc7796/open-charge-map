"""Backend import path for the shared occupancy model contract."""

from shared.occupancy_contract import (
    CONTRACT_VERSION,
    INTERVAL_MIN,
    LAG_FEATURES,
    LOOKBACK_STEPS,
    SUPPORTED_HORIZONS_MIN,
    target_column,
)

__all__ = [
    "CONTRACT_VERSION",
    "INTERVAL_MIN",
    "LAG_FEATURES",
    "LOOKBACK_STEPS",
    "SUPPORTED_HORIZONS_MIN",
    "target_column",
]
