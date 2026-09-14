"""Consecutive-exceedance tracking: "for 4 consecutive hours".

This is the counter behind §3.9's ``consecutive`` framing and behind the
assignment sentence itself — "vibration at 3 kHz exceeded the 95th percentile
for 4 consecutive hours". It is measured in **dataset time**, not in rows, so a
gap in the stream lengthens the streak by the real elapsed time rather than by a
sample count.

Rules, all from ``features``:

* A feature is *exceeding* when its percentile rank (from
  :class:`~xpm.features.percentiles.PercentileBank`) is at or above
  ``features.streak_percentile``. Ranking against the same estimator the
  explanation prints is deliberate: the streak and the "97th percentile" in the
  sentence can never disagree.
* ``consecutive_hours`` is ``now - t_first``, where ``t_first`` is the dataset
  time of the first row of the current unbroken run. A run spanning exactly four
  hours therefore reports exactly ``4.0``.
* One row below the threshold ends the run; the counter drops to ``0.0`` and the
  next exceedance starts a fresh run.
* ``features.streak_min_hours`` is the floor below which §3.9 does not use the
  consecutive framing at all; :meth:`StreakBank.framing_eligible` applies it.
* A feature still inside its percentile warmup has no rank, so its streak is
  ``NaN`` rather than zero.
"""

from __future__ import annotations

import numpy as np

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.features.stats import SECONDS_PER_HOUR, Float64Array

__all__ = ["StreakBank"]


class StreakBank:
    """Consecutive-exceedance hours for one machine's whole feature vector."""

    __slots__ = ("_min_hours", "_start_seconds", "_threshold_percentile")

    def __init__(self, n_features: int, settings: Settings | None = None) -> None:
        if n_features < 1:
            raise ValueError(f"a feature vector needs at least one feature, got {n_features}")
        features = (settings or get_settings()).features
        self._threshold_percentile = float(features.streak_percentile)
        self._min_hours = features.streak_min_hours
        self._start_seconds: Float64Array = np.full(n_features, np.nan, dtype=np.float64)

    @property
    def threshold_percentile(self) -> float:
        """``features.streak_percentile`` — the "Nth percentile" of the sentence."""
        return self._threshold_percentile

    @property
    def min_hours(self) -> float:
        """``features.streak_min_hours``."""
        return self._min_hours

    def update(self, now_seconds: float, ranks: Float64Array) -> Float64Array:
        """Advance every feature's streak and return the hours held.

        ``ranks`` is the percentile-rank vector for this row; ``NaN`` ranks
        (unknown feature or pre-warmup) propagate to ``NaN`` streaks.
        """
        if ranks.shape != self._start_seconds.shape:
            raise ValueError(f"expected {self._start_seconds.size} features, got {ranks.shape}")
        exceeding = ranks >= self._threshold_percentile
        fresh = exceeding & np.isnan(self._start_seconds)
        self._start_seconds = np.where(
            exceeding, np.where(fresh, now_seconds, self._start_seconds), np.nan
        )
        hours = np.where(exceeding, (now_seconds - self._start_seconds) / SECONDS_PER_HOUR, 0.0)
        return np.where(np.isnan(ranks), np.nan, hours)

    def framing_eligible(
        self, hours: Float64Array
    ) -> np.ndarray[tuple[int, ...], np.dtype[np.bool_]]:
        """Which features may use §3.9's ``consecutive`` framing this row."""
        return hours >= self._min_hours

    def reset(self) -> None:
        """Forget every open streak (used when a replay loop starts a new run)."""
        self._start_seconds[:] = np.nan
