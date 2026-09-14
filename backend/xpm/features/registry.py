"""The canonical feature vector: ordered names and per-feature metadata.

The grammar is backend.md §0/§3.1's ``<channel>_<stat>_<window>`` —
``vibration_3khz_p95_4h``, ``torque_slope_1h`` — over the channel table in
:mod:`xpm.contracts.channels`, the stat list in ``features.stats`` and the
window list in ``features.windows_hours``. Raw channels are features too and
come first, which is what makes ``n_features`` for ``ai4i`` the 154 of §3.7's
``manifest.json`` (7 raw + 7 channels x 7 stats x 3 windows).

Order is a contract. ``models/registry/<family>/<version>/feature_names.json``
is written from :func:`feature_names` by ``T-MODEL`` and hashed into the
manifest, so serving refuses a model whose ordering disagrees with this module
(§3.7). :func:`feature_meta_payload` is the body of the sibling
``feature_meta.json``, which the explanation templater reads for the framing,
display name, unit and window it needs to render §3.9's clauses.

Nothing here is a threshold: the only numbers are the stat and window lists,
and both come from ``get_settings().features``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType
from typing import Final, Literal

from xpm.config import get_settings
from xpm.contracts.channels import channels_for
from xpm.contracts.common import ChannelSpec, PlantId

__all__ = [
    "FeatureMeta",
    "Framing",
    "feature_index",
    "feature_meta",
    "feature_meta_payload",
    "feature_names",
    "n_features",
    "window_label",
]

Framing = Literal["percentile", "threshold", "trend", "consecutive"]

#: §3.9's framing table, keyed by stat. ``p95`` and ``max`` are listed as
#: ``percentile`` here and carry ``consecutive_eligible``: the templater
#: promotes them to ``consecutive`` once the streak counter reaches
#: ``features.streak_min_hours``.
_STAT_FRAMING: Final[Mapping[str, Framing]] = MappingProxyType(
    {
        "mean": "percentile",
        "ewma": "percentile",
        "p95": "percentile",
        "max": "percentile",
        "slope": "trend",
        "std": "threshold",
        "min": "threshold",
    }
)

#: Stats whose framing becomes ``consecutive`` when a streak is long enough.
_CONSECUTIVE_STATS: Final[frozenset[str]] = frozenset({"p95", "max"})

#: Human labels used in ``display_name``. ``pNN`` is derived, not listed.
_STAT_LABELS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "mean": "mean",
        "std": "std dev",
        "min": "minimum",
        "max": "maximum",
        "slope": "slope",
        "ewma": "EWMA",
    }
)

_PERCENTILE_STAT = re.compile(r"^p(\d{1,2})$")

#: U+2014 EM DASH, matching §3.4.3's worked ``display_name``
#: "Vibration @ 3 kHz — 95th pct over 4 h".
_DISPLAY_SEPARATOR: Final[str] = " — "


@dataclass(frozen=True, slots=True)
class FeatureMeta:
    """Everything §3.4.3's :class:`ShapContribution` needs about one feature.

    ``framing`` is the declared family from §3.9; ``consecutive_eligible`` marks
    the two stats that switch to the consecutive-exceedance sentence when the
    streak counter says they may. ``nominal_min`` / ``nominal_max`` are the
    source channel's bounds, which is where the threshold framing gets its
    ``{threshold}`` from.
    """

    name: str
    index: int
    plant_id: PlantId
    channel: str
    channel_display_name: str
    display_name: str
    unit: str | None
    """``None`` for a dimensionless channel; ``"<unit>/h"`` for a slope."""
    stat: str | None
    """``None`` for a raw channel feature."""
    window_hours: int | None
    """``None`` for a raw channel feature."""
    framing: Framing
    consecutive_eligible: bool
    vibration_like: bool
    nominal_min: float
    nominal_max: float

    def as_dict(self) -> dict[str, object]:
        """JSON-ready row for ``feature_meta.json`` (§3.7)."""
        return {
            "name": self.name,
            "index": self.index,
            "plant_id": self.plant_id,
            "channel": self.channel,
            "channel_display_name": self.channel_display_name,
            "display_name": self.display_name,
            "unit": self.unit,
            "stat": self.stat,
            "window_hours": self.window_hours,
            "framing": self.framing,
            "consecutive_eligible": self.consecutive_eligible,
            "vibration_like": self.vibration_like,
            "nominal_min": self.nominal_min,
            "nominal_max": self.nominal_max,
        }


def window_label(hours: int) -> str:
    """The ``<window>`` token of the grammar: ``1`` -> ``"1h"``."""
    return f"{hours}h"


def _window_display(hours: int) -> str:
    """The humanised window used inside ``display_name``: ``4`` -> ``"4 h"``."""
    return f"{hours} h"


def _ordinal_suffix(value: int) -> str:
    if 10 <= value % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")


def _stat_label(stat: str) -> str:
    """``"p95"`` -> ``"95th pct"``; everything else comes from the table."""
    match = _PERCENTILE_STAT.match(stat)
    if match is not None:
        level = int(match.group(1))
        return f"{level}{_ordinal_suffix(level)} pct"
    label = _STAT_LABELS.get(stat)
    if label is None:
        raise ValueError(f"features.stats contains an unsupported stat {stat!r}")
    return label


def _stat_framing(stat: str) -> Framing:
    framing = _STAT_FRAMING.get(stat)
    if framing is None:
        raise ValueError(f"features.stats contains an unsupported stat {stat!r}")
    return framing


def _unit_or_none(unit: str) -> str | None:
    """``ChannelSpec.unit`` is ``""`` for dimensionless; the wire wants ``None``."""
    return unit or None


def _raw_meta(plant_id: PlantId, index: int, channel: ChannelSpec) -> FeatureMeta:
    """A raw channel feature. Every channel carries nominal bounds, so §3.9's
    "raw channel -> threshold if the channel has nominal bounds" always holds."""
    return FeatureMeta(
        name=channel.name,
        index=index,
        plant_id=plant_id,
        channel=channel.name,
        channel_display_name=channel.display_name,
        display_name=channel.display_name,
        unit=_unit_or_none(channel.unit),
        stat=None,
        window_hours=None,
        framing="threshold",
        consecutive_eligible=False,
        vibration_like=channel.vibration_like,
        nominal_min=channel.nominal_min,
        nominal_max=channel.nominal_max,
    )


def _windowed_meta(
    plant_id: PlantId, index: int, channel: ChannelSpec, stat: str, hours: int
) -> FeatureMeta:
    unit = _unit_or_none(channel.unit)
    if stat == "slope" and unit is not None:
        unit = f"{unit}/h"
    return FeatureMeta(
        name=f"{channel.name}_{stat}_{window_label(hours)}",
        index=index,
        plant_id=plant_id,
        channel=channel.name,
        channel_display_name=channel.display_name,
        display_name=(
            f"{channel.display_name}{_DISPLAY_SEPARATOR}"
            f"{_stat_label(stat)} over {_window_display(hours)}"
        ),
        unit=unit,
        stat=stat,
        window_hours=hours,
        framing=_stat_framing(stat),
        consecutive_eligible=stat in _CONSECUTIVE_STATS,
        vibration_like=channel.vibration_like,
        nominal_min=channel.nominal_min,
        nominal_max=channel.nominal_max,
    )


@cache
def _build(plant_id: PlantId) -> tuple[FeatureMeta, ...]:
    """Raw channels first, then channel-major x stat x window.

    Cached on ``plant_id`` alone: the two settings this reads,
    ``features.stats`` and ``features.windows_hours``, are not in
    ``MUTABLE_CONFIG_KEYS``, so ``PUT /api/config`` cannot invalidate it.
    """
    features = get_settings().features
    stats: Sequence[str] = features.stats
    windows: Sequence[int] = features.windows_hours
    if not stats or not windows:
        raise ValueError("features.stats and features.windows_hours must be non-empty")

    channels = channels_for(plant_id)
    metas: list[FeatureMeta] = [
        _raw_meta(plant_id, index, channel) for index, channel in enumerate(channels)
    ]
    for channel in channels:
        for stat in stats:
            for hours in windows:
                metas.append(_windowed_meta(plant_id, len(metas), channel, stat, hours))
    return tuple(metas)


@cache
def feature_names(plant_id: PlantId) -> tuple[str, ...]:
    """The ordered feature names of ``plant_id``'s vector."""
    return tuple(meta.name for meta in _build(plant_id))


@cache
def feature_meta(plant_id: PlantId) -> Mapping[str, FeatureMeta]:
    """Per-feature metadata, keyed by name, in feature order."""
    return MappingProxyType({meta.name: meta for meta in _build(plant_id)})


@cache
def feature_index(plant_id: PlantId) -> Mapping[str, int]:
    """Feature name -> position in the vector."""
    return MappingProxyType({meta.name: meta.index for meta in _build(plant_id)})


def n_features(plant_id: PlantId) -> int:
    """Length of ``plant_id``'s feature vector."""
    return len(_build(plant_id))


def feature_meta_payload(plant_id: PlantId) -> dict[str, object]:
    """The JSON body of ``feature_meta.json`` in a model version (§3.7)."""
    return {
        "plant_id": plant_id,
        "n_features": n_features(plant_id),
        "features": [meta.as_dict() for meta in _build(plant_id)],
    }
