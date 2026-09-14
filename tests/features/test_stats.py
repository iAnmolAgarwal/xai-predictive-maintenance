"""Each of the seven ``features.stats`` against a NumPy/pandas reference.

The fixed 100-point block is the reference sample backend.md §4 asks for. Every
assertion compares against the library implementation the golden fixtures were
generated to agree with, so a change of convention (``ddof``, percentile
interpolation, slope units) fails here rather than silently moving every number
in the dashboard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xpm.config import get_settings
from xpm.features.stats import (
    EWMA_WINDOW_DIVISOR,
    EwmaState,
    ewma_halflife_hours,
    maximum,
    mean,
    minimum,
    percentile,
    slope,
    std,
    window_stat,
)

ROWS = 100
CHANNELS = 3


@pytest.fixture(scope="module")
def block() -> np.ndarray:
    """A fixed 100 x 3 sample block; seeded, so the numbers never move."""
    generator = np.random.default_rng(20260914)
    return generator.normal(loc=[300.0, 40.0, 0.02], scale=[2.0, 9.0, 0.004], size=(ROWS, CHANNELS))


@pytest.fixture(scope="module")
def times_hours() -> np.ndarray:
    """A regular 5-minute cadence, the ``ai4i`` row interval, in hours."""
    return np.arange(ROWS, dtype=np.float64) * (300.0 / 3600.0)


def test_mean_matches_numpy(block: np.ndarray) -> None:
    np.testing.assert_allclose(mean(block), np.mean(block, axis=0), rtol=0, atol=0)


def test_std_is_the_sample_deviation(block: np.ndarray) -> None:
    np.testing.assert_allclose(std(block), np.std(block, axis=0, ddof=1), rtol=0, atol=0)


def test_std_matches_pandas_rolling(block: np.ndarray) -> None:
    """pandas' rolling std is ddof=1; ours must be the same convention."""
    expected = pd.DataFrame(block).rolling(ROWS).std().iloc[-1].to_numpy()
    np.testing.assert_allclose(std(block), expected, rtol=1e-12, atol=1e-12)


def test_min_and_max(block: np.ndarray) -> None:
    np.testing.assert_allclose(minimum(block), np.min(block, axis=0), rtol=0, atol=0)
    np.testing.assert_allclose(maximum(block), np.max(block, axis=0), rtol=0, atol=0)


def test_percentile_matches_numpy_linear(block: np.ndarray) -> None:
    for level in (50.0, 75.0, 95.0, 99.0):
        np.testing.assert_allclose(
            percentile(block, level),
            np.percentile(block, level, axis=0, method="linear"),
            rtol=1e-12,
            atol=1e-12,
        )


def test_percentile_matches_pandas_quantile(block: np.ndarray) -> None:
    expected = pd.DataFrame(block).rolling(ROWS).quantile(0.95).iloc[-1].to_numpy()
    np.testing.assert_allclose(percentile(block, 95.0), expected, rtol=1e-12, atol=1e-12)


def test_percentile_of_a_single_row_is_that_row(block: np.ndarray) -> None:
    np.testing.assert_allclose(percentile(block[:1], 95.0), block[0], rtol=0, atol=0)


def test_slope_matches_least_squares(block: np.ndarray, times_hours: np.ndarray) -> None:
    expected = np.array(
        [np.polyfit(times_hours, block[:, column], 1)[0] for column in range(CHANNELS)]
    )
    np.testing.assert_allclose(slope(block, times_hours), expected, rtol=1e-9, atol=1e-12)


def test_slope_is_per_hour_not_per_row(times_hours: np.ndarray) -> None:
    """A ramp of 1 unit per row on a 5-minute cadence is 12 units per hour."""
    ramp = np.arange(ROWS, dtype=np.float64).reshape(-1, 1)
    np.testing.assert_allclose(slope(ramp, times_hours), [12.0], rtol=1e-12, atol=1e-12)
    assert get_settings().features.slope_unit == "per_hour"


