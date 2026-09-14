"""Dataset rows -> virtual machines -> a deterministic per-tick schedule.

The row/machine assignment itself is *not* random: it is baked into the
committed processed parquet by ``xpm.data`` (backend.md §3.2). AI4I deals its
10 000 rows round-robin into 12 machines (row *i* -> ``ai4i-{(i mod 12)+1:02d}``)
so every tile has a similar failure prevalence; IMS maps bearing *b* -> ``ims-0b``
and preserves the real 10-minute recording cadence. This module re-derives that
grid, verifies it, and turns it into the exact sequence the publisher emits.

**What ``replay.seed`` affects, and what it does not.** The seed is an input to
``run_id`` (§3.1) and it fixes the *order in which the machines of one tick are
published* — a stable, reproducible shuffle so a demo does not always light the
plant-floor tiles left to right. It does **not** touch which row belongs to
which machine, which ``dataset_ts`` a row carries, how many rows exist, or the
tick a row lands on: all four come from the dataset and are seed-independent.
So two runs with different seeds publish the same rows at the same dataset
instants, in a different within-tick order, under different run ids.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import Random
from typing import Any, Final

import pandas as pd

from xpm.config import Settings, get_settings
from xpm.contracts.mqtt import (
    Ai4iLabels,
    Ai4iMeta,
    FailureModes,
    ImsLabels,
    ImsMeta,
)
from xpm.data import loader
from xpm.data.schema import AI4I_FAILURE_MODES, PlantId, channels_for, machine_id

__all__ = [
    "ReplaySchedule",
    "ScheduledRow",
    "build_schedule",
    "expected_machine_id",
    "plant_row_interval",
]

#: Tolerance when checking that the dataset's timestamps sit on a uniform grid.
_GRID_TOLERANCE: Final[timedelta] = timedelta(milliseconds=1)


@dataclass(frozen=True, slots=True)
class ScheduledRow:
    """One dataset row, pre-shaped into the parts of a ``TelemetryMessage``."""

    machine_id: str
    dataset_ts: datetime
    channels: Mapping[str, float]
    labels: Ai4iLabels | ImsLabels
    meta: Ai4iMeta | ImsMeta


@dataclass(frozen=True, slots=True)
class ReplaySchedule:
    """Everything a run publishes, in publication order.

    ``ticks[k]`` is the group of rows published at ``dataset_start + k *
    row_interval``, ordered by the seeded within-tick permutation. A tick may
    hold fewer rows than there are machines: AI4I's round-robin leaves four
    machines one row longer than the other eight, so the final tick is short.
    """

    plant_id: PlantId
    seed: int
    dataset_start: datetime
    dataset_end: datetime
    row_interval: timedelta
    machine_ids: tuple[str, ...]
    ticks: tuple[tuple[ScheduledRow, ...], ...]

    @property
    def tick_count(self) -> int:
        return len(self.ticks)

    @property
    def rows_total(self) -> int:
        return sum(len(tick) for tick in self.ticks)

    @property
    def machine_count(self) -> int:
        return len(self.machine_ids)


def expected_machine_id(plant_id: PlantId, source_index: int, machine_count: int) -> str:
    """The machine a 0-based source row belongs to (backend.md §3.2).

    AI4I deals rows round-robin; IMS's ``source_index`` is its 0-based bearing
    column, so the same expression covers both plants.
    """
    if machine_count < 1:
        raise ValueError(f"machine_count must be at least 1, got {machine_count!r}")
    return machine_id(plant_id, (source_index % machine_count) + 1)


def plant_row_interval(plant_id: PlantId, settings: Settings) -> timedelta:
    """Dataset-time advance of one tick, from ``plants.<id>.row_interval_seconds``."""
    seconds = (
        settings.plants.ai4i.row_interval_seconds
        if plant_id == "ai4i"
        else settings.plants.ims.row_interval_seconds
    )
    return timedelta(seconds=seconds)


def build_schedule(
    plant_id: PlantId,
    *,
    settings: Settings | None = None,
    seed: int | None = None,
    frame: pd.DataFrame | None = None,
) -> ReplaySchedule:
    """Build the publication schedule for ``plant_id``.

    ``frame`` defaults to the committed processed parquet via
    :mod:`xpm.data.loader`; tests pass a small frame instead. ``seed`` defaults
    to ``replay.seed`` and affects only the within-tick machine order (and,
    through the publisher, ``run_id``).
    """
    resolved = settings if settings is not None else get_settings()
    resolved_seed = seed if seed is not None else resolved.replay.seed
    data = loader.load_plant(plant_id) if frame is None else frame
    if data.empty:
        raise ValueError(f"{plant_id}: processed dataset is empty; nothing to replay")

    row_interval = plant_row_interval(plant_id, resolved)
    stamps = _tick_stamps(plant_id, data, row_interval)
    rng = Random(f"{resolved_seed}|{plant_id}")

    by_tick: list[list[ScheduledRow]] = [[] for _ in stamps]
    index_of = {stamp: position for position, stamp in enumerate(stamps)}
    for row in _iter_rows(plant_id, data):
        by_tick[index_of[row.dataset_ts]].append(row)

    ticks: list[tuple[ScheduledRow, ...]] = []
    for group in by_tick:
        group.sort(key=lambda row: row.machine_id)
        rng.shuffle(group)
        ticks.append(tuple(group))

    machine_ids = tuple(sorted({str(value) for value in data["machine_id"].unique()}))
    return ReplaySchedule(
        plant_id=plant_id,
        seed=resolved_seed,
        dataset_start=stamps[0],
        dataset_end=stamps[-1],
        row_interval=row_interval,
        machine_ids=machine_ids,
        ticks=tuple(ticks),
    )


def _tick_stamps(
    plant_id: PlantId, data: pd.DataFrame, row_interval: timedelta
) -> tuple[datetime, ...]:
    """Distinct dataset instants, verified to be a uniform ``row_interval`` grid."""
    stamps = tuple(_as_datetime(value) for value in sorted(pd.Index(data["dataset_ts"].unique())))
    start = stamps[0]
    for position, stamp in enumerate(stamps):
        drift = abs(stamp - (start + position * row_interval))
        if drift > _GRID_TOLERANCE:
            raise ValueError(
                f"{plant_id}: dataset_ts {stamp.isoformat()} is off the "
                f"{row_interval} grid by {drift}; the replay clock assumes a "
                "uniform cadence (backend.md §3.2)"
            )
    return stamps


def _as_datetime(value: object) -> datetime:
    """Normalise a pandas timestamp to a tz-aware :class:`datetime`."""
    # pandas-stubs types `Timestamp.__new__` far more narrowly than the runtime
    # accepts: the values arriving here are `numpy.datetime64` / `Timestamp`
    # objects read back out of a parquet column, which `object` is the only
    # honest static type for.
    return pd.Timestamp(value).to_pydatetime()  # type: ignore[arg-type]


def _iter_rows(plant_id: PlantId, data: pd.DataFrame) -> list[ScheduledRow]:
    """Shape every dataset row into a :class:`ScheduledRow`."""
    channels = channels_for(plant_id)
    rows: list[ScheduledRow] = []
    for record in data.to_dict(orient="records"):
        machine = str(record["machine_id"])
        rows.append(
            ScheduledRow(
                machine_id=machine,
                dataset_ts=_as_datetime(record["dataset_ts"]),
                channels={name: float(record[name]) for name in channels},
                labels=_labels(plant_id, record),
                meta=_meta(plant_id, record),
            )
        )
    return rows


def _labels(plant_id: PlantId, record: Mapping[Hashable, Any]) -> Ai4iLabels | ImsLabels:
    if plant_id == "ims":
        return ImsLabels(failure_imminent=int(record["failure_imminent"]))
    return Ai4iLabels(
        machine_failure=int(record["machine_failure"]),
        failure_modes=FailureModes(**{name: int(record[name]) for name in AI4I_FAILURE_MODES}),
    )


def _meta(plant_id: PlantId, record: Mapping[Hashable, Any]) -> Ai4iMeta | ImsMeta:
    if plant_id == "ims":
        return ImsMeta(
            bearing=int(record["bearing"]),
            source_file=str(record["source_file"]),
        )
    return Ai4iMeta(
        variant=str(record["variant"]),
        source_row=int(record["source_row"]),
    )
