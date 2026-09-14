"""The deterministic MQTT replay publisher (backend.md §1, §3.3).

Streams the committed processed dataset of one plant over MQTT as if it were a
live plant floor: one ``TelemetryMessage`` per machine per tick, a retained
``ReplayState`` describing the run, and a control topic that plays, pauses,
seeks, re-paces or restarts it.

Runs as its own container, entered via ``python -m xpm.replay``.
"""

from __future__ import annotations

from xpm.replay.clock import RealTimeSource, ReplayClock, TimeSource
from xpm.replay.control import ReplayCommandError, ReplayControl
from xpm.replay.mapping import (
    ReplaySchedule,
    ScheduledRow,
    build_schedule,
    expected_machine_id,
    plant_row_interval,
)
from xpm.replay.publisher import (
    MqttPublisherClient,
    ReplayPublisher,
    control_cmd_topic,
    control_state_topic,
    run_id_for,
    telemetry_topic,
)

__all__ = [
    "MqttPublisherClient",
    "RealTimeSource",
    "ReplayClock",
    "ReplayCommandError",
    "ReplayControl",
    "ReplayPublisher",
    "ReplaySchedule",
    "ScheduledRow",
    "TimeSource",
    "build_schedule",
    "control_cmd_topic",
    "control_state_topic",
    "expected_machine_id",
    "plant_row_interval",
    "run_id_for",
    "telemetry_topic",
]
