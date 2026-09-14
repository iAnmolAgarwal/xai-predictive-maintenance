"""The seven window statistics of ``features.stats``.

Every function takes a ``(samples, channels)`` block — the window's rows for all
of a plant's channels at once — and returns one value per channel. Vectorising
across channels rather than across rows is what keeps the online engine's
per-row cost to a fixed, small number of NumPy calls no matter how many channels
a plant has.

Conventions, all of which the golden fixtures pin:

* ``std`` is the sample standard deviation (``ddof=1``), matching
  ``pandas.DataFrame.rolling(...).std()``.
* ``p95`` uses NumPy's default ``"linear"`` interpolation, matching
  ``rolling(...).quantile(0.95)``; it is evaluated with :func:`numpy.partition`
  rather than a full sort.
* ``slope`` is the ordinary-least-squares gradient in channel units **per hour**
  (``features.slope_unit: per_hour``), computed from mean-centred times and
  values so a 2026 epoch timestamp cannot eat the precision.
* ``ewma`` is time-aware: ``alpha = 1 - 2 ** (-dt_hours / halflife_hours)``
  applied recursively with ``adjust=False``, seeded with the first sample. On a
  regular cadence this is exactly ``pandas.Series.ewm(alpha=..., adjust=False)``.
  Timestamps are passed in seconds, like everywhere else in the engine, and the
  elapsed hours are derived from their difference.

A statistic that is undefined for the sample count it is given (``std`` and
``slope`` below two samples) returns ``NaN``, which is how the engine spells
§3.1's "not yet computable".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, cast

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "EWMA_WINDOW_DIVISOR",
    "SECONDS_PER_HOUR",
    "EwmaState",
    "Float64Array",
    "ewma_halflife_hours",
    "maximum",
    "mean",
    "minimum",
    "percentile",
    "slope",
    "std",
    "window_stat",
]

Float64Array = NDArray[np.float64]

#: ``config/settings.yaml`` documents the per-window EWMA halflife as
#: "window_hours/4, floored here" against ``features.ewma_halflife_hours``.
#: The divisor is the shape of that rule rather than a tunable threshold, so it
#: lives here beside the formula it belongs to; the floor is the config leaf.
EWMA_WINDOW_DIVISOR: Final[float] = 4.0

#: Dataset timestamps travel through the engine in seconds; per-hour statistics
#: convert with this.
SECONDS_PER_HOUR: Final[float] = 3600.0


def ewma_halflife_hours(window_hours: float, floor_hours: float) -> float:
    """Per-window halflife: ``window_hours / 4``, floored at ``floor_hours``."""
    return max(window_hours / EWMA_WINDOW_DIVISOR, floor_hours)


def _empty(block: Float64Array) -> Float64Array:
    return np.full(block.shape[1], np.nan, dtype=np.float64)


def mean(block: Float64Array) -> Float64Array:
    """Arithmetic mean per channel."""
    return cast(Float64Array, block.mean(axis=0))


def std(block: Float64Array) -> Float64Array:
    """Sample standard deviation (``ddof=1``) per channel; ``NaN`` below 2 rows."""
    if block.shape[0] < 2:
        return _empty(block)
    return cast(Float64Array, block.std(axis=0, ddof=1))


def minimum(block: Float64Array) -> Float64Array:
    """Window minimum per channel."""
    return cast(Float64Array, block.min(axis=0))


def maximum(block: Float64Array) -> Float64Array:
    """Window maximum per channel."""
    return cast(Float64Array, block.max(axis=0))


def percentile(block: Float64Array, level: float) -> Float64Array:
    """``level``-th percentile per channel, NumPy ``"linear"`` interpolation."""
    rows = block.shape[0]
    if rows == 1:
        return cast(Float64Array, block[0].astype(np.float64, copy=True))
    position = (rows - 1) * (level / 100.0)
    lower = int(np.floor(position))
    upper = min(lower + 1, rows - 1)
    fraction = position - lower
    kth = (lower,) if upper == lower else (lower, upper)
    partitioned = np.partition(block, kth, axis=0)
    low = partitioned[lower]
    high = partitioned[upper]
    return cast(Float64Array, low + fraction * (high - low))


def slope(block: Float64Array, times_hours: Float64Array) -> Float64Array:
    """OLS gradient per channel in channel units per hour; ``NaN`` below 2 rows.

    ``NaN`` is also returned when every sample shares one timestamp, which would
    otherwise be a division by a zero time variance.

    Mean-centring both operands is a conditioning choice, not a determinism one.
    The dot product below is a float64 reduction, and no float64 reduction is
    bit-identical across platforms: ``@`` dispatches to whichever BLAS the wheel
    was built against and NumPy's own pairwise summation blocks differently for
    NEON and AVX2. Rewriting it as an explicit multiply-and-sum would move the
    divergence rather than remove it, at the cost of a temporary the size of the
    window. The engine absorbs the last few ULPs where it actually matters —
    :data:`xpm.features.percentiles.RANK_RTOL`, the one place a float64
    comparison turns into a step function.
    """
    if block.shape[0] < 2:
        return _empty(block)
    centred_times = times_hours - times_hours.mean()
    denominator = float(centred_times @ centred_times)
    if denominator <= 0.0:
        return _empty(block)
    centred_values = block - block.mean(axis=0)
    return cast(Float64Array, (centred_times @ centred_values) / denominator)


def window_stat(stat: str, block: Float64Array, times_hours: Float64Array) -> Float64Array:
    """Dispatch one ``features.stats`` entry over a window block.

    ``ewma`` is excluded: it is recursive over the whole series rather than a
    function of the window, and is maintained by :class:`EwmaState`.
    """
    if stat == "mean":
        return mean(block)
    if stat == "std":
        return std(block)
    if stat == "min":
        return minimum(block)
    if stat == "max":
        return maximum(block)
    if stat == "slope":
        return slope(block, times_hours)
    if stat.startswith("p") and stat[1:].isdigit():
        return percentile(block, float(stat[1:]))
    raise ValueError(f"features.stats contains an unsupported stat {stat!r}")


@dataclass(slots=True)
class EwmaState:
    """Time-aware exponentially weighted mean, one per (window, machine).

    Recursive over every sample the machine has produced, not over the window:
    the window only chooses the halflife. ``update`` is O(channels) and holds no
    history, which is what keeps it O(1) per row.
    """

    halflife_hours: float
    _value: Float64Array | None = field(default=None, init=False, repr=False)
    _last_seconds: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.halflife_hours <= 0.0:
            raise ValueError(f"halflife must be positive, got {self.halflife_hours}")

    @property
    def value(self) -> Float64Array | None:
        """The current EWMA per channel, or ``None`` before the first sample."""
        return self._value

    def update(self, time_seconds: float, row: Float64Array) -> Float64Array:
        """Fold ``row`` in at ``time_seconds`` and return the new EWMA."""
        previous = self._value
        if previous is None:
            self._value = row.astype(np.float64, copy=True)
            self._last_seconds = time_seconds
            return self._value
        elapsed_hours = (time_seconds - self._last_seconds) / SECONDS_PER_HOUR
        if elapsed_hours <= 0.0:
            # A repeated or out-of-order timestamp contributes no decay; the
            # sample still replaces nothing, so the mean is left untouched.
            return previous
        alpha = 1.0 - 2.0 ** (-elapsed_hours / self.halflife_hours)
        self._value = previous + alpha * (row - previous)
        self._last_seconds = time_seconds
        return self._value

    def reset(self) -> None:
        """Forget the series (used when a replay loop starts a new run)."""
        self._value = None
        self._last_seconds = 0.0
