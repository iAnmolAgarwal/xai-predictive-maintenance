"""Every command on ``xpm/control/replay/cmd``, and every way to get one wrong.

The contract is blunt: a valid command changes the run and is acknowledged by a
retained ``ReplayState``; an invalid one is logged and dropped, and the tick
loop keeps running either way. The publisher is exercised as a live task, so
"pause stops emission" means *no further telemetry was actually published*.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from xpm.config import Settings, get_settings
from xpm.contracts.mqtt import ReplayCommand
from xpm.replay.control import ReplayCommandError, ReplayControl
from xpm.replay.publisher import ReplayPublisher

from . import AI4I_START, FakeMqttClient, VirtualTimeSource, drain, small_schedule

#: Long enough that no test can reach the end of the schedule by accident: the
#: virtual clock runs a tick per event-loop turn, so a short schedule would be
#: exhausted before a command landed.
TICKS = 500
MACHINES = 2


def control_settings(**overrides: Any) -> Settings:
    """Settings with ``loop`` off so a test run has a definite end."""
    base = get_settings()
    replay = base.replay.model_copy(update={"loop": False, **overrides})
    return base.model_copy(update={"replay": replay})


class Harness:
    """A running publisher plus its control listener and fake broker."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = FakeMqttClient()
        self.time = VirtualTimeSource()
        self.schedule = small_schedule(settings, ticks=TICKS, machines=MACHINES)
        self.publisher = ReplayPublisher(
            self.client,
            settings=settings,
            plant_id="ai4i",
            seed=settings.replay.seed,
            schedule_factory=lambda plant, seed: small_schedule(
                settings, plant_id=plant, ticks=TICKS, machines=MACHINES, seed=seed
            ),
            time_source=self.time,
        )
        self.control = ReplayControl(self.publisher)
        self.task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.publisher.run())
        await drain(20)

    async def stop(self) -> None:
        self.publisher.stop()
        if self.task is not None:
            await asyncio.wait_for(self.task, timeout=5.0)

    async def send(self, **fields: Any) -> bool:
        """Apply one command, without letting the tick loop run afterwards."""
        payload = ReplayCommand(request_id="req_00ff", **fields).model_dump_json()
        return await self.control.handle(payload.encode("utf-8"))

    @property
    def telemetry_count(self) -> int:
        return len(self.client.telemetry)

    def last_state(self) -> dict[str, Any]:
        return self.client.states[-1].json


@pytest.fixture
async def harness() -> AsyncIterator[Harness]:
    running = Harness(control_settings())
    await running.start()
    try:
        yield running
    finally:
        await running.stop()


# -- play / pause ----------------------------------------------------------- #


async def test_pause_stops_emission(harness: Harness) -> None:
    assert await harness.send(command="pause") is True
    settled = harness.telemetry_count
    await drain(200)
    assert harness.telemetry_count == settled
    assert harness.last_state()["playing"] is False


async def test_resume_continues_from_the_same_seq(harness: Harness) -> None:
    await harness.send(command="pause")
    await drain(20)
    last_seq = harness.client.telemetry[-1].json["seq"]
    resumed_from = harness.publisher.clock.tick

    assert await harness.send(command="play") is True
    await drain(50)
    next_seq = harness.client.telemetry[harness.telemetry_count - 1].json["seq"]
    assert resumed_from == last_seq + 1
    assert next_seq >= resumed_from
    # No row is replayed and none is skipped across the pause.
    seqs = [message.json["seq"] for message in harness.client.telemetry]
    assert sorted(set(seqs)) == list(range(max(seqs) + 1))
    assert harness.last_state()["playing"] is True


async def test_play_while_playing_is_accepted_and_idempotent(harness: Harness) -> None:
    assert await harness.send(command="play") is True
    assert harness.publisher.playing is True


async def test_pause_and_play_each_publish_a_retained_state(harness: Harness) -> None:
    before = len(harness.client.states)
    await harness.send(command="pause")
    await harness.send(command="play")
    published = harness.client.states[before:]
    assert len(published) == 2
    assert all(message.retain and message.qos == 1 for message in published)
    assert [message.json["playing"] for message in published] == [False, True]


