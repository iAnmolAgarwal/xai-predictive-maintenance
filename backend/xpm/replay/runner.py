"""Process wiring for the replay container: connect, serve, reconnect, stop.

This module is everything ``python -m xpm.replay`` does, kept out of
``__main__.py`` so it is coverage-measured rather than omit-listed (R6, R21).

**Reconnect is the publisher's own job** (R21). A broker blip raises
``aiomqtt.MqttError``; the runner catches it, backs off exponentially between
``mqtt.reconnect_min_seconds`` and ``mqtt.reconnect_max_seconds``, and
reconnects with the *same* publisher, so the run keeps its ``run_id``, its
dataset cursor and its ``seq``. The container restart policy is a backstop, not
the mechanism: ``docker-compose.e2e.yml`` turns it off.

**The client identifier is ``xpm-replay-{run_id}``** using the run id minted at
connect time, i.e. ``loop_index`` 0 (§3.3, R21). Later loops and restarts keep
the connection and therefore the identifier; the current run id is always
readable from the retained ``ReplayState``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, final, runtime_checkable

import aiomqtt
import structlog

from xpm.config import Settings, get_settings
from xpm.contracts.settings import ReplaySettings
from xpm.data.schema import PlantId
from xpm.replay.clock import RealTimeSource, TimeSource
from xpm.replay.control import RawPayload, ReplayControl
from xpm.replay.mapping import ReplaySchedule, build_schedule
from xpm.replay.publisher import (
    COMMAND_QOS,
    ReplayPublisher,
    ScheduleFactory,
    control_cmd_topic,
    run_id_for,
)

__all__ = [
    "ClientFactory",
    "MqttConnection",
    "aiomqtt_client_factory",
    "client_identifier",
    "configure_logging",
    "initial_run_id",
    "install_signal_handlers",
    "main",
    "serve",
]

_log = structlog.get_logger(__name__)


@runtime_checkable
class MqttConnection(Protocol):
    """The slice of :class:`aiomqtt.Client` the runner drives."""

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None: ...

    async def subscribe(self, topic: str, qos: int = 0) -> Any: ...

    @property
    def messages(self) -> AsyncIterator[Any]: ...


#: Opens one broker connection under a given client identifier.
ClientFactory = Callable[[str], AbstractAsyncContextManager[MqttConnection]]


def client_identifier(run_id: str) -> str:
    """``xpm-replay-{run_id}`` (backend.md §3.3, R21)."""
    return f"xpm-replay-{run_id}"


def initial_run_id(plant_id: PlantId, seed: int, schedule: ReplaySchedule) -> str:
    """The ``loop_index`` 0 run id, minted before the connection is opened."""
    return run_id_for(seed, plant_id, 0, schedule.dataset_start)


@final
class _ClientProxy:
    """Publishes through whichever broker connection is currently live.

    The publisher is built once and outlives any individual connection, so it
    talks to this proxy instead of a client. While disconnected a publish is
    dropped rather than raising: telemetry is QoS 0 and inherently lossy (§3.3),
    so losing frames during an outage beats taking the process down.

    A dropped ``ReplayState`` is not lost for good: :meth:`bind` publishes
    nothing itself, but :meth:`ReplayPublisher.run` re-publishes the retained
    state as its first act on every re-entry, which is what closes the window
    for a subscriber that reconnected during the outage.

    The first drop after each :meth:`unbind` is logged at warning level, so an
    operator sees the loss when it happens rather than in the shutdown footer.
    """

    def __init__(self) -> None:
        self._client: MqttConnection | None = None
        self._warned = False
        self.dropped = 0

    def bind(self, client: MqttConnection) -> None:
        self._client = client
        self._warned = False

    def unbind(self) -> None:
        self._client = None

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        if self._client is None:
            self.dropped += 1
            if not self._warned:
                self._warned = True
                _log.warning("replay.publish_dropped", topic=topic, qos=qos, retain=retain)
            return
        await self._client.publish(topic, payload, qos, retain)


def aiomqtt_client_factory(settings: Settings) -> ClientFactory:
    """The production :data:`ClientFactory`, bound to ``mqtt.*`` settings."""

    def factory(identifier: str) -> AbstractAsyncContextManager[MqttConnection]:
        client: AbstractAsyncContextManager[MqttConnection] = aiomqtt.Client(
            hostname=settings.mqtt.host,
            port=settings.mqtt.port,
            keepalive=settings.mqtt.keepalive_seconds,
            identifier=identifier,
        )
        return client

    return factory


async def serve(
    settings: Settings,
    *,
    client_factory: ClientFactory | None = None,
    schedule_factory: ScheduleFactory | None = None,
    time_source: TimeSource | None = None,
    on_start: Callable[[ReplayPublisher], None] | None = None,
) -> ReplayPublisher:
    """Run the replay until it stops, reconnecting across broker failures.

    ``on_start`` is handed the publisher once it exists and before the first
    connection attempt; :func:`main` uses it to install the signal handlers, so
    a ``SIGTERM`` arriving during a reconnect backoff still ends the process.
    Returns the publisher, so the caller can inspect the run that finished.
    """
    factory: ScheduleFactory = schedule_factory or _default_schedule_factory(settings)
    clock_source: TimeSource = time_source or RealTimeSource()
    plant_id: PlantId = settings.plants.default
    replay: ReplaySettings = settings.replay
    schedule = factory(plant_id, replay.seed)
    identifier = client_identifier(initial_run_id(plant_id, replay.seed, schedule))

    proxy = _ClientProxy()
    publisher = ReplayPublisher(
        proxy,
        settings=settings,
        plant_id=plant_id,
        seed=replay.seed,
        schedule_factory=factory,
        time_source=clock_source,
    )
    control = ReplayControl(publisher)
    if on_start is not None:
        on_start(publisher)

    connect = client_factory or aiomqtt_client_factory(settings)
    delay = settings.mqtt.reconnect_min_seconds
    while not _stopped(publisher):
        try:
            async with connect(identifier) as client:
                proxy.bind(client)
                # Wall time spent refusing and backing off is not tick debt: the
                # tick loop was not running, so re-anchor its deadline on now.
                # Dataset time and `seq` are untouched (R5).
                publisher.clock.rebase()
                delay = settings.mqtt.reconnect_min_seconds
                await client.subscribe(control_cmd_topic(settings.mqtt.topic_root), COMMAND_QOS)
                _log.info(
                    "replay.connected",
                    host=settings.mqtt.host,
                    port=settings.mqtt.port,
                    identifier=identifier,
                    run_id=publisher.run_id,
                )
                listener = asyncio.create_task(control.listen(_payloads(client)))
                try:
                    await publisher.run()
                finally:
                    listener.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await listener
                # A clean stop deserves a truthful final retained state.
                with contextlib.suppress(aiomqtt.MqttError, OSError):
                    await publisher.publish_state()
        except (aiomqtt.MqttError, OSError) as error:
            if _stopped(publisher):
                break
            _log.warning(
                "replay.disconnected",
                error=str(error),
                retry_in_seconds=delay,
                run_id=publisher.run_id,
            )
            await clock_source.sleep(delay)
            delay = min(delay * 2.0, settings.mqtt.reconnect_max_seconds)
        finally:
            proxy.unbind()
    _log.info(
        "replay.shutdown",
        run_id=publisher.run_id,
        rows_published=publisher.rows_published,
        dropped_publishes=proxy.dropped,
    )
    return publisher


def _stopped(publisher: ReplayPublisher) -> bool:
    """Whether the run has been asked to end.

    A named call rather than an inline ``publisher.stopped``: the reconnect loop
    asks the question in two places with opposite consequences (keep looping /
    stop retrying), and naming it keeps both readable.
    """
    return publisher.stopped


def install_signal_handlers(publisher: ReplayPublisher) -> None:
    """Turn ``SIGTERM``/``SIGINT`` into a graceful stop rather than a kill."""
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, publisher.stop)


async def _payloads(client: MqttConnection) -> AsyncIterator[RawPayload]:
    """The control topic's payloads, stripped of their MQTT envelope."""
    async for message in client.messages:
        payload: RawPayload = message.payload
        yield payload


def _default_schedule_factory(settings: Settings) -> ScheduleFactory:
    def factory(plant_id: PlantId, seed: int) -> ReplaySchedule:
        return build_schedule(plant_id, settings=settings, seed=seed)

    return factory


def configure_logging(settings: Settings) -> None:
    """Structured logging: JSON in containers, human-readable otherwise."""
    level = logging.getLevelNamesMapping()[settings.logging.level]
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.logging.json_logs
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """Entrypoint: load settings, configure logging, run the event loop."""
    settings = get_settings()
    configure_logging(settings)
    asyncio.run(serve(settings, on_start=install_signal_handlers))
