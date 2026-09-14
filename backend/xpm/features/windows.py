"""Rolling dataset-time windows: the 1 h / 4 h / 24 h buffers of §3.1.

Window boundaries are **half-open in dataset time**, ``(t - W, t]``: the row
being scored is always in its own window and the row exactly ``W`` ago is not.
Dataset time is the only clock here (§3.1); wall clock never enters.

Coverage. A window expects ``W / plants.<id>.row_interval_seconds`` samples. A
gap in the stream shrinks the count, and once the count falls below
``features.min_window_coverage`` of the expectation every statistic for that
window is ``NaN`` — §3.1's "not yet computable", which consumers render as a
designed empty state rather than a zero. This is also what makes the 24 h
features null for the first several hours of a machine's life.

Storage. :class:`RollingWindowBuffer` keeps one contiguous ``(capacity,
channels)`` NumPy array per machine plus a parallel array of dataset timestamps
in **seconds** since the epoch. Seconds, not hours, because dataset timestamps
are whole seconds and floats hold integers exactly up to 2**53: the boundary
comparison ``t > now - W`` is then exact, and the row exactly one window old can
never fall inside the window through a rounding wobble. Hours appear only where
a statistic is defined per hour, computed from differences that are themselves
exact. Appends write at the tail, expiry advances the head, and the live
region is compacted to the front only when the tail runs out of room — so
buffer maintenance is amortised O(1) per row and every window is a **view**,
never a copy. That is what lets :mod:`xpm.features.stats` work on plain
contiguous blocks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np

from xpm.config import get_settings
from xpm.contracts.common import PlantId
from xpm.contracts.settings import Settings
from xpm.features.stats import Float64Array, ewma_halflife_hours

__all__ = [
    "RollingWindowBuffer",
    "WindowSpec",
    "row_interval_seconds",
    "seconds_since_epoch",
    "window_specs",
]

_SECONDS_PER_HOUR: Final[float] = 3600.0

#: Spare rows kept beyond the longest window so a burst of samples arriving
#: faster than the nominal cadence does not force a reallocation immediately.
_CAPACITY_SLACK: Final[int] = 8


def seconds_since_epoch(moment: datetime) -> float:
    """Dataset time as float seconds since the Unix epoch, held exactly."""
    return moment.timestamp()


def row_interval_seconds(plant_id: PlantId, settings: Settings | None = None) -> int:
    """``plants.<plant_id>.row_interval_seconds`` — the dataset-time advance per
    row (§3.2): 300 s for ``ai4i``, 600 s for ``ims``."""
    plants = (settings or get_settings()).plants
    return (
        plants.ai4i.row_interval_seconds if plant_id == "ai4i" else plants.ims.row_interval_seconds
    )


@dataclass(frozen=True, slots=True)
class WindowSpec:
    """One entry of ``features.windows_hours``, resolved for a plant."""

    hours: int
    label: str
    """The ``<window>`` token of the feature grammar, e.g. ``"4h"``."""
    span_seconds: float
    """The window length in dataset seconds; the exact comparison boundary."""
    expected_samples: int
    """``hours * 3600 / row_interval_seconds``, at least 1."""
    min_samples: int
    """``ceil(expected_samples * features.min_window_coverage)``, at least 1."""
    ewma_halflife_hours: float

    def covers(self, samples: int) -> bool:
        """Whether ``samples`` rows meet ``features.min_window_coverage``."""
        return samples >= self.min_samples


def window_specs(plant_id: PlantId, settings: Settings | None = None) -> tuple[WindowSpec, ...]:
    """Resolve ``features.windows_hours`` against ``plant_id``'s row cadence."""
    resolved = settings or get_settings()
    features = resolved.features
    interval = row_interval_seconds(plant_id, resolved)
    specs: list[WindowSpec] = []
    for hours in features.windows_hours:
        expected = max(1, round(hours * _SECONDS_PER_HOUR / interval))
        minimum = max(1, math.ceil(expected * features.min_window_coverage))
        specs.append(
            WindowSpec(
                hours=hours,
                label=f"{hours}h",
                span_seconds=hours * _SECONDS_PER_HOUR,
                expected_samples=expected,
                min_samples=minimum,
                ewma_halflife_hours=ewma_halflife_hours(float(hours), features.ewma_halflife_hours),
            )
        )
    return tuple(specs)


