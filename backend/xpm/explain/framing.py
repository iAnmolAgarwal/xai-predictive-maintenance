"""Which of §3.9's four framings a feature gets, and the numbers that fill it.

The framing *family* is declared once, per feature, by
:mod:`xpm.features.registry` from ``(stat, channel)`` — §3.9's table. This
module resolves the declared family into the framing actually rendered for one
feature at one dataset instant, because two of the rows in that table are
conditional:

* ``p95`` / ``max`` are declared ``percentile`` and carry
  ``consecutive_eligible``; they are **promoted to** ``consecutive`` once the
  streak counter reaches ``features.streak_min_hours``, which is what makes the
  assignment's own sentence ("above the 95th percentile for 4 consecutive
  hours") come out of real data rather than out of a hardcoded string;
* a ``percentile`` clause needs a percentile, and during
  ``features.percentile_warmup_samples`` there is not one. The percentile rank
  is genuinely unknown then, never zero (§3.1), so the clause **degrades to**
  ``threshold``, which needs nothing but the value and a band.

The degradation ladder is ``consecutive -> percentile -> trend -> threshold``
and it terminates: ``threshold`` renders from the value and the band alone, and
a band always exists because every :class:`~xpm.contracts.common.ChannelSpec`
carries nominal bounds.

**Where "historical percentile" comes from.** Every feature in the vector —
not only the ``pNN`` stats — is ranked against that machine's own history by
:class:`~xpm.features.percentiles.PercentileBank`, so
``ShapContribution.percentile`` is a measured empirical rank for a ``mean`` or
a ``slope`` feature exactly as it is for a ``p95`` one. It is ``None``, never a
filled-in number, when the feature is still inside the warm-up window or when
the caller supplies no rank (a what-if override, whose hypothetical value has no
place in the machine's history).

**Where the band comes from.** ``threshold`` and ``consecutive`` quote a number
the value is compared against. In order of preference:

1. the machine's own history — the ``features.streak_percentile`` quantile as
   the ceiling and its complement as the floor, which is the same estimator the
   streak counter tests against, so the sentence and the streak can never
   disagree;
2. the source channel's nominal bounds, when no history is available (a fresh
   machine, or a what-if recompute performed without the percentile bank).

Every number in this module comes from ``features.*``; the only literal is the
midpoint of the 0-100 percentile scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from xpm.contracts.common import Direction, Framing
from xpm.contracts.settings import Settings
from xpm.features.registry import FeatureMeta
from xpm.features.stats import SECONDS_PER_HOUR

__all__ = [
    "ClauseFacts",
    "band_for",
    "direction_from_shap",
    "history_levels",
    "resolve_clause",
]

#: The midpoint of the 0-100 percentile scale. Above it a level reads as "sat
#: at"; below it, as "fell to". Not a tunable: it is the definition of the
#: median, not a threshold anyone would want to move.
MEDIAN_PERCENTILE: Final[float] = 50.0

#: The top of the percentile scale, used to mirror ``features.streak_percentile``
#: into the matching low-side quantile (95 -> 5).
FULL_PERCENTILE: Final[float] = 100.0


@dataclass(frozen=True, slots=True)
class ClauseFacts:
    """The resolved framing of one feature plus every number its clause quotes.

    This is the intermediate between the raw feature vector and
    :class:`~xpm.contracts.rest.ShapContribution`: the contribution's
    ``framing``, ``direction``, ``percentile``, ``consecutive_hours``,
    ``threshold`` and ``value`` fields are copied straight off it, which is what
    makes "the numbers in the sentence match the numbers on screen" a property
    of construction rather than a coincidence.
    """

    meta: FeatureMeta
    framing: Framing
    direction: Direction
    value: float | None
    percentile: float | None
    consecutive_hours: float | None
    threshold: float | None
    window_mean: float | None
    """The ``mean`` feature of the same channel and window, for ``{rate}``."""
    window_hours: float
    """The span ``{window}`` names: the feature's own window, or one dataset row
    for a raw channel."""
    band: tuple[float, float] | None = None
    """Set only on the ``in_band`` rung, where the clause quotes both bounds."""

    @property
    def in_band(self) -> bool:
        """Whether this is the non-§3.9 "inside its normal band" clause."""
        return self.band is not None

    @property
    def renderable(self) -> bool:
        """Whether a §3.9 template can be filled for this feature.

        ``False`` only when the feature has no value at all — a window still
        short of ``features.min_window_coverage``. Such a feature can still
        carry a SHAP contribution, so the bar is drawn, but no clause claims a
        level it does not have.
        """
        return self.value is not None


def direction_from_shap(shap_value: float) -> Direction:
    """The waterfall glyph: which side of the base value the bar sits on."""
    return "up" if shap_value >= 0.0 else "down"


def band_for(
    meta: FeatureMeta,
    *,
    history_band: tuple[float, float] | None,
) -> tuple[float, float]:
    """``(floor, ceiling)`` for a threshold-style clause.

    The machine's own history wins; the channel's nominal bounds are the
    fallback. A history band with a floor above its ceiling (possible only from
    a caller-supplied mapping) is rejected rather than silently reordered.
    """
    if history_band is not None:
        floor, ceiling = history_band
        if floor > ceiling:
            raise ValueError(f"{meta.name}: history band floor {floor} exceeds ceiling {ceiling}")
        return floor, ceiling
    return meta.nominal_min, meta.nominal_max


def resolve_clause(
    meta: FeatureMeta,
    *,
    value: float | None,
    percentile: float | None,
    streak_hours: float | None,
    history_band: tuple[float, float] | None,
    window_mean: float | None,
    settings: Settings,
) -> ClauseFacts:
    """Resolve one feature's framing and the numbers its clause will quote.

    The ladder, in order, with the condition each rung needs:

    1. ``consecutive`` — the feature is streak-eligible, its streak has reached
       ``features.streak_min_hours`` and it has a percentile rank;
    2. ``trend`` — the declared family for a ``slope``, which reports a rate and
       needs no rank;
    3. ``percentile`` — the declared family for a level statistic, given a rank;
    4. ``threshold`` against the channel's **nominal** bounds — the value is
       outside the range the channel is specified for, which is the strongest
       and most interesting thing that can be said about it;
    5. ``percentile`` again — a declared-threshold feature inside its nominal
       range still has a true and more informative statement available if it has
       a rank. This rung is why a raw channel usually reads as a percentile
       clause: quoting the machine's own 95th percentile as a "ceiling" beside a
       value at its 98th percentile says the same thing twice;
    6. ``threshold`` against the **history** band — no rank, but the value is
       outside what this machine normally does (a what-if slider pushed past the
       machine's own range);
    7. ``in_band`` — nothing above applies. :attr:`ClauseFacts.in_band` marks it
       and :mod:`xpm.explain.narrative` renders the one non-§3.9 clause in the
       system, because both §3.9 threshold templates would assert a crossing
       that did not happen. A what-if slider parked mid-range is the common case;
    8. no value at all — the bar is drawn, no level is quoted.
    """
    floor, ceiling = band_for(meta, history_band=history_band)
    nominal_floor, nominal_ceiling = meta.nominal_min, meta.nominal_max

    if value is None:
        return ClauseFacts(
            meta=meta,
            framing=meta.framing,
            direction="up",
            value=None,
            percentile=percentile,
            consecutive_hours=streak_hours,
            threshold=None,
            window_mean=window_mean,
            window_hours=_window_hours(meta, settings),
        )

    def facts(
        framing: Framing,
        direction: Direction,
        threshold: float | None,
        band: tuple[float, float] | None = None,
    ) -> ClauseFacts:
        return ClauseFacts(
            meta=meta,
            framing=framing,
            direction=direction,
            value=value,
            percentile=percentile,
            consecutive_hours=streak_hours,
            threshold=threshold,
            window_mean=window_mean,
            window_hours=_window_hours(meta, settings),
            band=band,
        )

    if (
        meta.consecutive_eligible
        and percentile is not None
        and streak_hours is not None
        and streak_hours >= settings.features.streak_min_hours
    ):
        above = percentile >= MEDIAN_PERCENTILE
        return facts("consecutive", "up" if above else "down", ceiling if above else floor)

    if meta.framing == "trend":
        return facts("trend", "up" if value >= 0.0 else "down", None)

    if meta.framing == "percentile" and percentile is not None:
        return facts("percentile", _side(percentile), None)

    if value >= nominal_ceiling or value <= nominal_floor:
        above = value >= nominal_ceiling
        return facts(
            "threshold",
            "up" if above else "down",
            nominal_ceiling if above else nominal_floor,
        )

    if percentile is not None:
        return facts("percentile", _side(percentile), None)

    if value >= ceiling or value <= floor:
        above = value >= ceiling
        return facts("threshold", "up" if above else "down", ceiling if above else floor)

    nearer_ceiling = (ceiling - value) <= (value - floor)
    return facts(
        "threshold",
        "up" if nearer_ceiling else "down",
        ceiling if nearer_ceiling else floor,
        band=(floor, ceiling),
    )


def _side(percentile: float) -> Direction:
    """Which half of the machine's own history a rank sits in."""
    return "up" if percentile >= MEDIAN_PERCENTILE else "down"


def _window_hours(meta: FeatureMeta, settings: Settings) -> float:
    """The span the clause's ``{window}`` names.

    A windowed feature names its own window. A raw channel names one dataset
    row — ``plants.<id>.row_interval_seconds`` — because that is the span its
    reading covers, and it lets a raw channel use the percentile framing instead
    of asserting a band crossing that did not happen.
    """
    if meta.window_hours is not None:
        return float(meta.window_hours)
    plant = settings.plants.ai4i if meta.plant_id == "ai4i" else settings.plants.ims
    return plant.row_interval_seconds / SECONDS_PER_HOUR


def history_levels(settings: Settings) -> tuple[float, float]:
    """The two percentile levels a history band is read at: ``(low, high)``.

    ``features.streak_percentile`` is the high side — the same level the streak
    counter tests — and its complement is the low side, so the band is symmetric
    about the median by construction.
    """
    high = float(settings.features.streak_percentile)
    return FULL_PERCENTILE - high, high
