"""Looping, run ids and the end of a finite run (R12, backend.md §4, §6).

``replay.loop`` defaults to true for demos: exhaustion increments
``loop_index``, mints a new ``run_id``, re-emits a retained ``ReplayState`` and
resumes from ``dataset_start``. The e2e overlay sets ``XPM_REPLAY__LOOP=false``,
which must give a run exactly one ``run_id`` and a final paused state.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xpm.config import Settings, get_settings
from xpm.replay.publisher import ReplayPublisher, run_id_for

from . import FakeMqttClient, VirtualTimeSource, drain, small_schedule

LOOP_TICKS = 10
LOOP_MACHINES = 2


def loop_settings(*, loop: bool, autostart: bool = True) -> Settings:
    base = get_settings()
    return base.model_copy(
        update={"replay": base.replay.model_copy(update={"loop": loop, "autostart": autostart})}
    )


def make_publisher(settings: Settings) -> tuple[ReplayPublisher, FakeMqttClient, VirtualTimeSource]:
    client = FakeMqttClient()
    time = VirtualTimeSource()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        schedule_factory=lambda _plant, seed: small_schedule(
            settings, ticks=LOOP_TICKS, machines=LOOP_MACHINES, seed=seed
        ),
        time_source=time,
    )
    return publisher, client, time


def state_payloads(client: FakeMqttClient) -> list[dict[str, Any]]:
    return [message.json for message in client.states]


# -- loop = true ------------------------------------------------------------ #


async def test_exhaustion_increments_loop_index_and_mints_a_new_run_id() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=True))
    task = asyncio.create_task(publisher.run())
    await drain(3 * LOOP_TICKS + 20)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)

    run_ids = [state["run_id"] for state in state_payloads(client)]
    loop_indices = [state["loop_index"] for state in state_payloads(client)]
    assert loop_indices[0] == 0
    assert max(loop_indices) >= 2
    assert len(set(run_ids)) == max(loop_indices) + 1
    # Every loop's run id is the documented hash of its loop index.
    for index in range(max(loop_indices) + 1):
        expected = run_id_for(publisher.seed, "ai4i", index, publisher.schedule.dataset_start)
        assert expected in run_ids


async def test_a_loop_resumes_at_dataset_start_and_restarts_seq() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=True))
    task = asyncio.create_task(publisher.run())
    await drain(2 * LOOP_TICKS + 20)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)

    by_run: dict[str, list[int]] = {}
    for message in client.telemetry:
        payload = message.json
        by_run.setdefault(payload["run_id"], []).append(payload["seq"])
    assert len(by_run) >= 2
    for seqs in by_run.values():
        assert min(seqs) == 0
        assert sorted(set(seqs)) == list(range(max(seqs) + 1))

    starts = {
        message.json["run_id"]: message.json["dataset_ts"]
        for message in client.telemetry
        if message.json["seq"] == 0
    }
    assert len(set(starts.values())) == 1


async def test_a_loop_re_emits_a_retained_state_before_resuming() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=True))
    task = asyncio.create_task(publisher.run())
    await drain(LOOP_TICKS + 20)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)

    loop_states = [state for state in state_payloads(client) if state["loop_index"] == 1]
    assert loop_states, "the publisher must announce the new run before resuming it"
    first = loop_states[0]
    assert first["rows_published"] == 0
    assert first["dataset_ts"] == first["dataset_start"]
    assert first["loop"] is True
    assert all(message.retain for message in client.states)


async def test_rows_published_resets_but_rows_total_does_not() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=True))
    task = asyncio.create_task(publisher.run())
    await drain(LOOP_TICKS + 20)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)
    for state in state_payloads(client):
        assert state["rows_total"] == LOOP_TICKS * LOOP_MACHINES
        assert state["rows_published"] <= state["rows_total"]


# -- loop = false ----------------------------------------------------------- #


async def test_loop_false_stops_with_one_run_id_and_a_final_paused_state() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=False))
    await asyncio.wait_for(publisher.run(), timeout=5.0)

    states = state_payloads(client)
    assert len({state["run_id"] for state in states}) == 1
    assert len({message.json["run_id"] for message in client.telemetry}) == 1
    assert states[-1]["playing"] is False
    assert states[-1]["rows_published"] == LOOP_TICKS * LOOP_MACHINES
    assert states[-1]["rows_published"] == states[-1]["rows_total"]
    assert publisher.loop_index == 0
    assert publisher.stopped is True


async def test_loop_false_publishes_every_row_exactly_once() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=False))
    await asyncio.wait_for(publisher.run(), timeout=5.0)
    seen = {(message.json["machine_id"], message.json["seq"]) for message in client.telemetry}
    assert len(seen) == len(client.telemetry) == LOOP_TICKS * LOOP_MACHINES


async def test_playing_a_finished_run_rewinds_it() -> None:
    """The dashboard's play button must not be a no-op on a finished run."""
    publisher, _client, _ = make_publisher(loop_settings(loop=False))
    await asyncio.wait_for(publisher.run(), timeout=5.0)
    await publisher.play()
    assert publisher.clock.tick == 0
    assert publisher.rows_published == 0
    assert publisher.playing is True


