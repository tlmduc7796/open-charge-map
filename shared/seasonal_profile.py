"""Frozen seasonal-profile semantics shared by ML training and API inference.

The profile is fitted only from the training interval. Every training,
validation, test and online row then computes the same target-time feature from
that frozen profile. Keeping this calculation here prevents a training-serving
skew caused by two subtly different smoothing implementations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

DEFAULT_SEASONAL_PRIOR = 0.5
SEASONAL_SMOOTHING = 8.0
INTERVAL_MIN = 5


def seasonal_bucket(timestamp: datetime) -> tuple[int, int]:
    """Return the weekday/weekend flag and five-minute time-of-day bucket."""
    return int(timestamp.weekday() >= 5), timestamp.hour * 12 + timestamp.minute // INTERVAL_MIN


def seasonal_prior(
    profile: dict[str, Any], station_id: str, forecast_at: datetime, horizon_min: int
) -> float:
    """Return the smoothed profile value for the horizon's target timestamp."""
    target = forecast_at + timedelta(minutes=horizon_min)
    is_weekend, slot = seasonal_bucket(target)
    default = float(profile.get("default", DEFAULT_SEASONAL_PRIOR))
    station = profile.get("station_means", {}).get(station_id, {})
    station_mean = float(station.get("mean", default))
    bucket = profile.get("buckets", {}).get(f"{station_id}|{is_weekend}|{slot}", {})
    count = int(bucket.get("count", 0))
    mean = float(bucket.get("mean", station_mean))
    smoothing = float(profile.get("smoothing", SEASONAL_SMOOTHING))
    return (mean * count + smoothing * station_mean) / (count + smoothing)
