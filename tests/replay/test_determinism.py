"""The reproducibility guarantee of R5, asserted end to end.

A replay run is driven against an in-memory MQTT client and a virtual clock,
and the resulting stream is compared to a checked-in golden JSONL file. Then the
same run is repeated at 20x and proved to emit the *identical* ``(machine_id,
dataset_ts, seq, payload)`` sequence — only the wall-clock ``ts`` and the
virtual wall time the run consumed may differ.

That is exactly the property the rest of the system leans on: ``alert_id`` is
``blake2b(run_id|machine_id|dataset_ts_ms|model_id)``, so if this test holds,
alert ids, explanations and scrub results are speed-independent too.

Regenerating the golden file (only ever with a *reviewed* protocol change)::

    XPM_REPLAY_GOLDEN_WRITE=1 uv run pytest tests/replay/test_determinism.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from xpm.config import get_settings
from xpm.replay.publisher import (
    ReplayPublisher,
    control_cmd_topic,
    control_state_topic,
    run_id_for,
    telemetry_topic,
)

from . import FakeMqttClient, VirtualTimeSource, drain, small_schedule

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "golden_run_seed42_1x.jsonl"

#: The golden run: a 6-tick, 4-machine AI4I slice at seed 42. Small enough to
#: read in a diff, wide enough to exercise the within-tick permutation.
GOLDEN_TICKS = 6
GOLDEN_MACHINES = 4
GOLDEN_SEED = 42


async def run_capture(speed: float) -> tuple[FakeMqttClient, VirtualTimeSource, ReplayPublisher]:
    """Run the golden replay to exhaustion at ``speed`` with ``loop=false``."""
    settings = get_settings().model_copy(
        update={
            "replay": get_settings().replay.model_copy(
                update={"loop": False, "speed": speed, "autostart": True}
            )
        }
    )
    schedule = small_schedule(
        settings, ticks=GOLDEN_TICKS, machines=GOLDEN_MACHINES, seed=GOLDEN_SEED
    )
    client = FakeMqttClient()
    time = VirtualTimeSource()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        seed=GOLDEN_SEED,
        schedule_factory=lambda _plant, _seed: schedule,
        time_source=time,
    )
    await asyncio.wait_for(publisher.run(), timeout=5.0)
    await drain(10)
    return client, time, publisher


def telemetry_records(client: FakeMqttClient) -> list[dict[str, Any]]:
    """Every telemetry payload, with the wall clock dropped."""
    records: list[dict[str, Any]] = []
    for message in client.telemetry:
        payload = message.json
        payload.pop("ts")
        records.append({"topic": message.topic, "payload": payload})
    return records


def write_golden(records: list[dict[str, Any]]) -> None:
    """Serialise the golden stream: one compact JSON object per line."""
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def read_golden() -> list[dict[str, Any]]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


async def test_the_1x_run_matches_the_checked_in_golden_file() -> None:
    client, _, _ = await run_capture(1.0)
    records = telemetry_records(client)
    if os.environ.get("XPM_REPLAY_GOLDEN_WRITE") == "1":
        write_golden(records)
    assert records == read_golden()


async def test_20x_emits_the_identical_sequence_with_only_wall_timing_different() -> None:
    slow_client, slow_time, slow_publisher = await run_capture(1.0)
    fast_client, fast_time, fast_publisher = await run_capture(20.0)

    def key(record: dict[str, Any]) -> tuple[str, str, int]:
        payload = record["payload"]
        return payload["machine_id"], payload["dataset_ts"], payload["seq"]

    slow = telemetry_records(slow_client)
    fast = telemetry_records(fast_client)
    assert [key(record) for record in fast] == [key(record) for record in slow]
    assert fast == slow
    assert fast_publisher.run_id == slow_publisher.run_id

    # Only the pacing differs, and by exactly the speed ratio.
    assert slow_time.now == pytest.approx(fast_time.now * 20.0)
    assert slow_time.now > fast_time.now


async def test_wall_clock_ts_is_the_only_field_that_moves_between_runs() -> None:
    first, _, _ = await run_capture(1.0)
    second, _, _ = await run_capture(1.0)
    raw_first = [message.json for message in first.telemetry]
    raw_second = [message.json for message in second.telemetry]
    assert raw_first != raw_second  # `ts` is a real wall clock, so it moves
    for left, right in zip(raw_first, raw_second, strict=True):
        assert left.keys() == right.keys()
        assert {k: v for k, v in left.items() if k != "ts"} == {
            k: v for k, v in right.items() if k != "ts"
        }


async def test_the_run_id_is_speed_independent_by_construction() -> None:
    settings = get_settings()
    schedule = small_schedule(settings, ticks=GOLDEN_TICKS, machines=GOLDEN_MACHINES)
    expected = run_id_for(GOLDEN_SEED, "ai4i", 0, schedule.dataset_start)
    for speed in settings.replay.allowed_speeds:
        _, _, publisher = await run_capture(float(speed))
        assert publisher.run_id == expected


async def test_every_message_lands_on_the_contracted_topic_with_the_right_qos() -> None:
    client, _, publisher = await run_capture(1.0)
    root = get_settings().mqtt.topic_root
    for message in client.telemetry:
        payload = message.json
        assert message.topic == f"{root}/ai4i/{payload['machine_id']}/telemetry"
        assert (message.qos, message.retain) == (0, False)
    for message in client.states:
        assert message.topic == f"{root}/control/replay/state"
        assert (message.qos, message.retain) == (1, True)
    assert len(client.telemetry) == GOLDEN_TICKS * GOLDEN_MACHINES
    assert publisher.rows_published == GOLDEN_TICKS * GOLDEN_MACHINES


async def test_seq_is_the_tick_index_and_agrees_with_dataset_time() -> None:
    client, _, publisher = await run_capture(1.0)
    interval = publisher.schedule.row_interval
    start = publisher.schedule.dataset_start
    for message in client.telemetry:
        payload = message.json
        seq = payload["seq"]
        expected = start + seq * interval
        assert payload["dataset_ts"] == expected.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Every machine of a tick shares the tick's seq.
    by_seq: dict[int, set[str]] = {}
    for message in client.telemetry:
        payload = message.json
        by_seq.setdefault(payload["seq"], set()).add(payload["machine_id"])
    assert sorted(by_seq) == list(range(GOLDEN_TICKS))
    assert all(len(machines) == GOLDEN_MACHINES for machines in by_seq.values())


async def test_the_golden_file_is_a_stable_serialisation() -> None:
    """Round-tripping the golden file must not reorder or reshape it."""
    records = read_golden()
    assert len(records) == GOLDEN_TICKS * GOLDEN_MACHINES
    rendered = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    assert rendered == GOLDEN.read_text(encoding="utf-8")


# -- production wiring ------------------------------------------------------ #


async def test_the_default_schedule_factory_reads_the_committed_parquet() -> None:
    """With no injected factory the publisher streams the real dataset."""
    settings = get_settings().model_copy(
        update={"replay": get_settings().replay.model_copy(update={"autostart": False})}
    )
    publisher = ReplayPublisher(
        FakeMqttClient(), settings=settings, plant_id="ims", time_source=VirtualTimeSource()
    )
    assert publisher.schedule.tick_count == 984
    assert publisher.schedule.machine_ids == ("ims-01", "ims-02", "ims-03", "ims-04")
    assert publisher.run_id == run_id_for(
        settings.replay.seed, "ims", 0, publisher.schedule.dataset_start
    )


async def test_a_wide_tick_yields_to_the_event_loop_every_publish_batch() -> None:
    """``replay.publish_batch`` bounds how long a tick can hog the loop."""
    base = get_settings()
    settings = base.model_copy(
        update={"replay": base.replay.model_copy(update={"loop": False, "publish_batch": 1})}
    )
    schedule = small_schedule(settings, ticks=2, machines=4, seed=GOLDEN_SEED)
    client = FakeMqttClient()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        schedule_factory=lambda _plant, _seed: schedule,
        time_source=VirtualTimeSource(),
    )
    await asyncio.wait_for(publisher.run(), timeout=5.0)
    # Order is preserved across the yields: the schedule order is the wire order.
    published = [message.json["machine_id"] for message in client.telemetry]
    expected = [row.machine_id for tick in schedule.ticks for row in tick]
    assert published == expected


def test_the_control_topics_match_the_topic_table() -> None:
    root = get_settings().mqtt.topic_root
    assert control_cmd_topic(root) == "xpm/control/replay/cmd"
    assert control_state_topic(root) == "xpm/control/replay/state"
    assert telemetry_topic(root, "ims", "ims-01") == "xpm/ims/ims-01/telemetry"