# -- autostart -------------------------------------------------------------- #


async def test_autostart_false_publishes_a_paused_state_and_no_telemetry() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=False, autostart=False))
    task = asyncio.create_task(publisher.run())
    await drain(50)
    assert publisher.playing is False
    assert client.telemetry == []
    assert state_payloads(client)[0]["playing"] is False

    await publisher.play()
    await drain(20)
    assert client.telemetry != []
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)


# -- the state heartbeat ---------------------------------------------------- #


async def test_the_retained_state_is_refreshed_on_the_heartbeat_interval() -> None:
    settings = loop_settings(loop=True)
    client = FakeMqttClient()
    time = VirtualTimeSource()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        schedule_factory=lambda _plant, seed: small_schedule(
            settings, ticks=400, machines=LOOP_MACHINES, seed=seed
        ),
        time_source=time,
        state_heartbeat_seconds=2.0,
    )
    task = asyncio.create_task(publisher.run())
    await drain(120)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)

    # 100 ticks at 2 Hz is 50 virtual seconds, i.e. ~25 heartbeats.
    assert time.now > 2.0
    assert len(client.states) >= int(time.now / 2.0)
    assert all(message.retain and message.qos == 1 for message in client.states)


async def test_the_heartbeat_interval_defaults_to_the_server_ping_interval() -> None:
    """There is no separate replay heartbeat knob: ``api.ws_ping_seconds`` is it.

    The assertion is behavioural rather than a private-attribute read: a run of
    known virtual duration must produce the number of refreshes that interval
    implies.
    """
    settings = loop_settings(loop=True)
    client = FakeMqttClient()
    time = VirtualTimeSource()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        schedule_factory=lambda _plant, seed: small_schedule(
            settings, ticks=400, machines=LOOP_MACHINES, seed=seed
        ),
        time_source=time,
    )
    task = asyncio.create_task(publisher.run())
    await drain(200)
    publisher.stop()
    await asyncio.wait_for(task, timeout=5.0)

    interval = float(settings.api.ws_ping_seconds)
    heartbeats = len(client.states) - 1  # the first state is the start-up one
    assert heartbeats == pytest.approx(time.now // interval, abs=1)


# -- state shape ------------------------------------------------------------ #


async def test_the_state_carries_every_field_the_dashboard_needs() -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=False))
    await publisher.publish_state()
    state = client.states[-1].json
    assert set(state) == {
        "schema_version",
        "run_id",
        "plant_id",
        "seed",
        "speed",
        "playing",
        "loop",
        "loop_index",
        "dataset_ts",
        "dataset_start",
        "dataset_end",
        "rows_published",
        "rows_total",
        "machine_count",
        "ts",
    }
    assert state["plant_id"] == "ai4i"
    assert state["machine_count"] == LOOP_MACHINES
    assert state["seed"] == get_settings().replay.seed


def test_run_id_is_stable_and_speed_independent() -> None:
    schedule = small_schedule(get_settings(), ticks=LOOP_TICKS, machines=LOOP_MACHINES)
    first = run_id_for(42, "ai4i", 0, schedule.dataset_start)
    assert first == run_id_for(42, "ai4i", 0, schedule.dataset_start)
    assert first != run_id_for(42, "ai4i", 1, schedule.dataset_start)
    assert first != run_id_for(7, "ai4i", 0, schedule.dataset_start)
    assert first != run_id_for(42, "ims", 0, schedule.dataset_start)
    assert first.startswith("run_")
    assert len(first) == len("run_") + 12


@pytest.mark.parametrize("loop", [True, False])
async def test_the_loop_flag_is_reported_on_the_wire(loop: bool) -> None:
    publisher, client, _ = make_publisher(loop_settings(loop=loop))
    await publisher.publish_state()
    assert client.states[-1].json["loop"] is loop
