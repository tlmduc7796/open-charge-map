"""Dependency-free occupancy feature contract shared by training and serving."""

CONTRACT_VERSION = "2.2"
INTERVAL_MIN = 5
LOOKBACK_STEPS = 12
SUPPORTED_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
LAG_FEATURES = tuple(f"lag_{step}" for step in range(1, LOOKBACK_STEPS + 1))


def target_column(horizon_min: int) -> str:
    if horizon_min not in SUPPORTED_HORIZONS_MIN:
        raise ValueError(f"Unsupported occupancy horizon: {horizon_min}")
    return f"target_occupancy_t_plus_{horizon_min}m"
