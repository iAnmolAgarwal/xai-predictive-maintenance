"""``python -m xpm.replay`` — the replay container's entrypoint.

Reads the settings tree (``config/settings.yaml`` plus ``XPM_*`` overrides),
connects to the broker, and runs two cooperating tasks on one event loop: the
publisher's tick loop and the control-topic listener. ``SIGTERM`` and
``SIGINT`` stop the run, flush a final retained ``ReplayState`` and exit 0, so
``docker compose down`` is a clean shutdown rather than a kill.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import AsyncIterator

import aiomqtt
import structlog

from xpm.config import Settings, get_settings
from xpm.replay.control import RawPayload, ReplayControl
from xpm.replay.publisher import (
    COMMAND_QOS,
    ReplayPublisher,
    control_cmd_topic,
)

__all__ = ["configure_logging", "main", "serve"]


def configure_logging(settings: Settings) -> None:
    """Structured logging, JSON in containers and human-readable otherwise."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.logging.level)
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
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.logging.level]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def serve(settings: Settings) -> None:
    """Connect, publish and listen until a signal or dataset exhaustion."""
    log = structlog.get_logger("xpm.replay")
    loop = asyncio.get_running_loop()
    identifier_seed = settings.replay.seed
    async with aiomqtt.Client(
        hostname=settings.mqtt.host,
        port=settings.mqtt.port,
        keepalive=settings.mqtt.keepalive_seconds,
        identifier=f"xpm-replay-{identifier_seed}",
    ) as client:
        publisher = ReplayPublisher(client, settings=settings)
        control = ReplayControl(publisher)
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, publisher.stop)
        await client.subscribe(control_cmd_topic(settings.mqtt.topic_root), qos=COMMAND_QOS)
        log.info(
            "replay.connected",
            host=settings.mqtt.host,
            port=settings.mqtt.port,
            run_id=publisher.run_id,
        )
        listener = asyncio.create_task(control.listen(_payloads(client)))
        try:
            await publisher.run()
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await publisher.publish_state()
            log.info("replay.shutdown", run_id=publisher.run_id)


async def _payloads(client: aiomqtt.Client) -> AsyncIterator[RawPayload]:
    """The control topic's payloads, stripped of their MQTT envelope."""
    async for message in client.messages:
        yield message.payload


def main() -> None:
    """Entrypoint: load settings, configure logging, run the event loop."""
    settings = get_settings()
    configure_logging(settings)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
