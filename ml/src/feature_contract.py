"""Versioned ML feature contracts shared by dataset and training commands.

The contracts deliberately separate features that can be served today from data
domains that still need a verified real-time source.  A model must never be
trained with a feature that the API cannot reproduce at prediction time.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTRACT_VERSION = "2.1"
LOOKBACK_STEPS = 12
HORIZONS_MIN = tuple(range(5, 61, 5))
INTERVAL_MIN = 5

LAG_FEATURES = tuple(f"lag_{step}" for step in range(1, LOOKBACK_STEPS + 1))
TEMPORAL_FEATURES = (
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "is_weekend",
    "is_public_holiday",
    "is_holiday_period",
)
WEATHER_FEATURES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "is_raining",
)

# These columns are deliberately horizon-specific.  A direct model for +30
# minutes must see the station profile for the calendar bucket at t+30, not
# the bucket at the forecast origin t.
SEASONAL_PRIOR_FEATURES = tuple(f"seasonal_prior_t_plus_{horizon}m" for horizon in HORIZONS_MIN)


@dataclass(frozen=True)
class FeatureProfile:
    name: str
    feature_names: tuple[str, ...]
    required_inputs: tuple[str, ...]
    serving_ready: bool
    serving_reason: str


FEATURE_PROFILES = {
    "baseline": FeatureProfile(
        name="baseline",
        feature_names=LAG_FEATURES,
        required_inputs=("occupancy",),
        serving_ready=True,
        serving_reason="Only validated occupancy history is required.",
    ),
    "temporal": FeatureProfile(
        name="temporal",
        feature_names=(*LAG_FEATURES, *TEMPORAL_FEATURES),
        required_inputs=("occupancy", "calendar"),
        serving_ready=False,
        serving_reason=(
            "Requires a deployment-region calendar provider in the backend; "
            "the current API intentionally serves only the baseline profile."
        ),
    ),
    "seasonal": FeatureProfile(
        name="seasonal",
        feature_names=(*LAG_FEATURES, *SEASONAL_PRIOR_FEATURES),
        required_inputs=("occupancy", "seasonal_profile"),
        serving_ready=True,
        serving_reason=(
            "Uses a frozen station weekday/weekend 5-minute profile bundled "
            "with the model; inference also requires station ID and timestamp."
        ),
    ),
    "context": FeatureProfile(
        name="context",
        feature_names=(*LAG_FEATURES, *TEMPORAL_FEATURES, *WEATHER_FEATURES),
        required_inputs=("occupancy", "calendar", "weather"),
        serving_ready=False,
        serving_reason=(
            "Requires a validated real-time weather feed and station-local feature serving; "
            "do not deploy this profile yet."
        ),
    ),
}


def get_feature_profile(name: str) -> FeatureProfile:
    try:
        return FEATURE_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(FEATURE_PROFILES))
        raise ValueError(f"Unknown feature profile {name!r}; choose one of: {choices}") from exc


def target_column(horizon_min: int) -> str:
    if horizon_min not in HORIZONS_MIN:
        raise ValueError(f"Unsupported horizon: {horizon_min}")
    return f"target_occupancy_t_plus_{horizon_min}m"
