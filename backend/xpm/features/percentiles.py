"""Per-feature historical percentile tracking.

This is what lets the explanation templater say "sat at the 97th percentile of
this machine's own history" with a real number (§1, §3.9), and what the streak
counter tests against for "above its 95th percentile".

**Backend choice, and why it is not the `tdigest` package.** ``settings.yaml``
names ``features.percentile_algorithm: tdigest``. A t-digest is the right shape
for an unbounded stream, but the online engine has to rank *every* feature of
*every* row — 154 features for ``ai4i``, 198 for ``ims`` — and the PyPI
``tdigest`` package costs, measured on this machine at
``features.percentile_compression = 200``, **9.3 µs per ``update`` and 773 µs
per ``cdf``**. That is ~120 ms per row, i.e. ~38 rows/s against a 5 000 rows/s
budget: three orders of magnitude short.

:class:`PercentileBank` therefore keeps the machine's own history as one
**feature-major** ``(features, capacity)`` NumPy matrix and computes **exact**
empirical percentile ranks for all features in a single vectorised comparison
per row. Feature-major because the reduction then runs along contiguous memory,
which measured ~40 % faster than the row-major layout; unused capacity is
``NaN``-filled so the comparison can run over the whole contiguous block, and
``NaN`` never satisfies ``<=``.

The exact tracker is both faster and strictly more accurate than the sketch, and
it is affordable because the history it ranks against is bounded by the dataset:
834 rows per ``ai4i`` machine and 984 per ``ims`` bearing per run, ~1 MB per
machine, and a replay loop starts a new run (R12) with a fresh engine.
``features.percentile_compression`` is still honoured — it is the block the
history matrix grows by, so the setting governs the allocation granularity of
the estimator it names.

Warmup. Below ``features.percentile_warmup_samples`` observations of a given
feature the rank is ``NaN``, never ``0`` (§3.1, §3.6) — and the count is kept
per feature, so a 24 h feature that is still null warms up later than a 1 h one.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.features.stats import Float64Array

__all__ = ["SUPPORTED_ALGORITHMS", "PercentileBank"]

#: Spellings of ``features.percentile_algorithm`` this module serves. Both map
#: to the exact empirical backend; see the module docstring for the measurement
#: that rules the sketch out of the online path.
SUPPORTED_ALGORITHMS: Final[tuple[str, ...]] = ("tdigest", "exact")

_PERCENT: Final[float] = 100.0


class PercentileBank:
    """Exact empirical percentile ranks for one machine's feature vector."""

    __slots__ = ("_block", "_counts", "_history", "_rows", "_warmup")

    def __init__(self, n_features: int, settings: Settings | None = None) -> None:
        if n_features < 1:
            raise ValueError(f"a feature vector needs at least one feature, got {n_features}")
        features = (settings or get_settings()).features
        if features.percentile_algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(
                f"features.percentile_algorithm {features.percentile_algorithm!r} is not one of "
                f"{SUPPORTED_ALGORITHMS}"
            )
        self._warmup = features.percentile_warmup_samples
        self._block = features.percentile_compression
        self._history: Float64Array = np.full((n_features, self._block), np.nan, dtype=np.float64)
        self._counts: NDArray[np.int64] = np.zeros(n_features, dtype=np.int64)
        self._rows = 0

    def __len__(self) -> int:
        return self._rows

    @property
    def counts(self) -> NDArray[np.int64]:
        """Observations seen per feature, ignoring the ``NaN`` ones."""
        return self._counts

    def update(self, values: Float64Array) -> Float64Array:
        """Record ``values`` and return each feature's percentile rank, 0-100.

        The rank is inclusive of the sample just recorded, so a feature at its
        all-time high reports exactly 100. Features that are ``NaN`` (not yet
        computable) or still inside the warmup report ``NaN``.
        """
        if values.shape != self._counts.shape:
            raise ValueError(f"expected {self._counts.size} features, got {values.shape}")
        self._append(values)
        observed = ~np.isnan(values)
        self._counts += observed
        below = np.count_nonzero(self._history <= values[:, None], axis=1).astype(np.float64)
        with np.errstate(invalid="ignore", divide="ignore"):
            ranks: Float64Array = below / self._counts * _PERCENT
        ranks[~observed] = np.nan
        ranks[self._counts < self._warmup] = np.nan
        return ranks

    def quantile(self, index: int, level: float) -> float | None:
        """The ``level``-th percentile of feature ``index``'s own history.

        ``None`` before warmup. Used off the hot path — the templater needs it
        only for the handful of features a rendered explanation names.
        """
        if not 0 <= index < self._counts.size:
            raise IndexError(f"feature index {index} out of range")
        if int(self._counts[index]) < self._warmup:
            return None
        history = self._history[index, : self._rows]
        return float(np.nanpercentile(history, level))

    def reset(self) -> None:
        """Forget the history (used when a replay loop starts a new run)."""
        self._rows = 0
        self._counts[:] = 0
        self._history[:] = np.nan

    def _append(self, values: Float64Array) -> None:
        if self._rows == self._history.shape[1]:
            grown = np.full(
                (self._counts.size, self._history.shape[1] + self._block), np.nan, dtype=np.float64
            )
            grown[:, : self._rows] = self._history[:, : self._rows]
            self._history = grown
        self._history[:, self._rows] = values
        self._rows += 1
