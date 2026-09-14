"""The deterministic MQTT replay publisher (backend.md §3.3).

One tick publishes one ``TelemetryMessage`` per machine of the selected plant on
``xpm/{plant}/{machine_id}/telemetry`` at QoS 0 without retain, and the run's
``ReplayState`` is kept on the retained control topic
``xpm/control/replay/state`` at QoS 1 so a late subscriber — the dashboard, a
Node-RED flow, an ``mosquitto_sub`` session — learns the transport state without
waiting for the next change.

Determinism (R5): ``run_id``, ``seq``, ``dataset_ts`` and the payloads are pure
functions of ``(seed, plant_id, loop_index, dataset)``. Speed is deliberately
absent from every one of them, so a run at 20x emits byte-identical messages to
a run at 1x apart from the wall-clock ``ts``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import blake2b
from typing import Final, Protocol, runtime_checkable

import structlog

from xpm.config import Settings, get_settings
from xpm.contracts.common import ReplaySpeed
from xpm.contracts.mqtt import ReplayState, TelemetryMessage
from xpm.data.schema import PlantId
from xpm.replay.clock import RealTimeSource, ReplayClock, TimeSource
from xpm.replay.mapping import ReplaySchedule, ScheduledRow, build_schedule

__all__ = [
    "MqttPublisherClient",
    "ReplayPublisher",
    "ScheduleFactory",
    "control_cmd_topic",
    "control_state_topic",
    "run_id_for",
    "telemetry_topic",
]

_log = structlog.get_logger(__name__)

#: QoS/retain per the topic table in backend.md §3.3.
TELEMETRY_QOS: Final[int] = 0
TELEMETRY_RETAIN: Final[bool] = False
STATE_QOS: Final[int] = 1
STATE_RETAIN: Final[bool] = True
COMMAND_QOS: Final[int] = 1


@runtime_checkable
class MqttPublisherClient(Protocol):
    """The slice of :class:`aiomqtt.Client` the publisher needs."""

    async def publish(
        self,
        topic: str,
        payload: bytes | None = None,
        qos: int = 0,
        retain: bool = False,
    ) -> None: ...


#: Builds the schedule for a plant and seed; injectable so tests stay off disk.
ScheduleFactory = Callable[[PlantId, int], ReplaySchedule]


def telemetry_topic(topic_root: str, plant_id: str, machine: str) -> str:
    """``xpm/{plant}/{machine_id}/telemetry``."""
    return f"{topic_root}/{plant_id}/{machine}/telemetry"


def control_state_topic(topic_root: str) -> str:
    """``xpm/control/replay/state`` — retained."""
    return f"{topic_root}/control/replay/state"


def control_cmd_topic(topic_root: str) -> str:
    """``xpm/control/replay/cmd`` — the API is the only writer."""
    return f"{topic_root}/control/replay/cmd"


def run_id_for(seed: int, plant_id: str, loop_index: int, dataset_start: datetime) -> str:
    """``run_`` + 12 hex of ``blake2b(seed|plant|loop_index|dataset_start_ms)``.

    Speed is deliberately not an input, so a run id is identical at 0.5x and
    20x (backend.md §3.1, R5). ``loop_index`` is, so every loop mints a new one
    (R12).
    """
    dataset_start_ms = int(dataset_start.timestamp() * 1000)
    material = f"{seed}|{plant_id}|{loop_index}|{dataset_start_ms}"
    return "run_" + blake2b(material.encode("utf-8"), digest_size=6).hexdigest()


class ReplayPublisher:
    """Streams one plant's rows over MQTT and owns the replay's live state.

    The publisher is single-task: :meth:`run` drives the tick loop, and the
    control listener calls the command methods from the same event loop, so
    there is no lock and no shared mutable state outside this instance.
    """

    def __init__(
        self,
        client: MqttPublisherClient,
        *,
        settings: Settings | None = None,
        plant_id: PlantId | None = None,
        seed: int | None = None,
        schedule_factory: ScheduleFactory | None = None,
        time_source: TimeSource | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        state_heartbeat_seconds: float | None = None,
    ) -> None:
        self._client = client
        self._settings = settings if settings is not None else get_settings()
        self._time: TimeSource = time_source if time_source is not None else RealTimeSource()
        self._wall_clock = wall_clock if wall_clock is not None else _utc_now
        self._factory: ScheduleFactory = (
            schedule_factory
            if schedule_factory is not None
            else _default_schedule_factory(self._settings)
        )
        # The server heartbeat cadence is the one interval in settings that
        # describes "how often a client is told the system is still alive"
        # (api.ws_ping_seconds, R11); the retained ReplayState refresh reuses it
        # rather than inventing a second knob.
        self._heartbeat_seconds = (
            state_heartbeat_seconds
            if state_heartbeat_seconds is not None
            else float(self._settings.api.ws_ping_seconds)
        )
        self._plant_id: PlantId = (
            plant_id if plant_id is not None else self._settings.plants.default
        )
        self._seed = seed if seed is not None else self._settings.replay.seed
        self._loop = self._settings.replay.loop
        self._loop_index = 0
        self._rows_published = 0
        self._stopped = asyncio.Event()
        self._resumed = asyncio.Event()
        self._schedule = self._factory(self._plant_id, self._seed)
        self._clock = self._new_clock(playing=self._settings.replay.autostart)
        self._run_id = self._mint_run_id()
        self._last_state_at = self._time.monotonic()
        if self._clock.playing:
            self._resumed.set()

    # -- read-only view ---------------------------------------------------- #

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def plant_id(self) -> PlantId:
        return self._plant_id

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def loop_index(self) -> int:
        return self._loop_index

    @property
    def playing(self) -> bool:
        return self._clock.playing

    @property
    def speed(self) -> float:
        return self._clock.speed

    @property
    def schedule(self) -> ReplaySchedule:
        return self._schedule

    @property
    def clock(self) -> ReplayClock:
        return self._clock

    @property
    def rows_published(self) -> int:
        return self._rows_published

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def state(self) -> ReplayState:
        """The current :class:`ReplayState`, as published on the control topic."""
        return ReplayState(
            run_id=self._run_id,
            plant_id=self._plant_id,
            seed=self._seed,
            speed=_as_speed(self._clock.speed),
            playing=self._clock.playing,
            loop=self._loop,
            loop_index=self._loop_index,
            dataset_ts=self._clock.dataset_ts,
            dataset_start=self._schedule.dataset_start,
            dataset_end=self._schedule.dataset_end,
            rows_published=self._rows_published,
            rows_total=self._schedule.rows_total,
            machine_count=self._schedule.machine_count,
            ts=self._wall_clock(),
        )

    # -- lifecycle --------------------------------------------------------- #

    async def run(self) -> None:
        """Publish until the dataset is exhausted (``loop=false``) or stopped."""
        await self.publish_state()
        _log.info(
            "replay.started",
            run_id=self._run_id,
            plant_id=self._plant_id,
            seed=self._seed,
            speed=self._clock.speed,
            playing=self._clock.playing,
            rows_total=self._schedule.rows_total,
        )
        while not self._stopped.is_set():
            if not self._clock.playing:
                # No heartbeat while paused: the paused ReplayState is already
                # retained on the broker, so a periodic re-publish would repeat
                # a message every subscriber has and change nothing.
                await self._resumed.wait()
                continue
            await self._time.sleep(self._clock.wait_seconds())
            if not self._should_publish():
                continue
            await self._publish_tick()
            self._clock.advance()
            if self._clock.exhausted:
                await self._on_exhausted()
            await self._maybe_heartbeat()
        _log.info("replay.stopped", run_id=self._run_id, rows_published=self._rows_published)

    def _should_publish(self) -> bool:
        """Whether the tick that just came due may still be published.

        A ``pause`` or ``stop`` can land while the loop is sleeping out the
        tick interval, and it must win over the tick that was already due.
        """
        return self._clock.playing and not self._stopped.is_set()

    def stop(self) -> None:
        """Ask :meth:`run` to return at the next opportunity."""
        self._stopped.set()
        self._resumed.set()

    # -- commands (backend.md §3.3) ---------------------------------------- #

    async def play(self) -> None:
        """Resume publishing; idempotent."""
        if self._clock.exhausted:
            # A finished non-looping run restarts rather than refusing to play.
            self._clock.reset()
            self._rows_published = 0
        changed = self._clock.play()
        self._resumed.set()
        _log.info("replay.play", run_id=self._run_id, changed=changed)
        await self.publish_state()

    async def pause(self) -> None:
        """Stop publishing without losing the cursor; idempotent."""
        changed = self._clock.pause()
        self._resumed.clear()
        _log.info("replay.pause", run_id=self._run_id, changed=changed)
        await self.publish_state()

    async def set_speed(self, speed: float) -> None:
        """Re-pace the run. Dataset time, ``seq`` and ``run_id`` are unaffected."""
        allowed = [float(value) for value in self._settings.replay.allowed_speeds]
        if speed not in allowed:
            raise ValueError(f"speed {speed!r} is not one of {allowed}")
        changed = self._clock.set_speed(speed)
        _log.info("replay.set_speed", run_id=self._run_id, speed=speed, changed=changed)
        await self.publish_state()

    async def seek(self, dataset_ts: datetime) -> None:
        """Jump the dataset cursor and re-emit the state."""
        tick = self._clock.seek(dataset_ts)
        self._rows_published = sum(len(group) for group in self._schedule.ticks[:tick])
        _log.info(
            "replay.seek",
            run_id=self._run_id,
            tick=tick,
            dataset_ts=self._clock.dataset_ts.isoformat(),
        )
        await self.publish_state()

    async def restart(self, *, seed: int | None = None, plant_id: PlantId | None = None) -> None:
        """Start a fresh run — optionally on another seed or plant (§3.3).

        A plant switch is a restart with ``plant_id``: the schedule, machine
        set, dataset bounds and ``run_id`` all change together.
        """
        if plant_id is not None and plant_id != self._plant_id:
            self._plant_id = plant_id
        if seed is not None:
            self._seed = seed
        speed = self._clock.speed
        self._schedule = self._factory(self._plant_id, self._seed)
        self._loop_index += 1
        self._rows_published = 0
        self._clock = self._new_clock(playing=True)
        # A restart re-paces nothing: the operator's chosen speed survives it.
        self._clock.set_speed(speed)
        self._run_id = self._mint_run_id()
        self._resumed.set()
        _log.info(
            "replay.restart",
            run_id=self._run_id,
            plant_id=self._plant_id,
            seed=self._seed,
            loop_index=self._loop_index,
        )
        await self.publish_state()

    # -- publishing -------------------------------------------------------- #

    async def publish_state(self) -> None:
        """Publish the retained ``ReplayState`` and reset the heartbeat timer."""
        state = self.state()
        await self._client.publish(
            control_state_topic(self._settings.mqtt.topic_root),
            state.model_dump_json().encode("utf-8"),
            STATE_QOS,
            STATE_RETAIN,
        )
        self._last_state_at = self._time.monotonic()

    async def _publish_tick(self) -> None:
        """Publish every machine's row for the current tick, in schedule order."""
        tick = self._clock.tick
        rows = self._schedule.ticks[tick]
        batch = self._settings.replay.publish_batch
        for position, row in enumerate(rows):
            # Yield to the event loop every `publish_batch` machines so a
            # control command never waits for a whole wide tick to drain.
            if position and position % batch == 0:
                await self._time.sleep(0.0)
            await self._client.publish(
                telemetry_topic(self._settings.mqtt.topic_root, self._plant_id, row.machine_id),
                self._telemetry(row, tick).model_dump_json().encode("utf-8"),
                TELEMETRY_QOS,
                TELEMETRY_RETAIN,
            )
        self._rows_published += len(rows)

    def _telemetry(self, row: ScheduledRow, tick: int) -> TelemetryMessage:
        """Shape one scheduled row into its wire message.

        ``seq`` is the tick index within the run: it is the same number for
        every machine of a tick, it restarts at 0 on every new ``run_id``, and
        it satisfies ``dataset_ts == dataset_start + seq * row_interval``.
        """
        return TelemetryMessage(
            run_id=self._run_id,
            plant_id=self._plant_id,
            machine_id=row.machine_id,
            seq=tick,
            ts=self._wall_clock(),
            dataset_ts=row.dataset_ts,
            channels=dict(row.channels),
            labels=row.labels,
            meta=row.meta,
        )

    async def _maybe_heartbeat(self) -> None:
        """Refresh the retained state if the heartbeat interval has elapsed."""
        if self._time.monotonic() - self._last_state_at >= self._heartbeat_seconds:
            await self.publish_state()

    async def _on_exhausted(self) -> None:
        """Loop into a new run (R12) or stop after a final paused state."""
        if not self._loop:
            self._clock.pause()
            self._resumed.clear()
            _log.info(
                "replay.exhausted",
                run_id=self._run_id,
                loop=False,
                rows_published=self._rows_published,
            )
            await self.publish_state()
            self.stop()
            return
        self._loop_index += 1
        self._rows_published = 0
        self._clock.reset()
        self._run_id = self._mint_run_id()
        _log.info(
            "replay.looped",
            run_id=self._run_id,
            loop_index=self._loop_index,
            plant_id=self._plant_id,
        )
        await self.publish_state()

    # -- internals --------------------------------------------------------- #

    def _new_clock(self, *, playing: bool) -> ReplayClock:
        return ReplayClock(
            dataset_start=self._schedule.dataset_start,
            row_interval=self._schedule.row_interval,
            base_rate_hz=self._settings.replay.base_rate_hz,
            speed=float(self._settings.replay.speed),
            tick_count=self._schedule.tick_count,
            time_source=self._time,
            playing=playing,
        )

    def _mint_run_id(self) -> str:
        return run_id_for(
            self._seed, self._plant_id, self._loop_index, self._schedule.dataset_start
        )


def _default_schedule_factory(settings: Settings) -> ScheduleFactory:
    """Bind :func:`xpm.replay.mapping.build_schedule` to these settings."""

    def factory(plant_id: PlantId, seed: int) -> ReplaySchedule:
        return build_schedule(plant_id, settings=settings, seed=seed)

    return factory


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_speed(value: float) -> ReplaySpeed:
    """Narrow a validated speed to the contract's closed literal union.

    The caller has already checked ``value`` against ``replay.allowed_speeds``,
    which ``tests/contracts/test_settings.py`` pins to exactly the members of
    :data:`~xpm.contracts.common.ReplaySpeed`.
    """
    speed: ReplaySpeed = value
    return speed