# -- speed ------------------------------------------------------------------ #


@pytest.mark.parametrize("speed", [0.5, 1.0, 5.0, 20.0])
async def test_every_allowed_speed_is_accepted(harness: Harness, speed: float) -> None:
    assert await harness.send(command="set_speed", speed=speed) is True
    assert harness.publisher.speed == speed
    assert harness.last_state()["speed"] == speed


async def test_an_out_of_enum_speed_is_rejected_before_it_reaches_the_publisher(
    harness: Harness,
) -> None:
    """``3.0`` is not in ``replay.allowed_speeds``; the contract literal rejects it."""
    payload = json.dumps(
        {
            "schema_version": 1,
            "command": "set_speed",
            "speed": 3.0,
            "dataset_ts": None,
            "request_id": "req_dead",
        }
    )
    assert await harness.control.handle(payload.encode("utf-8")) is False
    assert harness.publisher.speed == 1.0


async def test_set_speed_without_a_speed_is_rejected(harness: Harness) -> None:
    assert await harness.send(command="set_speed") is False
    assert harness.publisher.speed == 1.0


async def test_a_speed_outside_the_configured_list_is_refused_by_the_publisher(
    harness: Harness,
) -> None:
    """Defence in depth: the publisher re-checks against ``allowed_speeds``."""
    with pytest.raises(ValueError, match="not one of"):
        await harness.publisher.set_speed(2.0)


async def test_changing_speed_does_not_move_dataset_time(harness: Harness) -> None:
    before = harness.publisher.clock.dataset_ts
    await harness.send(command="set_speed", speed=20.0)
    assert harness.publisher.clock.dataset_ts == before


# -- seek ------------------------------------------------------------------- #


async def test_seek_jumps_and_re_emits_a_state(harness: Harness) -> None:
    target = AI4I_START + timedelta(minutes=5 * 30)
    before = len(harness.client.states)
    assert await harness.send(command="seek", dataset_ts=target) is True
    state = harness.last_state()
    assert len(harness.client.states) == before + 1
    assert state["dataset_ts"] == "2026-01-01T02:30:00.000Z"
    assert harness.publisher.clock.tick == 30
    assert state["rows_published"] == 30 * MACHINES


async def test_seek_without_a_dataset_ts_is_rejected(harness: Harness) -> None:
    tick = harness.publisher.clock.tick
    assert await harness.send(command="seek") is False
    assert harness.publisher.clock.tick == tick


async def test_seek_backwards_replays_the_same_rows(harness: Harness) -> None:
    await drain(60)
    assert await harness.send(command="seek", dataset_ts=AI4I_START) is True
    await drain(20)
    assert harness.publisher.clock.dataset_ts >= AI4I_START
    first_seqs = [message.json["seq"] for message in harness.client.telemetry]
    assert first_seqs.count(0) >= 2  # tick 0 was published before and after the seek


# -- restart and plant switch ----------------------------------------------- #


async def test_restart_mints_a_new_run_id_and_rewinds(harness: Harness) -> None:
    await drain(60)
    before = harness.publisher.run_id
    assert await harness.send(command="restart") is True
    assert harness.publisher.run_id != before
    assert harness.publisher.loop_index == 1
    assert harness.publisher.clock.tick == 0
    assert harness.last_state()["run_id"] == harness.publisher.run_id


async def test_restart_with_a_seed_changes_the_run_id_and_the_seeded_order(
    harness: Harness,
) -> None:
    assert await harness.send(command="restart", seed=7) is True
    assert harness.publisher.seed == 7
    assert harness.publisher.schedule.seed == 7
    assert harness.last_state()["seed"] == 7


