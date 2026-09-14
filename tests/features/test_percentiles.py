"""Historical percentile tracking: accuracy, warmup and determinism.

backend.md §4 asks for the estimate to be within one percentile point of the
exact percentile over 10 000 samples and to be ``null`` below
``features.percentile_warmup_samples``. :class:`PercentileBank` computes the
exact empirical rank, so the accuracy assertion holds with a wide margin — the
test keeps §4's tolerance as the contract and additionally pins exactness, which
is what the explanation sentence's "97th percentile" depends on.
"""

from __future__ import annotations

import numpy as np
import pytest

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.features.percentiles import RANK_RTOL, SUPPORTED_ALGORITHMS, PercentileBank

SAMPLES = 10_000
TOLERANCE_PERCENTILE_POINTS = 1.0


def _settings() -> Settings:
    return get_settings()


def _exact_rank(history: np.ndarray, value: float) -> float:
    return float(np.count_nonzero(history <= value)) / history.size * 100.0


def _ranks(values: np.ndarray) -> np.ndarray:
    """Replay a one-feature series and collect its ranks."""
    bank = PercentileBank(1)
    return np.array([float(bank.update(np.array([value]))[0]) for value in values])


def test_ranks_survive_one_ulp_of_platform_noise() -> None:
    """The CI failure this guards: a tie split by float64 reduction order.

    ``air_temp_slope_4h`` produced two mathematically equal window slopes that
    landed three ULPs apart between arm64 and x86-64, flipping one count and
    moving a rank from 196/223 to 197/223. Perturbing every value by a ULP in
    the direction least favourable to the tie must change no rank at all.
    """
    generator = np.random.default_rng(20260915)
    base = generator.normal(size=300)
    # Structural repeats are what actually produces the ties: the same window
    # contents give the same statistic twice.
    base[150:] = base[:150]

    up = np.nextafter(base, np.inf)
    down = np.nextafter(base, -np.inf)
    alternating = np.where(np.arange(base.size) % 2 == 0, up, down)

    reference = _ranks(base)
    for perturbed in (up, down, alternating):
        np.testing.assert_array_equal(_ranks(perturbed), reference)


def test_the_tie_band_does_not_swallow_distinct_values() -> None:
    """A tolerance wide enough to hide a real difference would be a bug.

    Values a thousand times further apart than ``RANK_RTOL`` must still rank
    apart; values inside the band must tie.
    """
    warmup = _settings().features.percentile_warmup_samples
    bank = PercentileBank(1)
    for _ in range(warmup):
        bank.update(np.array([1.0]))
    outside = float(bank.update(np.array([1.0 - RANK_RTOL * 1000.0]))[0])
    inside = float(bank.update(np.array([1.0 - RANK_RTOL / 1000.0]))[0])
    assert outside < 100.0
    assert inside == pytest.approx(100.0)


