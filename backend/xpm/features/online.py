"""The streaming feature engine: one :class:`TelemetryMessage` at a time.

``xpm.pipeline`` feeds every telemetry row published on
``xpm/{plant}/{machine_id}/telemetry`` (§3.3) through
:meth:`OnlineFeatureEngine.update` and gets back the ordered feature vector the
served model scores, alongside the metadata §3.4.3's ``ShapContribution``
carries: each feature's percentile in this machine's own history, how many
consecutive hours it has stayed above ``features.streak_percentile``, and the
raw channel values the sentence quotes.

State is per machine and explicit — the engine owns a dictionary of
:class:`MachineFeatureState`, there is no module-level mutable state, and
:meth:`OnlineFeatureEngine.reset` returns a fresh-run engine when a replay loop
mints a new ``run_id`` (R12).

:mod:`xpm.features.offline` drives the *same* :class:`MachineFeatureState` over
the processed parquet, so the training matrix and the live vector are the same
code path and ``tests/features/test_online_offline_parity.py`` can hold them to
bit equality rather than to a tolerance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from xpm.config import get_settings
from xpm.contracts.channels import channels_for
from xpm.contracts.common import PlantId
from xpm.contracts.mqtt import TelemetryMessage
from xpm.contracts.settings import Settings
from xpm.features.percentiles import PercentileBank
from xpm.features.registry import feature_index, feature_names, n_features
from xpm.features.stats import SECONDS_PER_HOUR, EwmaState, Float64Array, window_stat
from xpm.features.streak import StreakBank
from xpm.features.windows import (
    RollingWindowBuffer,
    WindowSpec,
    seconds_since_epoch,
    window_specs,
)

__all__ = ["FeatureVector", "MachineFeatureState", "OnlineFeatureEngine"]


def _optional(value: float) -> float | None:
    """``NaN`` is §3.1's "not yet computable"; the wire spells it ``null``."""
    return None if np.isnan(value) else float(value)


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """One machine's feature vector at one dataset instant.

    ``values``, ``percentiles`` and ``streak_hours`` are parallel arrays indexed
    by ``names``. ``NaN`` means "not yet computable" everywhere: a window short
    of ``features.min_window_coverage``, a feature still inside
    ``features.percentile_warmup_samples``, or a streak on a feature with no
    percentile yet. The ``*_of`` accessors translate that to ``None``.
    """

    plant_id: PlantId
    machine_id: str
    dataset_ts: datetime
    names: tuple[str, ...]
    values: Float64Array
    percentiles: Float64Array
    streak_hours: Float64Array
    channels: Mapping[str, float]

    def _position(self, feature: str) -> int:
        index = feature_index(self.plant_id).get(feature)
        if index is None:
            raise KeyError(f"{feature!r} is not a feature of plant {self.plant_id!r}")
        return index

    def value_of(self, feature: str) -> float | None:
        """The feature's value, or ``None`` when it is not yet computable."""
        return _optional(float(self.values[self._position(feature)]))

    def percentile_of(self, feature: str) -> float | None:
        """The value's percentile (0-100) in this machine's own history."""
        return _optional(float(self.percentiles[self._position(feature)]))

    def streak_of(self, feature: str) -> float | None:
        """Consecutive hours above ``features.streak_percentile``."""
        return _optional(float(self.streak_hours[self._position(feature)]))

    def as_dict(self) -> dict[str, float | None]:
        """Feature name -> value, in feature order, with ``None`` for null."""
        return {
            name: _optional(float(value))
            for name, value in zip(self.names, self.values, strict=True)
        }

    def percentiles_as_dict(self) -> dict[str, float | None]:
        """Feature name -> percentile rank, in feature order."""
        return {
            name: _optional(float(value))
            for name, value in zip(self.names, self.percentiles, strict=True)
        }

    def streaks_as_dict(self) -> dict[str, float | None]:
        """Feature name -> consecutive hours, in feature order."""
        return {
            name: _optional(float(value))
            for name, value in zip(self.names, self.streak_hours, strict=True)
        }