async def test_restart_with_a_plant_id_switches_plant(harness: Harness) -> None:
    assert await harness.send(command="restart", plant_id="ims") is True
    assert harness.publisher.plant_id == "ims"
    await drain(5)
    state = harness.last_state()
    assert state["plant_id"] == "ims"
    assert state["machine_count"] == MACHINES
    await drain(40)
    assert harness.client.telemetry[-1].topic.startswith("xpm/ims/ims-")


async def test_restart_preserves_the_operator_chosen_speed(harness: Harness) -> None:
    await harness.send(command="set_speed", speed=20.0)
    await harness.send(command="restart")
    assert harness.publisher.speed == 20.0


# -- malformed input -------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not json at all",
        b"{}",
        b'{"schema_version": 1, "command": "explode", "request_id": "req_0001"}',
        b'{"schema_version": 1, "command": "play"}',
        b'{"schema_version": 1, "command": "play", "request_id": "nope"}',
        b'{"schema_version": 1, "command": "play", "request_id": "req_0001", "extra": 1}',
        b'{"schema_version": 1, "command": "seek", "dataset_ts": "not-a-date",'
        b' "request_id": "req_0001"}',
        b'{"schema_version": 1, "command": "restart", "plant_id": "mars",'
        b' "request_id": "req_0001"}',
        "\udcff".encode("utf-8", "surrogateescape"),
    ],
)
async def test_malformed_commands_are_rejected_and_never_crash_the_publisher(
    harness: Harness, payload: bytes
) -> None:
    before = harness.publisher.run_id
    assert await harness.control.handle(payload) is False
    assert harness.publisher.run_id == before
    assert harness.publisher.stopped is False
    # The tick loop is untouched and still publishing.
    settled = harness.telemetry_count
    await drain(50)
    assert harness.telemetry_count > settled


async def test_an_empty_payload_is_rejected(harness: Harness) -> None:
    assert await harness.control.handle(None) is False


async def test_a_string_payload_is_accepted_as_readily_as_bytes(harness: Harness) -> None:
    payload = ReplayCommand(command="pause", request_id="req_0001").model_dump_json()
    assert await harness.control.handle(payload) is True
    assert harness.publisher.playing is False


def test_decode_returns_none_rather_than_raising(harness: Harness) -> None:
    assert harness.control.decode(b"{") is None


async def test_apply_raises_for_a_missing_companion_field(harness: Harness) -> None:
    """``handle`` swallows this; ``apply`` is the strict, testable core."""
    command = ReplayCommand(command="seek", request_id="req_0001")
    with pytest.raises(ReplayCommandError, match="seek requires"):
        await harness.control.apply(command)


# -- the listener loop ------------------------------------------------------ #


async def test_listen_consumes_a_stream_of_payloads(harness: Harness) -> None:
    async def payloads() -> AsyncIterator[bytes]:
        yield (
            ReplayCommand(command="set_speed", speed=5.0, request_id="req_0001")
            .model_dump_json()
            .encode()
        )
        yield b"garbage"
        yield ReplayCommand(command="pause", request_id="req_0002").model_dump_json().encode()

    await harness.control.listen(payloads())
    assert harness.publisher.speed == 5.0
    assert harness.publisher.playing is False


async def test_listen_stops_when_the_publisher_stops(harness: Harness) -> None:
    """The listener must not consume a command after the run has stopped."""
    commands = [
        ReplayCommand(command="pause", request_id="req_0001").model_dump_json().encode(),
        ReplayCommand(command="set_speed", speed=20.0, request_id="req_0002")
        .model_dump_json()
        .encode(),
    ]
    consumed: list[int] = []

    async def payloads() -> AsyncIterator[bytes]:
        for index, command in enumerate(commands):
            consumed.append(index)
            yield command

    harness.publisher.stop()  # e.g. SIGTERM arrived while commands were queued
    await harness.control.listen(payloads())
    assert consumed == [0]
    assert harness.publisher.playing is False
    assert harness.publisher.speed == 1.0  # the second command was never read


def test_control_exposes_its_publisher(harness: Harness) -> None:
    assert harness.control.publisher is harness.publisher
