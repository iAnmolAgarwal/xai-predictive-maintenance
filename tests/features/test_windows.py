"""Dataset-time window boundaries, coverage nulling and the ring buffer.

backend.md §4 pins two behaviours here: window boundaries are half-open
``(t - W, t]`` in dataset time, and a gap in the data shrinks the sample count
until ``features.min_window_coverage`` trips and the feature goes null. Both are
asserted against the buffer directly and end-to-end through the engine, and the
window contents are cross-checked against ``pandas.rolling`` on a time index.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from xpm.config import get_settings
from xpm.features.online import OnlineFeatureEngine
from xpm.features.windows import (
    RollingWindowBuffer,
    row_interval_seconds,
    seconds_since_epoch,
    window_specs,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _spec(plant: str, hours: int):  # type: ignore[no-untyped-def]
    return next(spec for spec in window_specs(plant) if spec.hours == hours)  # type: ignore[arg-type]


def _buffer(channels: int = 1, hours: float = 24.0, expected: int = 288) -> RollingWindowBuffer:
    return RollingWindowBuffer(
        n_channels=channels, max_span_seconds=hours * 3600.0, expected_samples=expected
    )


def test_row_interval_comes_from_the_plant_settings() -> None:
    settings = get_settings()
    assert row_interval_seconds("ai4i") == settings.plants.ai4i.row_interval_seconds
    assert row_interval_seconds("ims") == settings.plants.ims.row_interval_seconds


def test_window_specs_are_derived_from_config_not_hardcoded() -> None:
    features = get_settings().features
    specs = window_specs("ai4i")
    assert [spec.hours for spec in specs] == features.windows_hours
    assert [spec.label for spec in specs] == [f"{h}h" for h in features.windows_hours]
    for spec in specs:
        expected = round(spec.hours * 3600 / row_interval_seconds("ai4i"))
        assert spec.expected_samples == expected
        assert spec.min_samples == max(1, math.ceil(expected * features.min_window_coverage))
        assert spec.span_seconds == spec.hours * 3600.0


def test_ims_windows_hold_half_as_many_rows_as_ai4i() -> None:
    """One IMS file is 10 minutes of dataset time, one AI4I row is 5 (§3.2)."""
    ai4i = {spec.hours: spec.expected_samples for spec in window_specs("ai4i")}
    ims = {spec.hours: spec.expected_samples for spec in window_specs("ims")}
    assert ai4i == {1: 12, 4: 48, 24: 288}
    assert ims == {1: 6, 4: 24, 24: 144}


def test_window_boundary_is_half_open() -> None:
    """``(t - W, t]``: the current row is in, the row exactly W ago is out."""
    buffer = _buffer()
    spec = _spec("ai4i", 1)
    for index in range(13):
        buffer.append(index * 300.0, np.array([float(index)]))
    times, block = buffer.window(spec)
    # Rows are 5 min apart; the 1 h window holds rows 1..12, not row 0.
    assert block.shape[0] == 12
    assert float(block[0, 0]) == 1.0
    assert float(block[-1, 0]) == 12.0
    assert times[0] > buffer.last_time_seconds - spec.span_seconds


def test_window_contents_match_pandas_rolling_on_a_time_index() -> None:
    generator = np.random.default_rng(7)
    values = generator.normal(size=200)
    index = pd.date_range(START, periods=200, freq="5min", tz="UTC")
    series = pd.Series(values, index=index)

    buffer = _buffer()
    spec = _spec("ai4i", 4)
    produced: list[float] = []
    for moment, value in series.items():
        buffer.append(seconds_since_epoch(moment.to_pydatetime()), np.array([value]))
        _, block = buffer.window(spec)
        produced.append(float(block.mean()))

    # pandas' "4h" offset window is closed on the right and open on the left,
    # which is the same convention as §3.1's (t - W, t].
    expected = series.rolling("4h", closed="right").mean().to_numpy()
    np.testing.assert_allclose(np.array(produced), expected, rtol=1e-12, atol=1e-12)


def test_only_the_longest_window_is_retained() -> None:
    buffer = _buffer(hours=1.0, expected=12)
    for index in range(60):
        buffer.append(index * 300.0, np.array([float(index)]))
    assert len(buffer) == 12


def test_buffer_compacts_and_grows_without_losing_rows() -> None:
    """A cadence four times denser than expected forces a reallocation."""
    buffer = _buffer(hours=24.0, expected=4)
    for index in range(400):
        buffer.append(index * 300.0, np.array([float(index)]))
    times, block = buffer.window(_spec("ai4i", 24))
    assert block.shape[0] == len(buffer) == 288
    assert float(block[-1, 0]) == 399.0
    assert times[-1] == buffer.last_time_seconds


def test_buffer_rejects_a_rewound_timestamp() -> None:
    buffer = _buffer()
    buffer.append(600.0, np.array([1.0]))
    with pytest.raises(ValueError, match="strictly increase"):
        buffer.append(600.0, np.array([2.0]))


def test_buffer_rejects_a_wrong_width_row() -> None:
    buffer = _buffer(channels=2)
    with pytest.raises(ValueError, match="expected 2 channels"):
        buffer.append(300.0, np.array([1.0]))


def test_buffer_rejects_a_channelless_plant() -> None:
    with pytest.raises(ValueError, match="at least one channel"):
        RollingWindowBuffer(n_channels=0, max_span_seconds=3600.0, expected_samples=1)


def test_empty_buffer_yields_an_empty_window() -> None:
    buffer = _buffer()
    times, block = buffer.window(_spec("ai4i", 1))
    assert times.size == 0
    assert block.shape == (0, 1)
    with pytest.raises(IndexError, match="empty"):
        _ = buffer.last_time_seconds


def test_buffer_reset_empties_it() -> None:
    buffer = _buffer()
    buffer.append(300.0, np.array([1.0]))
    buffer.reset()
    assert len(buffer) == 0


def _telemetry_rows(count: int, *, gap_after: int | None = None) -> list[tuple[datetime, float]]:
    """A 5-minute ``ai4i`` cadence with an optional 20 h hole punched in it."""
    rows: list[tuple[datetime, float]] = []
    moment = START
    for index in range(count):
        rows.append((moment, 40.0 + index * 0.01))
        moment += timedelta(minutes=5)
        if gap_after is not None and index == gap_after:
            moment += timedelta(hours=20)
    return rows


def _channels(torque: float) -> dict[str, float | None]:
    return {
        "air_temp": 298.0,
        "process_temp": 308.0,
        "temp_diff": 10.0,
        "rot_speed": 1500.0,
        "torque": torque,
        "power": 6300.0,
        "tool_wear": 100.0,
    }


def test_features_are_null_until_the_window_is_covered() -> None:
    """A 1 h window needs ``ceil(12 * 0.6) = 8`` rows before it reports."""
    engine = OnlineFeatureEngine("ai4i")
    spec = _spec("ai4i", 1)
    for position, (moment, torque) in enumerate(_telemetry_rows(spec.min_samples)):
        vector = engine.update_row("ai4i-01", moment, _channels(torque))
        covered = position + 1 >= spec.min_samples
        assert (vector.value_of("torque_mean_1h") is not None) is covered
        # The raw channel is never null: it needs no window at all.
        assert vector.value_of("torque") == torque
    assert engine.machine_ids == ("ai4i-01",)


def test_the_longest_window_stays_null_longest() -> None:
    engine = OnlineFeatureEngine("ai4i")
    vector = None
    for moment, torque in _telemetry_rows(60):
        vector = engine.update_row("ai4i-02", moment, _channels(torque))
    assert vector is not None
    assert vector.value_of("torque_mean_1h") is not None
    assert vector.value_of("torque_mean_4h") is not None
    assert vector.value_of("torque_mean_24h") is None


def test_a_gap_trips_min_window_coverage() -> None:
    """After a 20 h hole the 24 h window holds too few rows to report."""
    engine = OnlineFeatureEngine("ai4i")
    vector = None
    for moment, torque in _telemetry_rows(300, gap_after=250):
        vector = engine.update_row("ai4i-03", moment, _channels(torque))
    assert vector is not None
    assert vector.value_of("torque_mean_24h") is None
    # The short window refilled after the gap, so it is live again.
    assert vector.value_of("torque_mean_1h") is not None


def test_engine_reset_clears_every_machine() -> None:
    engine = OnlineFeatureEngine("ai4i")
    for moment, torque in _telemetry_rows(20):
        engine.update_row("ai4i-04", moment, _channels(torque))
    engine.reset()
    assert engine.machine_ids == ()
    vector = engine.update_row("ai4i-04", START + timedelta(days=30), _channels(42.0))
    assert vector.value_of("torque_mean_1h") is None


def test_machine_state_reset_keeps_the_machine_but_drops_its_history() -> None:
    engine = OnlineFeatureEngine("ai4i")
    for moment, torque in _telemetry_rows(20):
        engine.update_row("ai4i-05", moment, _channels(torque))
    state = engine.state_for("ai4i-05")
    assert state.machine_id == "ai4i-05"
    assert state.channel_names[4] == "torque"
    state.reset()
    vector = engine.update_row("ai4i-05", START + timedelta(days=30), _channels(42.0))
    assert vector.value_of("torque_mean_1h") is None
