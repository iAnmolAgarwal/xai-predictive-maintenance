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

**The tie test is tolerant, and has to be.** A rank is a counting operation, so
it is a step function of the comparison ``history <= value`` — and the values
being compared are float64 reductions over a rolling window. No such reduction
is bit-identical across platforms: ``a @ b`` lands in whichever BLAS the wheel
was built against (Accelerate on Apple silicon, OpenBLAS on x86-64) and NumPy's
own pairwise summation blocks differently for NEON and AVX2. Two mathematically
equal window slopes therefore came out three ULPs apart between a developer
machine and a CI runner, one count flipped, and a rank moved from 196/223 to
197/223 — a golden fixture failing on a value that was never actually different.

So a history entry counts as "at or below" the query when it is not
*meaningfully* greater:

    history <= value + RANK_RTOL * scale

``scale`` is the feature's own running maximum absolute value, updated with the
current ``|value|`` before the comparison, which is what makes the tolerance
usable for a statistic that cancels towards zero: a slope whose value is 1e-18
because its window is flat still gets a tolerance drawn from the magnitudes that
slope actually reaches, instead of 1e-27. ``RANK_RTOL`` is 1e-9 — about seven
orders of magnitude above float64 rounding noise and, on the real datasets, six
orders below the closest genuinely distinct pair of values a feature produces
(measured on ``air_temp_slope_4h``: ULP neighbour at 3.4e-16 relative, nearest
real neighbour at 5.1e-3).

**Sizing evidence.** The committed ``ai4i`` golden is *identical* for every
``RANK_RTOL`` in [1e-13, 1e-7] — a six-decade plateau, with 1e-9 at its centre.
Outside it the fixture moves: 1 cell at 1e-14 and at 1e-6, 20 cells at 1e-15,
28 cells at 0 (the untolerant comparison), and 12 cells at 1e-5. The plateau is
the whole argument for the constant: any value in it gives the same ranks, so
the choice is not tuned to a fixture.

Regenerating the golden under the tolerance moved a handful of ranks by as much
as ~40 counts (``temp_diff_p95_4h``: 12.56 → 30.94). Those are not noise being
papered over — they are *representational* ties. ``ai4i``'s temperatures are
recorded at 0.1 K resolution, so a difference of two of them takes one of a
small set of values, and the float64 subtraction renders the same intended
difference as two neighbouring doubles depending on the operands. Every one of
those ranks resolves by ``RANK_RTOL`` 1e-14, i.e. they were always ties that the
bit-exact comparison was splitting.

:meth:`quantile` needs no such treatment and deliberately gets none: it sorts
and interpolates rather than counting, so it has no step to fall off, and it
stays the exact inverse-style estimator described below.

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

**Two estimators, one sample apart.** :meth:`PercentileBank.update` returns an
*inclusive rank* — ``count(history <= value) / n * 100``, an empirical CDF —
while :meth:`PercentileBank.quantile` inverts the relationship with
:func:`numpy.nanpercentile`, which interpolates linearly between order
statistics. They are not exact inverses: round-tripping a value through
``quantile(95)`` and back through the rank stays within one sample's worth of
rank, ``100 / n`` percentile points. That is 0.12 points at the 834 rows an
``ai4i`` machine reaches, and 2 points at the 48-sample warmup floor where the
rank is first reported at all. Small either way, but ``xpm.explain`` prints both in
one sentence — "stayed above its 95th percentile" comes from the rank, "sat at
the 97th percentile" is the rank too, while the ``{threshold}`` value beside it
comes from :meth:`quantile` — so the difference is documented rather than
discovered.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from numpy.typing import NDArray

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.features.stats import Float64Array

__all__ = ["RANK_RTOL", "SUPPORTED_ALGORITHMS", "PercentileBank"]

#: Spellings of ``features.percentile_algorithm`` this module serves. Both map
#: to the exact empirical backend; see the module docstring for the measurement
#: that rules the sketch out of the online path.
SUPPORTED_ALGORITHMS: Final[tuple[str, ...]] = ("tdigest", "exact")

_PERCENT: Final[float] = 100.0

#: Relative width of the "indistinguishable from the query" band used by the
#: rank's tie test. Sized to swallow cross-platform float64 reduction noise
#: (~1e-16 relative) with orders of magnitude to spare, while staying far below
#: the separation between values a feature genuinely distinguishes.
RANK_RTOL: Final[float] = 1e-9


class PercentileBank:
    """Exact empirical percentile ranks for one machine's feature vector."""

    __slots__ = ("_block", "_counts", "_history", "_rows", "_scale", "_warmup")

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
        self._scale: Float64Array = np.zeros(n_features, dtype=np.float64)
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

        The comparison carries a :data:`RANK_RTOL` relative band so that a
        history entry which differs from ``values`` only by float64 reduction
        noise counts as a tie on every platform; see the module docstring.
        """
        if values.shape != self._counts.shape:
            raise ValueError(f"expected {self._counts.size} features, got {values.shape}")
        self._append(values)
        observed = ~np.isnan(values)
        self._counts += observed
        # fmax ignores NaN, so a not-yet-computable feature leaves its scale alone.
        self._scale = np.fmax(self._scale, np.abs(values))
        bound = values + RANK_RTOL * self._scale
        below = np.count_nonzero(self._history <= bound[:, None], axis=1).astype(np.float64)
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
        self._scale[:] = 0.0
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
