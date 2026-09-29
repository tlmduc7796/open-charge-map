"""Transparent Markov post-processing for occupancy-to-wait distributions.

This module implements the mathematical layer described in
Reference/LSTM_Markov_head_thoi_gian_cho.md.  It contains no trainable model:
an occupancy predictor or LSTM-Markov head supplies transition probabilities,
then this module turns them into calibrated, inspectable wait metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class WaitDistribution:
    arrival_step: int
    busy_probability_at_arrival: float
    probability_wait_zero: float
    wait_minutes: tuple[int, ...]
    probability_first_available: tuple[float, ...]
    probability_still_busy_after_horizon: float
    expected_wait_within_horizon_min: float


def _probabilities(values: np.ndarray | list[float], name: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array):
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence")
    if not np.isfinite(array).all() or not ((0 <= array) & (array <= 1)).all():
        raise ValueError(f"{name} must contain finite probabilities in [0, 1]")
    return array


def propagate_busy_probability(
    initial_busy_probability: float,
    release_probability: np.ndarray | list[float],
    occupy_probability: np.ndarray | list[float],
) -> np.ndarray:
    """Return π_0..π_K from per-step busy→free and free→busy probabilities."""
    if not 0 <= initial_busy_probability <= 1:
        raise ValueError("initial_busy_probability must be in [0, 1]")
    release = _probabilities(release_probability, "release_probability")
    occupy = _probabilities(occupy_probability, "occupy_probability")
    if len(release) != len(occupy):
        raise ValueError("release_probability and occupy_probability must have equal length")
    busy = np.empty(len(release) + 1, dtype=float)
    busy[0] = initial_busy_probability
    for index, (release_at_step, occupy_at_step) in enumerate(zip(release, occupy), start=1):
        previous = busy[index - 1]
        busy[index] = previous * (1 - release_at_step) + (1 - previous) * occupy_at_step
    return busy


def wait_distribution(
    busy_probability: np.ndarray | list[float],
    release_probability: np.ndarray | list[float],
    *,
    arrival_step: int,
    interval_min: int = 5,
) -> WaitDistribution:
    """Compute discrete first-availability probabilities for an arrival step.

    ``release_probability[k]`` is the transition from step ``k`` to ``k + 1``.
    Re-occupation does not affect a user's wait once their first free port has
    appeared, so only the release branch appears in this conditional survival.
    """
    busy = _probabilities(busy_probability, "busy_probability")
    release = _probabilities(release_probability, "release_probability")
    if len(busy) != len(release) + 1:
        raise ValueError("busy_probability must have one more item than release_probability")
    if interval_min <= 0:
        raise ValueError("interval_min must be positive")
    if not 0 <= arrival_step < len(release):
        raise ValueError("arrival_step must allow at least one future transition")

    busy_at_arrival = float(busy[arrival_step])
    still_busy = busy_at_arrival
    wait_minutes: list[int] = []
    first_available: list[float] = []
    for transition in range(arrival_step, len(release)):
        probability = still_busy * float(release[transition])
        first_available.append(probability)
        wait_minutes.append((transition - arrival_step + 1) * interval_min)
        still_busy *= 1 - float(release[transition])

    expected_within_horizon = sum(
        minutes * probability for minutes, probability in zip(wait_minutes, first_available)
    )
    return WaitDistribution(
        arrival_step=arrival_step,
        busy_probability_at_arrival=busy_at_arrival,
        probability_wait_zero=1 - busy_at_arrival,
        wait_minutes=tuple(wait_minutes),
        probability_first_available=tuple(first_available),
        probability_still_busy_after_horizon=still_busy,
        expected_wait_within_horizon_min=expected_within_horizon,
    )
