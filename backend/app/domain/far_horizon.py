"""Occupancy beyond the model horizon: the T+30 prediction anchored to the station profile.

The model only sees 30 minutes ahead. Further out, the deviation of the T+30 prediction from the
station's typical occupancy at that time decays towards zero, so the forecast converges to the
historical profile:

    occ(h) = profile(h) + (anchor - profile(30)) * exp(-(h - 30) / tau)
"""

from __future__ import annotations

import math

MODEL_HORIZON_MIN = 30
# Arrival can be up to 30 minutes ahead and the wait rule looks 30 minutes past it.
MAX_FORECAST_HORIZON_MIN = 60
DEFAULT_TAU_MIN = 30.0


def blend_with_profile(
    anchor_ratio: float,
    profile_at_anchor: float,
    profile_at_horizon: float,
    horizon_min: int,
    *,
    tau_min: float = DEFAULT_TAU_MIN,
) -> float:
    """Occupancy ratio at `horizon_min` (> 30) from the T+30 prediction and the profile."""
    if horizon_min < MODEL_HORIZON_MIN:
        raise ValueError("far-horizon blending starts at the model horizon")
    if tau_min <= 0:
        raise ValueError("tau_min must be positive")
    deviation = anchor_ratio - profile_at_anchor
    decay = math.exp(-(horizon_min - MODEL_HORIZON_MIN) / tau_min)
    return min(1.0, max(0.0, profile_at_horizon + deviation * decay))


def smooth_profile(
    mean_ratio: float, sample_count: int, station_mean_ratio: float, *, strength: float = 2.0
) -> float:
    """Pull a noisy cell mean towards the station mean (few samples per week-slot)."""
    if sample_count <= 0:
        return station_mean_ratio
    return (sample_count * mean_ratio + strength * station_mean_ratio) / (
        sample_count + strength
    )
