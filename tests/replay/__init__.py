"""Tests for :mod:`xpm.replay`, plus the doubles every one of them shares.

``VirtualTimeSource`` makes a replay run in microseconds: it never touches the
wall clock, it just accumulates the durations the publisher asks to sleep for.
That is what lets ``test_determinism`` prove a 1x run and a 20x run emit the
identical message sequence — the only thing that differs between them is the
virtual wall time the sleeps accumulate.

``FakeMqttClient`` records every publish with its topic, QoS and retain flag, so
the §3.3 topic table is asserted rather than assumed.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pandas as pd

from xpm.config import Settings
from xpm.data.schema import (
    AI4I_CHANNELS,
    AI4I_FAILURE_MODES,
    IMS_CHANNELS,
    PlantId,
)
from xpm.replay.mapping import ReplaySchedule, build_schedule

__all__ = [
    "AI4I_START",
    "FakeMqttClient",
    "PublishedMessage",
    "VirtualTimeSource",
    "ai4i_frame",
    "drain",
    "ims_frame",
    "small_schedule",
]

#: The fixed AI4I dataset start from ``config/settings.yaml`` (§3.2.1).
AI4I_START: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    """One recorded ``publish`` call."""

    topic: str
    payload: bytes
    qos: int
    retain: bool

    @property
    def json(self) -> dict[str, Any]:
        decoded: dict[str, Any] = json.loads(self.payload)
        return decoded


@dataclass(slots=True)
class FakeMqttClient:
    """An in-memory stand-in for the slice of ``aiomqtt.Client`` we use."""

    messages: list[PublishedMessage] = field(default_factory=list)

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        assert payload is not None, "the replay publisher never sends an empty payload"
        self.messages.append(PublishedMessage(topic, payload, qos, retain))

    def of_kind(self, suffix: str) -> list[PublishedMessage]:
        """Recorded messages whose topic ends with ``suffix``."""
        return [message for message in self.messages if message.topic.endswith(suffix)]

    @property
    def telemetry(self) -> list[PublishedMessage]:
        return self.of_kind("/telemetry")

    @property
    def states(self) -> list[PublishedMessage]:
        return self.of_kind("control/replay/state")


@dataclass(slots=True)
class VirtualTimeSource:
    """A monotonic clock that advances only when someone sleeps on it.

    Every requested duration is recorded in :attr:`sleeps`, which is how the
    runner tests read the reconnect backoff off a run that is also sleeping out
    its ordinary tick pacing.
    """

    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += max(seconds, 0.0)
        # Still yield, so other tasks on the loop make progress exactly as they
        # would against the real event loop.
        await asyncio.sleep(0)


async def drain(steps: int = 400) -> None:
    """Let the publisher task run for ``steps`` event-loop turns."""
    for _ in range(steps):
        await asyncio.sleep(0)


def ai4i_frame(ticks: int, machines: int = 3) -> pd.DataFrame:
    """A tiny AI4I-shaped frame on the real 5-minute grid.

    Row values are a deterministic function of the tick and machine index, so a
    golden comparison is meaningful without shipping a parquet fixture.
    """
    records: list[dict[str, Any]] = []
    for tick in range(ticks):
        for machine in range(1, machines + 1):
            index = tick * machines + (machine - 1)
            records.append(
                {
                    "machine_id": f"ai4i-{machine:02d}",
                    "dataset_ts": AI4I_START + timedelta(minutes=5 * tick),
                    **{
                        name: float(index + position) for position, name in enumerate(AI4I_CHANNELS)
                    },
                    "machine_failure": index % 7 == 0,
                    **{
                        name: (index % (5 + offset) == 0)
                        for offset, name in enumerate(AI4I_FAILURE_MODES)
                    },
                    "variant": "LMH"[index % 3],
                    "source_row": index,
                }
            )
    frame = pd.DataFrame.from_records(records)
    frame["machine_id"] = frame["machine_id"].astype("string")
    frame["variant"] = frame["variant"].astype("string")
    frame["source_row"] = frame["source_row"].astype("int32")
    for name in ("machine_failure", *AI4I_FAILURE_MODES):
        frame[name] = frame[name].astype("int8")
    return frame


def ims_frame(ticks: int, machines: int = 4) -> pd.DataFrame:
    """A tiny IMS-shaped frame on the real 10-minute grid."""
    start = datetime(2004, 2, 12, 10, 32, 39, tzinfo=UTC)
    records: list[dict[str, Any]] = []
    for tick in range(ticks):
        for machine in range(1, machines + 1):
            index = tick * machines + (machine - 1)
            records.append(
                {
                    "machine_id": f"ims-{machine:02d}",
                    "dataset_ts": start + timedelta(minutes=10 * tick),
                    **{
                        name: float(index) / 1000.0 + position
                        for position, name in enumerate(IMS_CHANNELS)
                    },
                    "failure_imminent": index % 11 == 0,
                    "bearing": machine,
                    "source_file": f"2004.02.12.{10 + tick:02d}.32.39",
                }
            )
    frame = pd.DataFrame.from_records(records)
    frame["machine_id"] = frame["machine_id"].astype("string")
    frame["source_file"] = frame["source_file"].astype("string")
    frame["failure_imminent"] = frame["failure_imminent"].astype("int8")
    frame["bearing"] = frame["bearing"].astype("int8")
    return frame


def small_schedule(
    settings: Settings,
    *,
    plant_id: PlantId = "ai4i",
    ticks: int = 4,
    machines: int = 3,
    seed: int = 42,
) -> ReplaySchedule:
    """A schedule over the synthetic frames above."""
    frame = ai4i_frame(ticks, machines) if plant_id == "ai4i" else ims_frame(ticks, machines)
    return build_schedule(plant_id, settings=settings, seed=seed, frame=frame)