class MachineFeatureState:
    """Rolling windows, EWMAs, percentiles and streaks for one machine."""

    __slots__ = (
        "_buffer",
        "_channels",
        "_ewma",
        "_machine_id",
        "_n_features",
        "_names",
        "_percentiles",
        "_plant_id",
        "_slots",
        "_specs",
        "_stats",
        "_streaks",
    )

    def __init__(
        self, plant_id: PlantId, machine_id: str, settings: Settings | None = None
    ) -> None:
        resolved = settings or get_settings()
        self._plant_id = plant_id
        self._machine_id = machine_id
        self._channels = tuple(channel.name for channel in channels_for(plant_id))
        self._names = feature_names(plant_id)
        self._n_features = n_features(plant_id)
        self._stats: Sequence[str] = tuple(resolved.features.stats)
        self._specs: tuple[WindowSpec, ...] = window_specs(plant_id, resolved)
        self._slots = _feature_slots(len(self._channels), len(self._stats), len(self._specs))
        longest = max(self._specs, key=lambda spec: spec.span_seconds)
        self._buffer = RollingWindowBuffer(
            n_channels=len(self._channels),
            max_span_seconds=longest.span_seconds,
            expected_samples=longest.expected_samples,
        )
        self._ewma = tuple(EwmaState(spec.ewma_halflife_hours) for spec in self._specs)
        self._percentiles = PercentileBank(self._n_features, resolved)
        self._streaks = StreakBank(self._n_features, resolved)

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def channel_names(self) -> tuple[str, ...]:
        return self._channels

    def quantile(self, feature: str, level: float) -> float | None:
        """A feature's historical ``level``-th percentile value.

        This is the ``{threshold}`` §3.9's consecutive template prints. It is a
        deliberate off-the-hot-path query: an explanation names a handful of
        features, not all 154.
        """
        index = feature_index(self._plant_id).get(feature)
        if index is None:
            raise KeyError(f"{feature!r} is not a feature of plant {self._plant_id!r}")
        return self._percentiles.quantile(index, level)

    def update(self, dataset_ts: datetime, row: Float64Array) -> FeatureVector:
        """Fold one row of channel values in and return the new feature vector."""
        time_seconds = seconds_since_epoch(dataset_ts)
        self._buffer.append(time_seconds, row)

        values = np.full(self._n_features, np.nan, dtype=np.float64)
        values[: len(self._channels)] = row
        for window_position, spec in enumerate(self._specs):
            times, block = self._buffer.window(spec)
            ewma_value = self._ewma[window_position].update(time_seconds, row)
            if not spec.covers(block.shape[0]):
                continue
            # Hours relative to the row being scored: exact (both ends are whole
            # seconds) and well conditioned, which a raw epoch would not be.
            times_hours = (times - time_seconds) / SECONDS_PER_HOUR
            for stat_position, stat in enumerate(self._stats):
                target = self._slots[stat_position][window_position]
                if stat == "ewma":
                    values[target] = ewma_value
                else:
                    values[target] = window_stat(stat, block, times_hours)

        percentiles = self._percentiles.update(values)
        streaks = self._streaks.update(time_seconds, percentiles)
        return FeatureVector(
            plant_id=self._plant_id,
            machine_id=self._machine_id,
            dataset_ts=dataset_ts,
            names=self._names,
            values=values,
            percentiles=percentiles,
            streak_hours=streaks,
            channels=dict(zip(self._channels, (float(v) for v in row), strict=True)),
        )

    def reset(self) -> None:
        """Return to the state of a machine that has published nothing."""
        self._buffer.reset()
        for state in self._ewma:
            state.reset()
        self._percentiles.reset()
        self._streaks.reset()


def _feature_slots(
    n_channels: int, n_stats: int, n_windows: int
) -> tuple[tuple[NDArray[np.intp], ...], ...]:
    """Vector positions per ``(stat, window)``, one entry per channel.

    Mirrors :func:`xpm.features.registry.feature_names`' ordering — raw channels
    first, then channel-major stat x window — as an index array, so writing a
    whole statistic into the vector is one NumPy assignment instead of a Python
    loop over channels.
    """
    channel_base = n_channels + np.arange(n_channels, dtype=np.intp) * (n_stats * n_windows)
    return tuple(
        tuple(channel_base + stat * n_windows + window for window in range(n_windows))
        for stat in range(n_stats)
    )


class OnlineFeatureEngine:
    """Per-plant streaming engine: a :class:`MachineFeatureState` per machine."""

    __slots__ = ("_channels", "_names", "_plant_id", "_settings", "_states")

    def __init__(self, plant_id: PlantId, settings: Settings | None = None) -> None:
        self._plant_id = plant_id
        self._settings = settings or get_settings()
        self._names = feature_names(plant_id)
        self._channels = tuple(channel.name for channel in channels_for(plant_id))
        self._states: dict[str, MachineFeatureState] = {}

    @property
    def plant_id(self) -> PlantId:
        return self._plant_id

    @property
    def names(self) -> tuple[str, ...]:
        """The ordered feature names this engine emits."""
        return self._names

    @property
    def n_features(self) -> int:
        return len(self._names)

    @property
    def machine_ids(self) -> tuple[str, ...]:
        """Machines seen so far, in first-seen order."""
        return tuple(self._states)

    def state_for(self, machine_id: str) -> MachineFeatureState:
        """The machine's state, created on first sight."""
        state = self._states.get(machine_id)
        if state is None:
            state = MachineFeatureState(self._plant_id, machine_id, self._settings)
            self._states[machine_id] = state
        return state

    def update(self, message: TelemetryMessage) -> FeatureVector:
        """Fold one MQTT telemetry message in and return the feature vector."""
        if message.plant_id != self._plant_id:
            raise ValueError(
                f"engine is for plant {self._plant_id!r}, got a {message.plant_id!r} message"
            )
        return self.update_row(message.machine_id, message.dataset_ts, message.channels)

    def update_row(
        self, machine_id: str, dataset_ts: datetime, channels: Mapping[str, float | None]
    ) -> FeatureVector:
        """Fold one row of named channel values in and return the vector.

        Every canonical channel must be present and non-null: the processed
        parquet guarantees it (``xpm.data.schema`` rejects a NaN in a channel),
        and silently substituting a value would poison every window that row
        enters.
        """
        row = np.empty(len(self._channels), dtype=np.float64)
        for position, name in enumerate(self._channels):
            if name not in channels:
                raise ValueError(f"{machine_id}: telemetry is missing channel {name!r}")
            value = channels[name]
            if value is None:
                raise ValueError(f"{machine_id}: channel {name!r} is null")
            row[position] = value
        return self.state_for(machine_id).update(dataset_ts, row)

    def reset(self) -> None:
        """Drop every machine's state (a new ``run_id`` starts a new history)."""
        self._states.clear()