class RollingWindowBuffer:
    """A machine's recent channel rows, indexed by dataset time.

    Only rows inside the longest configured window are retained; anything older
    is dropped on the next append, so memory per machine is bounded by
    ``max(windows) / row_interval`` rows regardless of how long a run lasts.
    """

    __slots__ = (
        "_capacity",
        "_end",
        "_max_span_seconds",
        "_n_channels",
        "_start",
        "_times",
        "_values",
    )

    def __init__(self, n_channels: int, max_span_seconds: float, expected_samples: int) -> None:
        if n_channels < 1:
            raise ValueError(f"a plant needs at least one channel, got {n_channels}")
        self._n_channels = n_channels
        self._max_span_seconds = max_span_seconds
        self._capacity = 2 * (expected_samples + _CAPACITY_SLACK)
        self._times = np.zeros(self._capacity, dtype=np.float64)
        self._values = np.zeros((self._capacity, n_channels), dtype=np.float64)
        self._start = 0
        self._end = 0

    def __len__(self) -> int:
        return self._end - self._start

    @property
    def last_time_seconds(self) -> float:
        """Dataset time of the most recent row, in seconds since the epoch."""
        if self._end == self._start:
            raise IndexError("buffer is empty")
        return float(self._times[self._end - 1])

    def append(self, time_seconds: float, row: Float64Array) -> None:
        """Add one row at ``time_seconds`` and expire everything older than the
        longest window.

        Raises ``ValueError`` on a non-increasing timestamp: dataset time is
        strictly increasing per machine (``xpm.data.schema`` enforces the same
        rule on the processed parquet), and a rewind would silently corrupt
        every window.
        """
        if row.shape != (self._n_channels,):
            raise ValueError(f"expected {self._n_channels} channels, got row shape {row.shape}")
        if self._end > self._start and time_seconds <= self.last_time_seconds:
            raise ValueError(
                f"dataset time must strictly increase: {time_seconds} <= {self.last_time_seconds}"
            )
        self._make_room()
        self._times[self._end] = time_seconds
        self._values[self._end] = row
        self._end += 1
        self._expire(time_seconds)

    def window(self, spec: WindowSpec) -> tuple[Float64Array, Float64Array]:
        """The half-open ``(t - W, t]`` slice as ``(times_seconds, block)`` views."""
        if self._end == self._start:
            empty_times: Float64Array = np.empty(0, dtype=np.float64)
            return empty_times, np.empty((0, self._n_channels), dtype=np.float64)
        cutoff = self.last_time_seconds - spec.span_seconds
        live = self._times[self._start : self._end]
        offset = int(np.searchsorted(live, cutoff, side="right"))
        begin = self._start + offset
        return self._times[begin : self._end], self._values[begin : self._end]

    def reset(self) -> None:
        """Drop every retained row (used when a replay loop starts a new run)."""
        self._start = 0
        self._end = 0

    def _make_room(self) -> None:
        """Compact, then grow, so the tail always has one free slot."""
        if self._end < self._capacity:
            return
        live = self._end - self._start
        if live * 2 >= self._capacity:
            self._grow(max(self._capacity * 2, (live + 1) * 2))
            return
        self._times[:live] = self._times[self._start : self._end]
        self._values[:live] = self._values[self._start : self._end]
        self._start = 0
        self._end = live

    def _grow(self, capacity: int) -> None:
        live = self._end - self._start
        times = np.zeros(capacity, dtype=np.float64)
        values = np.zeros((capacity, self._n_channels), dtype=np.float64)
        times[:live] = self._times[self._start : self._end]
        values[:live] = self._values[self._start : self._end]
        self._times = times
        self._values = values
        self._capacity = capacity
        self._start = 0
        self._end = live

    def _expire(self, now_seconds: float) -> None:
        cutoff = now_seconds - self._max_span_seconds
        while self._start < self._end and self._times[self._start] <= cutoff:
            self._start += 1
