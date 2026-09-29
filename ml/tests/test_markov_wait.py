from __future__ import annotations

import numpy as np

from ml.src.markov_wait import propagate_busy_probability, wait_distribution


def test_markov_propagation_matches_the_two_state_recursion():
    busy = propagate_busy_probability(1.0, [0.4, 0.4], [0.1, 0.1])
    assert np.allclose(busy, [1.0, 0.6, 0.4])


def test_wait_distribution_preserves_total_probability_mass():
    busy = propagate_busy_probability(1.0, [0.5, 0.5], [0.0, 0.0])
    result = wait_distribution(busy, [0.5, 0.5], arrival_step=0)

    assert result.probability_wait_zero == 0
    assert result.wait_minutes == (5, 10)
    assert np.allclose(result.probability_first_available, [0.5, 0.25])
    assert result.probability_still_busy_after_horizon == 0.25
    assert (
        sum(result.probability_first_available) + result.probability_still_busy_after_horizon == 1
    )
