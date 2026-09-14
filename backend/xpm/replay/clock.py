"""The replay clock: wall-clock pacing on one side, dataset time on the other.

Two clocks, kept rigorously apart (backend.md §3.1):

* **dataset time** advances by exactly ``row_interval`` per tick. It is a pure
  function of the tick index and is therefore *independent of speed*.
* **wall-clock pacing** decides *when* a tick becomes due:
  ``1 / (base_rate_hz * speed)`` seconds apart.

That separation is the whole of R5: changing the speed changes how fast a demo
runs, never which dataset instants are emitted, so ``run_id``, ``dataset_ts``,
``seq`` and every derived ``alert_id`` are byte-identical at 0.5x and at 20x.

The clock reads wall time through an injectable :class:`TimeSource`, so tests
drive a virtual clock and run a whole replay in microseconds.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Protocol, final, runtime_checkable

__all__ = ["RealTimeSource", "ReplayClock", "TimeSource"]


@runtime_checkable
class TimeSource(Protocol):
    """Wall-clock pacing, injectable so tests can run without sleeping."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary fixed origin; only differences matter."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend for ``seconds``; a non-positive duration must still yield."""
        ...


@final
class RealTimeSource:
    """The production :class:`TimeSource`: :mod:`asyncio` and :func:`time.monotonic`."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        # A zero-second sleep still hands control back to the event loop, which
        # is what lets a control command land between two ticks.
        await asyncio.sleep(max(seconds, 0.0))


@final
class ReplayClock:
    """Tick pacing and the dataset-time cursor for one replay run.

    The public cursor is :attr:`tick`, a 0-based index into the schedule.
    :attr:`dataset_ts` is always ``dataset_start + tick * row_interval``.
    """

    def __init__(
        self,
        *,
        dataset_start: datetime,
        row_interval: timedelta,
        base_rate_hz: float,
        speed: float,
        tick_count: int,
        time_source: TimeSource,
        playing: bool = True,
    ) -> None:
        if row_interval <= timedelta(0):
            raise ValueError(f"row_interval must be positive, got {row_interval!r}")
        if base_rate_hz <= 0.0:
            raise ValueError(f"base_rate_hz must be positive, got {base_rate_hz!r}")
        if speed <= 0.0:
            raise ValueError(f"speed must be positive, got {speed!r}")
        if tick_count < 1:
            raise ValueError(f"tick_count must be at least 1, got {tick_count!r}")
        self._dataset_start = dataset_start
        self._row_interval = row_interval
        self._base_rate_hz = base_rate_hz
        self._speed = speed
        self._tick_count = tick_count
        self._time = time_source
        self._tick = 0
        self._playing = playing
        # Wall-clock seconds still owed before the current tick may be
        # published. While playing, it is tracked as an absolute deadline;
        # while paused, as the frozen remainder.
        self._due = self._time.monotonic()
        self._remaining = 0.0

    # -- read-only view ---------------------------------------------------- #

    @property
    def tick(self) -> int:
        """0-based index of the tick that is due next."""
        return self._tick

    @property
    def tick_count(self) -> int:
        """Number of ticks in the run; :attr:`tick` never reaches it."""
        return self._tick_count

    @property
    def dataset_ts(self) -> datetime:
        """Dataset-time instant of the current tick. Never depends on speed."""
        return self.dataset_ts_at(self._tick)

    @property
    def dataset_start(self) -> datetime:
        return self._dataset_start

    @property
    def dataset_end(self) -> datetime:
        """Dataset-time instant of the final tick."""
        return self.dataset_ts_at(self._tick_count - 1)

    @property
    def row_interval(self) -> timedelta:
        return self._row_interval

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def seconds_per_tick(self) -> float:
        """Wall-clock spacing of two ticks at the current speed."""
        return 1.0 / (self._base_rate_hz * self._speed)

    @property
    def exhausted(self) -> bool:
        """True once every tick of the schedule has been published."""
        return self._tick >= self._tick_count

    def dataset_ts_at(self, tick: int) -> datetime:
        """Dataset time of an arbitrary tick index."""
        return self._dataset_start + tick * self._row_interval

    def tick_for(self, dataset_ts: datetime) -> int:
        """Nearest tick index to ``dataset_ts``, clamped to the schedule."""
        offset = (dataset_ts - self._dataset_start) / self._row_interval
        return max(0, min(self._tick_count - 1, round(offset)))

    def wait_seconds(self) -> float:
        """Wall-clock seconds to sleep before the current tick may be published."""
        if not self._playing:
            return self._remaining
        return max(0.0, self._due - self._time.monotonic())

    # -- mutation ---------------------------------------------------------- #

    def advance(self) -> None:
        """Consume the current tick and schedule the next one.

        The deadline is advanced by exactly one tick rather than rebased on
        *now*, so a slow publish is absorbed instead of compounding drift.
        """
        self._tick += 1
        if self._playing:
            self._due += self.seconds_per_tick
        else:
            self._remaining = self.seconds_per_tick

    def pause(self) -> bool:
        """Freeze pacing. Returns ``True`` if this changed anything."""
        if not self._playing:
            return False
        self._remaining = max(0.0, self._due - self._time.monotonic())
        self._playing = False
        return True

    def play(self) -> bool:
        """Resume pacing from the frozen remainder. Returns ``True`` on change."""
        if self._playing:
            return False
        self._due = self._time.monotonic() + self._remaining
        self._playing = True
        return True

    def set_speed(self, speed: float) -> bool:
        """Re-pace the run. Dataset time and :attr:`tick` are untouched (R5).

        The remainder of the current wait is rescaled by the speed ratio, so the
        change takes effect smoothly rather than with a jump or a burst.
        """
        if speed <= 0.0:
            raise ValueError(f"speed must be positive, got {speed!r}")
        if speed == self._speed:
            return False
        ratio = self._speed / speed
        if self._playing:
            now = self._time.monotonic()
            self._due = now + max(0.0, self._due - now) * ratio
        else:
            self._remaining *= ratio
        self._speed = speed
        return True

    def seek(self, dataset_ts: datetime) -> int:
        """Jump the dataset cursor to the tick nearest ``dataset_ts``.

        The next tick becomes due immediately: a scrub should feel instant, and
        holding the old phase would stall it by up to one tick interval.
        """
        self._tick = self.tick_for(dataset_ts)
        self._reset_phase()
        return self._tick

    def reset(self) -> None:
        """Rewind to the first tick, keeping speed and play state."""
        self._tick = 0
        self._reset_phase()

    def _reset_phase(self) -> None:
        self._due = self._time.monotonic()
        self._remaining = 0.0