def test_ranks_match_the_exact_empirical_percentile() -> None:
    generator = np.random.default_rng(4242)
    draws = generator.normal(size=SAMPLES)
    bank = PercentileBank(1)
    ranks: list[float] = []
    for value in draws:
        ranks.append(float(bank.update(np.array([value]))[0]))

    for position in (SAMPLES // 4, SAMPLES // 2, SAMPLES - 1):
        expected = _exact_rank(draws[: position + 1], float(draws[position]))
        assert abs(ranks[position] - expected) <= TOLERANCE_PERCENTILE_POINTS
        assert ranks[position] == pytest.approx(expected, abs=1e-12)


def test_a_new_all_time_high_ranks_at_one_hundred() -> None:
    bank = PercentileBank(1)
    warmup = _settings().features.percentile_warmup_samples
    for step in range(warmup):
        bank.update(np.array([float(step)]))
    assert float(bank.update(np.array([1e6]))[0]) == pytest.approx(100.0)


def test_ranks_are_null_below_warmup() -> None:
    features = _settings().features
    bank = PercentileBank(1)
    for step in range(features.percentile_warmup_samples - 1):
        assert np.isnan(bank.update(np.array([float(step)]))).all(), step
    assert not np.isnan(bank.update(np.array([1.0]))).any()
    assert len(bank) == features.percentile_warmup_samples


def test_each_feature_warms_up_on_its_own_count() -> None:
    """A 24 h feature that is still null must not borrow a 1 h feature's count."""
    warmup = _settings().features.percentile_warmup_samples
    bank = PercentileBank(2)
    for step in range(warmup):
        ranks = bank.update(np.array([float(step), np.nan]))
    assert not np.isnan(ranks[0])
    assert np.isnan(ranks[1])
    assert bank.counts.tolist() == [warmup, 0]


def test_null_values_never_become_a_rank() -> None:
    warmup = _settings().features.percentile_warmup_samples
    bank = PercentileBank(1)
    for step in range(warmup):
        bank.update(np.array([float(step)]))
    assert np.isnan(bank.update(np.array([np.nan]))[0])


def test_ranks_are_deterministic_for_a_given_input_order() -> None:
    generator = np.random.default_rng(11)
    draws = generator.normal(size=500)

    def run() -> list[float]:
        bank = PercentileBank(1)
        return [float(bank.update(np.array([value]))[0]) for value in draws]

    first, second = run(), run()
    # assert_array_equal treats NaN as equal to NaN, which is what "same nulls
    # in the same places" means here.
    np.testing.assert_array_equal(np.array(first), np.array(second))


def test_quantile_matches_numpy_after_warmup() -> None:
    generator = np.random.default_rng(99)
    draws = generator.normal(size=1000)
    bank = PercentileBank(1)
    for value in draws:
        bank.update(np.array([value]))
    for level in _settings().features.percentile_levels:
        assert bank.quantile(0, float(level)) == pytest.approx(
            float(np.percentile(draws, float(level))), abs=1e-12
        )


def test_quantile_is_null_before_warmup() -> None:
    bank = PercentileBank(1)
    bank.update(np.array([1.0]))
    assert bank.quantile(0, 95.0) is None


def test_quantile_rejects_an_out_of_range_feature() -> None:
    bank = PercentileBank(2)
    with pytest.raises(IndexError, match="out of range"):
        bank.quantile(5, 95.0)


def test_history_grows_past_its_initial_block() -> None:
    """``features.percentile_compression`` is the growth block, not a cap."""
    block = _settings().features.percentile_compression
    bank = PercentileBank(1)
    for step in range(block * 2 + 3):
        bank.update(np.array([float(step)]))
    assert len(bank) == block * 2 + 3
    assert bank.quantile(0, 50.0) == pytest.approx(float(block) + 1.0)


def test_reset_forgets_the_history() -> None:
    warmup = _settings().features.percentile_warmup_samples
    bank = PercentileBank(1)
    for step in range(warmup + 5):
        bank.update(np.array([float(step)]))
    bank.reset()
    assert len(bank) == 0
    assert bank.counts.tolist() == [0]
    assert np.isnan(bank.update(np.array([1.0]))[0])


def test_update_rejects_a_wrong_width_vector() -> None:
    bank = PercentileBank(3)
    with pytest.raises(ValueError, match="expected 3 features"):
        bank.update(np.array([1.0]))


def test_bank_rejects_an_empty_vector() -> None:
    with pytest.raises(ValueError, match="at least one feature"):
        PercentileBank(0)


def test_configured_algorithm_is_supported() -> None:
    assert _settings().features.percentile_algorithm in SUPPORTED_ALGORITHMS


def test_an_unknown_algorithm_is_rejected() -> None:
    settings = _settings().model_copy(
        update={"features": _settings().features.model_copy(update={"percentile_algorithm": "p2"})}
    )
    with pytest.raises(ValueError, match="percentile_algorithm"):
        PercentileBank(1, settings)