def test_slope_survives_a_2026_epoch_offset(block: np.ndarray, times_hours: np.ndarray) -> None:
    """Mean-centring means a 490 000-hour epoch offset changes nothing."""
    offset = times_hours + pd.Timestamp("2026-01-01T00:00:00Z").timestamp() / 3600.0
    np.testing.assert_allclose(
        slope(block, offset), slope(block, times_hours), rtol=1e-9, atol=1e-12
    )


def test_std_and_slope_are_null_below_two_samples(block: np.ndarray) -> None:
    assert np.isnan(std(block[:1])).all()
    assert np.isnan(slope(block[:1], np.zeros(1))).all()


def test_slope_is_null_when_time_does_not_advance(block: np.ndarray) -> None:
    frozen = np.zeros(ROWS, dtype=np.float64)
    assert np.isnan(slope(block, frozen)).all()


def test_window_stat_dispatches_every_configured_stat(
    block: np.ndarray, times_hours: np.ndarray
) -> None:
    """Every entry of ``features.stats`` except the recursive one resolves."""
    for stat in get_settings().features.stats:
        if stat == "ewma":
            continue
        computed = window_stat(stat, block, times_hours)
        assert computed.shape == (CHANNELS,)
        assert np.isfinite(computed).all()


def test_window_stat_rejects_an_unknown_stat(block: np.ndarray, times_hours: np.ndarray) -> None:
    with pytest.raises(ValueError, match="unsupported stat"):
        window_stat("median", block, times_hours)


def test_ewma_halflife_floors_at_the_configured_value() -> None:
    floor = get_settings().features.ewma_halflife_hours
    assert ewma_halflife_hours(1.0, floor) == floor
    assert ewma_halflife_hours(4.0, floor) == max(4.0 / EWMA_WINDOW_DIVISOR, floor)
    assert ewma_halflife_hours(24.0, floor) == 24.0 / EWMA_WINDOW_DIVISOR


def test_ewma_matches_pandas_on_a_regular_cadence(
    block: np.ndarray, times_hours: np.ndarray
) -> None:
    """Constant spacing makes alpha constant, which is pandas' ``adjust=False``."""
    halflife = 1.0
    step = float(times_hours[1] - times_hours[0])
    alpha = 1.0 - 2.0 ** (-step / halflife)
    state = EwmaState(halflife)
    produced = np.vstack(
        [state.update(float(t) * 3600.0, block[i]) for i, t in enumerate(times_hours)]
    )
    expected = pd.DataFrame(block).ewm(alpha=alpha, adjust=False).mean().to_numpy()
    np.testing.assert_allclose(produced, expected, rtol=1e-12, atol=1e-12)


def test_ewma_seeds_on_the_first_sample_and_decays_with_gaps(block: np.ndarray) -> None:
    state = EwmaState(2.0)
    np.testing.assert_allclose(state.update(0.0, block[0]), block[0], rtol=0, atol=0)
    # Exactly one halflife (2 h) later the mean sits halfway to the new sample.
    after = state.update(2.0 * 3600.0, block[1])
    np.testing.assert_allclose(after, (block[0] + block[1]) / 2.0, rtol=1e-12, atol=1e-12)


def test_ewma_ignores_a_non_advancing_timestamp(block: np.ndarray) -> None:
    state = EwmaState(1.0)
    first = state.update(0.0, block[0]).copy()
    np.testing.assert_allclose(state.update(0.0, block[1]), first, rtol=0, atol=0)


def test_ewma_reset_forgets_the_series(block: np.ndarray) -> None:
    state = EwmaState(1.0)
    state.update(0.0, block[0])
    assert state.value is not None
    state.reset()
    assert state.value is None
    np.testing.assert_allclose(state.update(5.0 * 3600.0, block[2]), block[2], rtol=0, atol=0)


def test_ewma_rejects_a_non_positive_halflife() -> None:
    with pytest.raises(ValueError, match="halflife must be positive"):
        EwmaState(0.0)
