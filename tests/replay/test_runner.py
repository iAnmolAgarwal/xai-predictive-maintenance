"""Process wiring: client identifier, reconnect backoff, shutdown (R21).

The broker is a double whose behaviour per connection is scripted, so a
"broker blip" is a real ``aiomqtt.MqttError`` raised out of a publish rather
than a mocked-out branch.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiomqtt
import pytest
import structlog

from xpm.config import Settings, get_settings
from xpm.contracts.mqtt import ReplayCommand
from xpm.replay import runner
from xpm.replay.publisher import ReplayPublisher, run_id_for
from xpm.replay.runner import (
    aiomqtt_client_factory,
    client_identifier,
    configure_logging,
    initial_run_id,
    install_signal_handlers,
    serve,
)

from . import FakeMqttClient, PublishedMessage, VirtualTimeSource, small_schedule

TICKS = 8
MACHINES = 2


def backoffs(time: VirtualTimeSource, settings: Settings) -> list[float]:
    """The reconnect sleeps of a run, separated from its tick pacing.

    A tick at 1x is ``1 / (2 Hz * 1)`` = 0.5 s and the shortest backoff is
    ``mqtt.reconnect_min_seconds`` = 1 s, so the two never overlap.
    """
    return [seconds for seconds in time.sleeps if seconds >= settings.mqtt.reconnect_min_seconds]


def runner_settings(**replay_overrides: Any) -> Settings:
    """Settings for a short, finite run."""
    base = get_settings()
    replay = base.replay.model_copy(update={"loop": False, **replay_overrides})
    return base.model_copy(update={"replay": replay})


def schedule_factory(settings: Settings) -> Any:
    def factory(plant: str, seed: int) -> Any:
        return small_schedule(settings, ticks=TICKS, machines=MACHINES, seed=seed)

    return factory


class ScriptedBroker:
    """A client factory whose connections fail on a scripted schedule."""

    def __init__(self, *, fail_connects: int = 0, fail_publish_after: int | None = None) -> None:
        self.fail_connects = fail_connects
        self.fail_publish_after = fail_publish_after
        self.identifiers: list[str] = []
        self.subscriptions: list[tuple[str, int]] = []
        self.messages_published: list[PublishedMessage] = []
        self.connections = 0
        self.live_connections = 0
        self.commands: list[bytes] = []

    def __call__(self, identifier: str) -> Any:
        self.identifiers.append(identifier)
        return self._connection()

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        self.connections += 1
        if self.connections <= self.fail_connects:
            raise aiomqtt.MqttError(f"connection {self.connections} refused")
        self.live_connections += 1
        yield _Connection(self, ordinal=self.live_connections)


class _Connection:
    """One live connection of a :class:`ScriptedBroker`."""

    def __init__(self, broker: ScriptedBroker, *, ordinal: int) -> None:
        self._broker = broker
        self._ordinal = ordinal
        self._published_here = 0

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        assert payload is not None
        limit = self._broker.fail_publish_after
        # Only the first connection that actually came up dies mid-stream.
        if limit is not None and self._ordinal == 1 and self._published_here >= limit:
            raise aiomqtt.MqttError("broker went away mid-publish")
        self._published_here += 1
        self._broker.messages_published.append(PublishedMessage(topic, payload, qos, retain))

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self._broker.subscriptions.append((topic, qos))

    @property
    def messages(self) -> AsyncIterator[Any]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[Any]:
        for payload in self._broker.commands:
            yield _Message(payload)
        # An idle control topic must not end the listener or the run.
        while True:
            await asyncio.sleep(0)


class _Message:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload


# -- the client identifier (R21, §3.3) -------------------------------------- #


async def test_the_client_identifier_is_xpm_replay_run_id() -> None:
    settings = runner_settings()
    broker = ScriptedBroker()
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    schedule = small_schedule(settings, ticks=TICKS, machines=MACHINES)
    expected = run_id_for(settings.replay.seed, "ai4i", 0, schedule.dataset_start)
    assert broker.identifiers == [f"xpm-replay-{expected}"]
    assert publisher.run_id == expected


def test_client_identifier_and_initial_run_id_are_pure_helpers() -> None:
    settings = get_settings()
    schedule = small_schedule(settings, ticks=4, machines=2)
    run_id = initial_run_id("ai4i", settings.replay.seed, schedule)
    assert run_id == run_id_for(settings.replay.seed, "ai4i", 0, schedule.dataset_start)
    assert client_identifier(run_id) == f"xpm-replay-{run_id}"


async def test_the_identifier_is_minted_before_the_connection_is_opened() -> None:
    """It must not depend on state that only exists after connecting."""
    settings = runner_settings()
    broker = ScriptedBroker(fail_connects=1)
    await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    assert len(set(broker.identifiers)) == 1
    assert broker.identifiers[0].startswith("xpm-replay-run_")


# -- reconnect (R21, blocking 4) -------------------------------------------- #


async def test_a_refused_connection_is_retried_and_the_run_completes() -> None:
    settings = runner_settings()
    broker = ScriptedBroker(fail_connects=1)
    time = VirtualTimeSource()
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=time,
    )
    assert broker.connections == 2
    assert publisher.rows_published == TICKS * MACHINES
    assert publisher.stopped is True
    assert backoffs(time, settings) == [settings.mqtt.reconnect_min_seconds]


async def test_a_mid_publish_failure_reconnects_and_keeps_the_same_run() -> None:
    settings = runner_settings()
    broker = ScriptedBroker(fail_publish_after=5)
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    assert broker.connections == 2
    run_ids = {
        message.json["run_id"]
        for message in broker.messages_published
        if message.topic.endswith("/telemetry")
    }
    assert run_ids == {publisher.run_id}
    assert publisher.stopped is True


async def test_the_backoff_grows_exponentially_and_is_capped() -> None:
    attempts = 8
    settings = runner_settings()
    broker = ScriptedBroker(fail_connects=attempts)
    time = VirtualTimeSource()
    await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=time,
    )
    minimum = settings.mqtt.reconnect_min_seconds
    maximum = settings.mqtt.reconnect_max_seconds
    expected: list[float] = []
    delay = minimum
    for _ in range(attempts):
        expected.append(delay)
        delay = min(delay * 2.0, maximum)
    assert broker.connections == attempts + 1
    assert backoffs(time, settings) == expected
    assert expected[-1] == maximum  # the cap is reached within 8 attempts
    assert expected[:3] == [minimum, minimum * 2, minimum * 4]


async def test_a_successful_connect_resets_the_backoff() -> None:
    """Two separate blips must not compound into a long wait."""
    settings = runner_settings()
    broker = ScriptedBroker(fail_connects=1, fail_publish_after=4)
    time = VirtualTimeSource()
    await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=time,
    )
    assert broker.connections == 3
    minimum = settings.mqtt.reconnect_min_seconds
    # Not [min, 2*min]: the connection that came up in between reset the delay.
    assert backoffs(time, settings) == [minimum, minimum]


async def test_a_stop_during_a_blip_ends_the_run_without_reconnecting() -> None:
    """A SIGTERM during a reconnect backoff must end the process, not retry."""
    settings = runner_settings()
    started: list[ReplayPublisher] = []

    class StoppingBroker(ScriptedBroker):
        """Stops the run on the second connect attempt, then fails it."""

        def __call__(self, identifier: str) -> Any:
            if self.connections >= 1:
                started[0].stop()
            return super().__call__(identifier)

    broker = StoppingBroker(fail_connects=5)
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
        on_start=started.append,
    )
    assert started == [publisher]
    assert publisher.stopped is True
    assert broker.connections == 2  # one blip, one attempt that found the stop
    assert publisher.rows_published == 0


# -- subscription and control ----------------------------------------------- #


async def test_the_runner_subscribes_to_the_control_topic_at_qos_1() -> None:
    settings = runner_settings()
    broker = ScriptedBroker()
    await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    assert broker.subscriptions == [("xpm/control/replay/cmd", 1)]


async def test_a_command_on_the_control_topic_reaches_the_publisher() -> None:
    settings = runner_settings()
    broker = ScriptedBroker()
    broker.commands = [
        ReplayCommand(command="set_speed", speed=5.0, request_id="req_00aa")
        .model_dump_json()
        .encode("utf-8")
    ]
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    assert publisher.speed == 5.0


# -- shutdown (review item 9) ----------------------------------------------- #


async def test_a_final_retained_state_is_published_after_the_run_stops() -> None:
    settings = runner_settings()
    broker = ScriptedBroker()
    publisher = await serve(
        settings,
        client_factory=broker,
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    states = [message for message in broker.messages_published if message.topic.endswith("/state")]
    final = states[-1].json
    assert states[-1].retain is True
    assert states[-1].qos == 1
    assert final["playing"] is False
    assert final["run_id"] == publisher.run_id
    assert final["rows_published"] == TICKS * MACHINES
    assert final["dataset_ts"] == final["dataset_end"]


async def test_sigterm_stops_the_run_gracefully() -> None:
    """The container's stop signal must be a clean stop, not a kill."""
    settings = runner_settings(loop=True)
    client = FakeMqttClient()
    publisher = ReplayPublisher(
        client,
        settings=settings,
        plant_id="ai4i",
        schedule_factory=schedule_factory(settings),
        time_source=VirtualTimeSource(),
    )
    loop = asyncio.get_running_loop()
    install_signal_handlers(publisher)  # exactly what main() passes as on_start
    try:
        task = asyncio.create_task(publisher.run())
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, timeout=5.0)
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
    assert publisher.stopped is True


