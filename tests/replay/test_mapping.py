"""Row -> machine -> tick mapping, over the real committed parquet (§3.2, §4).

These tests read ``data/processed/*`` rather than a synthetic frame: the claims
they make ("833 or 834 rows each", "failure prevalence within +-1.5 pp") are
claims about the shipped dataset, and checking them against a fixture would
prove nothing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from xpm.config import get_settings
from xpm.contracts.mqtt import Ai4iLabels, Ai4iMeta, ImsLabels, ImsMeta
from xpm.data import loader
from xpm.data.schema import AI4I_CHANNELS, IMS_CHANNELS
from xpm.replay.mapping import (
    ReplaySchedule,
    build_schedule,
    expected_machine_id,
    plant_row_interval,
)

from . import ai4i_frame, ims_frame


@pytest.fixture(scope="module")
def ai4i_schedule() -> ReplaySchedule:
    return build_schedule("ai4i", settings=get_settings())


@pytest.fixture(scope="module")
def ims_schedule() -> ReplaySchedule:
    return build_schedule("ims", settings=get_settings())


# -- round-robin assignment ------------------------------------------------- #


def test_round_robin_is_exactly_i_mod_12_plus_1() -> None:
    assert expected_machine_id("ai4i", 0, 12) == "ai4i-01"
    assert expected_machine_id("ai4i", 11, 12) == "ai4i-12"
    assert expected_machine_id("ai4i", 12, 12) == "ai4i-01"
    assert expected_machine_id("ai4i", 4822, 12) == "ai4i-11"


def test_round_robin_covers_the_ims_bearings() -> None:
    assert [expected_machine_id("ims", index, 4) for index in range(5)] == [
        "ims-01",
        "ims-02",
        "ims-03",
        "ims-04",
        "ims-01",
    ]


def test_expected_machine_id_rejects_a_zero_machine_count() -> None:
    with pytest.raises(ValueError, match="machine_count"):
        expected_machine_id("ai4i", 0, 0)


def test_the_committed_parquet_follows_the_round_robin_rule() -> None:
    """The publisher trusts ``machine_id``; this proves the trust is earned.

    ``source_row`` is AI4I's native 1-based ``UDI``, so the 0-based deal index
    is ``source_row - 1``.
    """
    frame = loader.load_ai4i()
    machines = get_settings().plants.ai4i.machine_count
    mismatches = [
        row.source_row
        for row in frame.itertuples(index=False)
        if row.machine_id != expected_machine_id("ai4i", int(row.source_row) - 1, machines)
    ]
    assert mismatches == []


# -- per-machine row counts and failure prevalence -------------------------- #


def test_every_ai4i_machine_receives_833_or_834_rows() -> None:
    counts = loader.load_ai4i().groupby("machine_id").size()
    assert set(counts.unique()) <= {833, 834}
    assert int(counts.sum()) == 10_000


def test_ai4i_failure_prevalence_per_machine_is_within_1_5_pp_of_the_global_rate() -> None:
    frame = loader.load_ai4i()
    global_rate = float(frame["machine_failure"].mean())
    per_machine = frame.groupby("machine_id")["machine_failure"].mean()
    assert (per_machine - global_rate).abs().max() <= 0.015


# -- schedule shape --------------------------------------------------------- #


def test_ai4i_schedule_matches_the_dataset_grid(ai4i_schedule: ReplaySchedule) -> None:
    schedule = ai4i_schedule
    assert schedule.plant_id == "ai4i"
    assert schedule.tick_count == 834
    assert schedule.rows_total == 10_000
    assert schedule.machine_count == 12
    assert schedule.row_interval == timedelta(minutes=5)
    assert schedule.dataset_end - schedule.dataset_start == 833 * timedelta(minutes=5)


def test_ims_schedule_preserves_the_ten_minute_cadence(ims_schedule: ReplaySchedule) -> None:
    schedule = ims_schedule
    assert schedule.tick_count == 984
    assert schedule.rows_total == 3_936
    assert schedule.machine_ids == ("ims-01", "ims-02", "ims-03", "ims-04")
    assert schedule.row_interval == timedelta(minutes=10)


def test_every_tick_holds_at_most_one_row_per_machine(ims_schedule: ReplaySchedule) -> None:
    for tick in ims_schedule.ticks:
        machines = [row.machine_id for row in tick]
        assert len(machines) == len(set(machines))


def test_a_tick_carries_the_full_canonical_channel_set() -> None:
    settings = get_settings()
    ai4i = build_schedule("ai4i", settings=settings, frame=ai4i_frame(3))
    ims = build_schedule("ims", settings=settings, frame=ims_frame(3))
    assert tuple(ai4i.ticks[0][0].channels) == AI4I_CHANNELS
    assert tuple(ims.ticks[0][0].channels) == IMS_CHANNELS


def test_labels_and_meta_are_the_plant_specific_shapes() -> None:
    settings = get_settings()
    ai4i = build_schedule("ai4i", settings=settings, frame=ai4i_frame(2))
    ims = build_schedule("ims", settings=settings, frame=ims_frame(2))
    assert isinstance(ai4i.ticks[0][0].labels, Ai4iLabels)
    assert isinstance(ai4i.ticks[0][0].meta, Ai4iMeta)
    assert isinstance(ims.ticks[0][0].labels, ImsLabels)
    assert isinstance(ims.ticks[0][0].meta, ImsMeta)


# -- determinism and the role of the seed ----------------------------------- #


def test_the_same_seed_builds_an_identical_schedule() -> None:
    settings = get_settings()
    frame = ai4i_frame(12)
    first = build_schedule("ai4i", settings=settings, seed=42, frame=frame)
    second = build_schedule("ai4i", settings=settings, seed=42, frame=frame)
    assert first == second


def test_the_seed_permutes_within_a_tick_and_changes_nothing_else() -> None:
    """Exactly the documented scope of ``replay.seed``."""
    settings = get_settings()
    frame = ai4i_frame(12, machines=6)
    a = build_schedule("ai4i", settings=settings, seed=42, frame=frame)
    b = build_schedule("ai4i", settings=settings, seed=7, frame=frame)

    assert [row.machine_id for row in a.ticks[0]] != [row.machine_id for row in b.ticks[0]]
    for left, right in zip(a.ticks, b.ticks, strict=True):
        assert sorted(row.machine_id for row in left) == sorted(row.machine_id for row in right)
        assert {row.dataset_ts for row in left} == {row.dataset_ts for row in right}
        by_machine = {row.machine_id: row for row in right}
        for row in left:
            assert by_machine[row.machine_id].channels == row.channels
    assert (a.dataset_start, a.dataset_end, a.rows_total) == (
        b.dataset_start,
        b.dataset_end,
        b.rows_total,
    )


def test_the_seed_defaults_to_the_configured_replay_seed() -> None:
    settings = get_settings()
    frame = ai4i_frame(4)
    assert build_schedule("ai4i", settings=settings, frame=frame).seed == settings.replay.seed


def test_build_schedule_falls_back_to_the_cached_settings_singleton() -> None:
    frame = ai4i_frame(4)
    assert build_schedule("ai4i", frame=frame).seed == get_settings().replay.seed


# -- guard rails ------------------------------------------------------------ #


def test_an_empty_frame_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        build_schedule("ai4i", settings=get_settings(), frame=ai4i_frame(1).iloc[0:0])


def test_a_ragged_cadence_is_rejected() -> None:
    """A dataset off the configured grid would silently desynchronise the clock."""
    frame = ai4i_frame(4)
    frame.loc[frame.index[-1], "dataset_ts"] += timedelta(minutes=1)
    with pytest.raises(ValueError, match="off the"):
        build_schedule("ai4i", settings=get_settings(), frame=frame)


def test_row_interval_comes_from_settings_not_from_a_literal() -> None:
    settings = get_settings()
    assert plant_row_interval("ai4i", settings) == timedelta(
        seconds=settings.plants.ai4i.row_interval_seconds
    )
    assert plant_row_interval("ims", settings) == timedelta(
        seconds=settings.plants.ims.row_interval_seconds
    )
