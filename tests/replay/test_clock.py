"""The replay clock: dataset time never depends on speed (backend.md §4, R5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xpm.replay.clock import RealTimeSource, ReplayClock

from . import AI4I_START, VirtualTimeSource

ROW_INTERVAL = timedelta(minutes=5)
BASE_RATE_HZ = 2.0
SPEEDS = (0.5, 1.0, 5.0, 20.0)


def make_clock(
    *,
    speed: float = 1.0,
    tick_count: int = 100,
    time_source: VirtualTimeSource | None = None,
    playing: bool = True,
) -> tuple[ReplayClock, VirtualTimeSource]:
    time = time_source if time_source is not None else VirtualTimeSource()
    clock = ReplayClock(
        dataset_start=AI4I_START,
        row_interval=ROW_INTERVAL,
        base_rate_hz=BASE_RATE_HZ,
        speed=speed,
        tick_count=tick_count,
        time_source=time,
        playing=playing,
    )
    return clock, time


@pytest.mark.parametrize("speed", SPEEDS)
def test_n_ticks_advance_dataset_time_by_n_row_intervals(speed: float) -> None:
    """The R5 invariant: dataset-time granularity is speed-independent."""
    clock, _ = make_clock(speed=speed)
    for expected in range(20):
        assert clock.tick == expected
        assert clock.dataset_ts == AI4I_START + expected * ROW_INTERVAL
        clock.advance()
    assert clock.dataset_ts - AI4I_START == 20 * ROW_INTERVAL


@pytest.mark.parametrize("speed", SPEEDS)
def test_speed_changes_wall_clock_pacing_only(speed: float) -> None:
    """``n`` ticks span ``(n - 1)`` intervals of wall time, and no more.

    The first tick is due immediately, so ten ticks cost nine gaps.
    """
    clock, time = make_clock(speed=speed)
    ticks = 10
    for _ in range(ticks):
        time.now += clock.wait_seconds()
        clock.advance()
    assert time.now == pytest.approx((ticks - 1) / (BASE_RATE_HZ * speed))
    assert clock.dataset_ts == AI4I_START + ticks * ROW_INTERVAL


def test_seconds_per_tick_is_the_inverse_of_rate_times_speed() -> None:
    clock, _ = make_clock(speed=5.0)
    assert clock.seconds_per_tick == pytest.approx(1.0 / (BASE_RATE_HZ * 5.0))


def test_wait_seconds_never_goes_negative_when_a_tick_is_overdue() -> None:
    clock, time = make_clock()
    time.now += 10.0
    assert clock.wait_seconds() == 0.0


def test_pause_freezes_the_remaining_wait_and_resume_restores_it() -> None:
    clock, time = make_clock()
    clock.advance()  # the next tick is due 0.5 s from the start
    time.now += 0.2
    assert clock.pause() is True
    assert clock.playing is False
    assert clock.wait_seconds() == pytest.approx(0.3)

    time.now += 100.0  # a long pause must not create a burst of overdue ticks
    assert clock.wait_seconds() == pytest.approx(0.3)
    assert clock.play() is True
    assert clock.wait_seconds() == pytest.approx(0.3)


def test_pause_and_play_are_idempotent() -> None:
    clock, _ = make_clock()
    assert clock.pause() is True
    assert clock.pause() is False
    assert clock.play() is True
    assert clock.play() is False


def test_advance_while_paused_keeps_a_full_interval_owed() -> None:
    clock, _ = make_clock(playing=False)
    clock.advance()
    assert clock.tick == 1
    assert clock.wait_seconds() == pytest.approx(clock.seconds_per_tick)


def test_set_speed_rescales_the_remaining_wait_without_moving_dataset_time() -> None:
    clock, time = make_clock(speed=1.0)
    clock.advance()
    time.now += 0.1  # 0.4 s of the 0.5 s interval still owed
    assert clock.set_speed(20.0) is True
    assert clock.wait_seconds() == pytest.approx(0.4 * (1.0 / 20.0))
    assert clock.dataset_ts == AI4I_START + ROW_INTERVAL
    assert clock.tick == 1


def test_set_speed_while_paused_rescales_the_frozen_remainder() -> None:
    clock, _ = make_clock(speed=1.0)
    clock.advance()
    clock.pause()
    assert clock.wait_seconds() == pytest.approx(0.5)
    clock.set_speed(5.0)
    assert clock.wait_seconds() == pytest.approx(0.1)


def test_set_speed_to_the_current_speed_reports_no_change() -> None:
    clock, _ = make_clock(speed=5.0)
    assert clock.set_speed(5.0) is False


def test_seek_jumps_to_the_nearest_tick_and_makes_it_due_immediately() -> None:
    clock, time = make_clock()
    time.now += 3.0
    target = AI4I_START + timedelta(minutes=27)  # nearest grid point is tick 5
    assert clock.seek(target) == 5
    assert clock.dataset_ts == AI4I_START + 5 * ROW_INTERVAL
    assert clock.wait_seconds() == 0.0


def test_seek_clamps_to_the_schedule_bounds() -> None:
    clock, _ = make_clock(tick_count=10)
    assert clock.seek(AI4I_START - timedelta(days=5)) == 0
    assert clock.seek(AI4I_START + timedelta(days=5)) == 9
    assert clock.dataset_ts == clock.dataset_end


def test_reset_rewinds_to_the_first_tick_and_keeps_speed_and_play_state() -> None:
    clock, _ = make_clock(speed=20.0)
    for _ in range(4):
        clock.advance()
    clock.reset()
    assert clock.tick == 0
    assert clock.dataset_ts == AI4I_START
    assert clock.speed == 20.0
    assert clock.playing is True


def test_exhausted_becomes_true_only_after_the_last_tick() -> None:
    clock, _ = make_clock(tick_count=3)
    for _ in range(3):
        assert clock.exhausted is False
        clock.advance()
    assert clock.exhausted is True


def test_dataset_bounds_are_derived_from_the_tick_count() -> None:
    clock, _ = make_clock(tick_count=12)
    assert clock.dataset_start == AI4I_START
    assert clock.dataset_end == AI4I_START + 11 * ROW_INTERVAL
    assert clock.row_interval == ROW_INTERVAL
    assert clock.tick_count == 12


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"row_interval": timedelta(0)}, "row_interval"),
        ({"base_rate_hz": 0.0}, "base_rate_hz"),
        ({"speed": -1.0}, "speed"),
        ({"tick_count": 0}, "tick_count"),
    ],
)
def test_invalid_construction_is_rejected(kwargs: dict[str, object], message: str) -> None:
    defaults: dict[str, object] = {
        "dataset_start": AI4I_START,
        "row_interval": ROW_INTERVAL,
        "base_rate_hz": BASE_RATE_HZ,
        "speed": 1.0,
        "tick_count": 10,
        "time_source": VirtualTimeSource(),
    }
    with pytest.raises(ValueError, match=message):
        ReplayClock(**{**defaults, **kwargs})  # type: ignore[arg-type]


def test_set_speed_rejects_a_non_positive_speed() -> None:
    clock, _ = make_clock()
    with pytest.raises(ValueError, match="speed"):
        clock.set_speed(0.0)


async def test_real_time_source_measures_a_real_sleep() -> None:
    """The production time source is a thin, real wrapper, so smoke it once."""
    source = RealTimeSource()
    before = source.monotonic()
    await source.sleep(0.01)
    assert source.monotonic() - before >= 0.005
    await source.sleep(-1.0)  # a negative duration still yields, never raises


def test_tick_for_rounds_to_the_nearest_grid_point() -> None:
    clock, _ = make_clock(tick_count=100)
    assert clock.tick_for(AI4I_START + timedelta(minutes=12)) == 2
    assert clock.tick_for(AI4I_START + timedelta(minutes=13)) == 3
    assert clock.tick_for(datetime(2026, 1, 1, 0, 0, tzinfo=UTC)) == 0