# -- production factory and logging ----------------------------------------- #


async def test_the_production_client_factory_builds_an_aiomqtt_client() -> None:
    settings = get_settings()
    factory = aiomqtt_client_factory(settings)
    client = factory("xpm-replay-run_000000000000")
    assert isinstance(client, aiomqtt.Client)
    assert client.identifier == "xpm-replay-run_000000000000"


@pytest.mark.parametrize(
    ("json_logs", "renderer"),
    [(True, structlog.processors.JSONRenderer), (False, structlog.dev.ConsoleRenderer)],
)
def test_configure_logging_honours_the_logging_settings(
    json_logs: bool, renderer: type[object]
) -> None:
    base = get_settings()
    settings = base.model_copy(
        update={"logging": base.logging.model_copy(update={"json_logs": json_logs})}
    )
    try:
        configure_logging(settings)
        processors = structlog.get_config()["processors"]
        assert isinstance(processors[-1], renderer)
        structlog.get_logger("test").info("configured", json_logs=json_logs)
    finally:
        structlog.reset_defaults()
        logging.getLogger().setLevel(logging.WARNING)


def test_the_entrypoint_module_is_a_shim() -> None:
    """``__main__`` must hold no logic of its own (R6, R21)."""
    from xpm.replay import __main__ as entrypoint

    assert entrypoint.main is runner.main


