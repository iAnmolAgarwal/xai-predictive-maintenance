"""Consecutive-exceedance hours — the "for 4 consecutive hours" counter.

backend.md §4: a hand-built series with a known 4 h exceedance must report
exactly ``4.0`` hours, and a one-sample dip must reset it. The bank is driven
with percentile ranks directly so the assertions are about the counter's rules
and not about how the ranks were estimated.
"""

from __future__ import annotations

import numpy as np
import pytest

from xpm.config import get_settings
from xpm.features.streak import StreakBank

HOUR = 3600.0
BELOW = 10.0
"""A percentile rank comfortably under ``features.streak_percentile``."""


def _above() -> float:
    return float(get_settings().features.streak_percentile)


def _run(ranks: list[float], *, step_hours: float = 0.5) -> list[float]:
    bank = StreakBank(1)
    return [
        float(bank.update(index * step_hours * HOUR, np.array([rank]))[0])
        for index, rank in enumerate(ranks)
    ]


def test_threshold_and_floor_come_from_settings() -> None:
    features = get_settings().features
    bank = StreakBank(1)
    assert bank.threshold_percentile == pytest.approx(float(features.streak_percentile))
    assert bank.min_hours == pytest.approx(features.streak_min_hours)


def test_a_four_hour_exceedance_reports_exactly_four_hours() -> None:
    """Nine samples half an hour apart span exactly 4.0 h of dataset time."""
    hours = _run([_above()] * 9)
    assert hours[0] == pytest.approx(0.0)
    assert hours[-1] == pytest.approx(4.0)


def test_the_streak_counts_dataset_time_not_rows() -> None:
    """The same 4 h held by three sparse samples still reads 4.0."""
    bank = StreakBank(1)
    above = np.array([_above()])
    assert float(bank.update(0.0, above)[0]) == pytest.approx(0.0)
    assert float(bank.update(2.5 * HOUR, above)[0]) == pytest.approx(2.5)
    assert float(bank.update(4.0 * HOUR, above)[0]) == pytest.approx(4.0)


def test_one_sample_below_resets_the_streak() -> None:
    hours = _run([_above()] * 9 + [BELOW] + [_above()] * 3)
    assert hours[8] == pytest.approx(4.0)
    assert hours[9] == pytest.approx(0.0)
    # The run restarts from the dip, not from the original start.
    assert hours[10] == pytest.approx(0.0)
    assert hours[12] == pytest.approx(1.0)


def test_a_rank_exactly_on_the_threshold_counts_as_exceeding() -> None:
    """ "Above its 95th percentile" is inclusive: a value *at* p95 is on the run."""
    hours = _run([_above(), _above()])
    assert hours[-1] == pytest.approx(0.5)


def test_framing_eligibility_respects_streak_min_hours() -> None:
    floor = get_settings().features.streak_min_hours
    bank = StreakBank(2)
    eligible = bank.framing_eligible(np.array([floor - 0.1, floor]))
    assert eligible.tolist() == [False, True]


def test_a_null_rank_yields_a_null_streak() -> None:
    hours = _run([np.nan, np.nan, _above()])
    assert np.isnan(hours[0])
    assert np.isnan(hours[1])
    assert hours[2] == pytest.approx(0.0)


def test_a_null_rank_mid_run_does_not_extend_the_streak() -> None:
    bank = StreakBank(1)
    above = np.array([_above()])
    bank.update(0.0, above)
    bank.update(2.0 * HOUR, above)
    assert np.isnan(float(bank.update(3.0 * HOUR, np.array([np.nan]))[0]))
    # The unknown row broke the run, so the next exceedance starts from zero.
    assert float(bank.update(4.0 * HOUR, above)[0]) == pytest.approx(0.0)


def test_reset_clears_every_open_streak() -> None:
    bank = StreakBank(1)
    above = np.array([_above()])
    bank.update(0.0, above)
    bank.update(3.0 * HOUR, above)
    bank.reset()
    assert float(bank.update(4.0 * HOUR, above)[0]) == pytest.approx(0.0)


def test_update_rejects_a_wrong_width_vector() -> None:
    bank = StreakBank(3)
    with pytest.raises(ValueError, match="expected 3 features"):
        bank.update(0.0, np.array([1.0]))


def test_bank_rejects_an_empty_vector() -> None:
    with pytest.raises(ValueError, match="at least one feature"):
        StreakBank(0)
