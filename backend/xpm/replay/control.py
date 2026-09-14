"""The replay control listener: ``xpm/control/replay/cmd`` -> publisher state.

The API is the only writer of that topic (backend.md §3.3); Node-RED is a
read-only consumer. Every command is validated against
:class:`~xpm.contracts.mqtt.ReplayCommand` before it reaches the publisher, and
a command that fails validation — malformed JSON, an unknown verb, an
out-of-enum speed, a ``seek`` with no ``dataset_ts`` — is logged with its
``request_id`` and dropped. **A bad command never propagates an exception into
the publisher's tick loop**: an unauthenticated broker topic is not allowed to
take the stream down.

The acknowledgement is the retained ``ReplayState`` the publisher emits after
applying a command. ``ReplayState`` carries no ``request_id`` field in the
frozen contract, so the correlation id is logged rather than echoed on the wire;
the API correlates by observing the state transition it asked for.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from datetime import datetime

import structlog
from pydantic import ValidationError

from xpm.contracts.mqtt import ReplayCommand
from xpm.data.schema import PlantId
from xpm.replay.publisher import ReplayPublisher

__all__ = ["ReplayCommandError", "ReplayControl"]

_log = structlog.get_logger(__name__)

#: Payload types an MQTT client may hand over for one retained/QoS-1 message.
type RawPayload = bytes | bytearray | str | None


class ReplayCommandError(ValueError):
    """A syntactically valid command that is not applicable as written."""


class ReplayControl:
    """Decodes commands from the control topic and applies them."""

    def __init__(self, publisher: ReplayPublisher) -> None:
        self._publisher = publisher

    @property
    def publisher(self) -> ReplayPublisher:
        return self._publisher

    async def listen(self, payloads: AsyncIterable[RawPayload]) -> None:
        """Consume the control topic until the stream ends or the run stops."""
        async for payload in payloads:
            await self.handle(payload)
            if self._publisher.stopped:
                break

    async def handle(self, payload: RawPayload) -> bool:
        """Decode, validate and apply one payload. ``True`` if it was applied.

        Never raises: this is the boundary between an open MQTT topic and the
        publisher's state machine.
        """
        command = self.decode(payload)
        if command is None:
            return False
        try:
            await self.apply(command)
        except (ReplayCommandError, ValueError) as error:
            _log.warning(
                "replay.command_rejected",
                request_id=command.request_id,
                command=command.command,
                reason=str(error),
            )
            return False
        return True

    def decode(self, payload: RawPayload) -> ReplayCommand | None:
        """Parse a payload into a :class:`ReplayCommand`, or ``None`` if invalid."""
        if payload is None:
            _log.warning("replay.command_rejected", reason="empty payload")
            return None
        raw = (
            payload.decode("utf-8", errors="replace")
            if isinstance(payload, bytes | bytearray)
            else payload
        )
        try:
            return ReplayCommand.model_validate_json(raw)
        except ValidationError as error:
            _log.warning(
                "replay.command_rejected",
                reason="does not validate against ReplayCommand",
                errors=error.error_count(),
                payload=raw[:200],
            )
            return None

    async def apply(self, command: ReplayCommand) -> None:
        """Apply a validated command to the publisher.

        Raises :class:`ReplayCommandError` when the verb's required companion
        field is missing; :meth:`handle` turns that into a log line.
        """
        match command.command:
            case "play":
                await self._publisher.play()
            case "pause":
                await self._publisher.pause()
            case "set_speed":
                await self._publisher.set_speed(_require_speed(command))
            case "seek":
                await self._publisher.seek(_require_dataset_ts(command))
            case "restart":
                await self._publisher.restart(seed=command.seed, plant_id=_plant_id(command))
        _log.info(
            "replay.command_applied",
            request_id=command.request_id,
            command=command.command,
            run_id=self._publisher.run_id,
        )


def _require_speed(command: ReplayCommand) -> float:
    if command.speed is None:
        raise ReplayCommandError("set_speed requires a speed")
    return float(command.speed)


def _require_dataset_ts(command: ReplayCommand) -> datetime:
    if command.dataset_ts is None:
        raise ReplayCommandError("seek requires a dataset_ts")
    return command.dataset_ts


def _plant_id(command: ReplayCommand) -> PlantId | None:
    """``restart``'s optional plant switch, narrowed to the dataset-side enum."""
    if command.plant_id is None:
        return None
    return command.plant_id