# -- disconnected publishes and the default wiring -------------------------- #


async def test_a_publish_while_disconnected_is_dropped_not_raised() -> None:
    """Telemetry is QoS 0: losing a frame beats taking the process down."""
    # The proxy is module-private on purpose; its drop behaviour is not.
    proxy = runner._ClientProxy()
    await proxy.publish("xpm/ai4i/ai4i-01/telemetry", b"{}", 0, False)
    assert proxy.dropped == 1

    client = FakeMqttClient()
    proxy.bind(client)
    await proxy.publish("xpm/ai4i/ai4i-01/telemetry", b"{}", 0, False)
    assert proxy.dropped == 1
    assert len(client.messages) == 1

    proxy.unbind()
    await proxy.publish("xpm/ai4i/ai4i-01/telemetry", b"{}", 0, False)
    assert proxy.dropped == 2
    assert len(client.messages) == 1


async def test_serve_without_a_schedule_factory_reads_the_committed_parquet() -> None:
    """The default wiring streams the real default plant, not a fixture."""
    settings = runner_settings()
    broker = ScriptedBroker()
    publisher = await serve(
        settings,
        client_factory=broker,
        time_source=VirtualTimeSource(),
        on_start=lambda running: running.stop(),
    )
    assert publisher.plant_id == settings.plants.default
    assert publisher.schedule.rows_total == 10_000
    assert publisher.schedule.machine_count == settings.plants.ai4i.machine_count


def test_main_loads_settings_configures_logging_and_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    served: list[Settings] = []
    configured: list[Settings] = []

    async def fake_serve(settings: Settings, **kwargs: Any) -> None:
        served.append(settings)
        assert kwargs["on_start"] is install_signal_handlers

    monkeypatch.setattr(runner, "serve", fake_serve)
    monkeypatch.setattr(runner, "configure_logging", configured.append)
    runner.main()
    assert len(served) == 1
    assert configured == served
