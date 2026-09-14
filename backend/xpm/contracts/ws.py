"""WebSocket frame models (backend.md §3.5).

``ws://localhost:8000/ws?plant_id=ai4i``. The query parameter **is** the
complete subscription (R11): there is no ``subscribe`` frame, and transport
control lives entirely on ``POST /api/replay/command``.

Telemetry and risk frames are batched and **positional**: ``values[]`` is indexed
by ``Plant.channels`` order. At 20x with 12 machines the keyed object map MQTT
uses would dominate bandwidth and GC, which is why the two transports diverge
(ADR-025).

Both unions are discriminated on ``type`` and exported to
``contracts/ws-schema.json`` by ``scripts/export_ws_schema.py``.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from xpm.contracts.common import (
    Alert,
    AlertId,
    MachineId,
    MachineStatus,
    ModelId,
    PlantId,
    Probability,
    RunId,
    UtcDatetime,
    XpmModel,
)
from xpm.contracts.mqtt import ReplayState, TopFeature
from xpm.contracts.rest import (
    ConfigResponse,
    Explanation,
    MachineSummary,
    Plant,
)

__all__ = [
    "PROTOCOL_VERSION",
    "AlertFrame",
    "ClientFrame",
    "ConfigFrame",
    "ErrorFrame",
    "ExplanationFrame",
    "HelloFrame",
    "MachineSnapshot",
    "PingFrame",
    "PongFrame",
    "ReplayStateFrame",
    "RiskFrame",
    "RiskUpdate",
    "ServerFrame",
    "SnapshotFrame",
    "TelemetryFrame",
    "TelemetryUpdate",
]

#: Bumped only when the canonical channel order or a frame shape changes.
PROTOCOL_VERSION: Final = 1


# --------------------------------------------------------------------------- #
# Batched frame bodies
# --------------------------------------------------------------------------- #


class TelemetryUpdate(XpmModel):
    """One machine's row inside a batched ``telemetry`` frame."""

    machine_id: MachineId
    dataset_ts: UtcDatetime
    seq: int
    """Publisher row counter — diagnostics only, **never** a resume cursor."""
    values: list[float | None]
    """POSITIONAL, indexed by ``Plant.channels`` order."""


class RiskUpdate(XpmModel):
    """One machine's score inside a batched ``risk`` frame."""

    machine_id: MachineId
    dataset_ts: UtcDatetime
    probability: Probability
    status: MachineStatus
    alert_id: AlertId | None
    model_id: ModelId
    top_features: list[TopFeature]
    """Probability space (R3); length ``explanation.top_k_preview``."""


class MachineSnapshot(MachineSummary):
    """A ``snapshot`` machine entry: the REST summary plus a seed sample."""

    values: list[float | None]
    """Current positional channel values, same order as ``Plant.channels``."""


# --------------------------------------------------------------------------- #
# Server -> client frames
# --------------------------------------------------------------------------- #


class HelloFrame(XpmModel):
    """Always the first frame on every connect (R10)."""

    type: Literal["hello"] = "hello"
    protocol_version: Literal[1] = PROTOCOL_VERSION
    run_id: RunId
    server_time: UtcDatetime
    plant: Plant


class SnapshotFrame(XpmModel):
    """Always the second frame, and re-sent after any ``seek``.

    The dashboard must be fully populated from ``hello`` + ``snapshot`` alone.
    """

    type: Literal["snapshot"] = "snapshot"
    plant_id: PlantId
    run_id: RunId
    dataset_ts: UtcDatetime
    machines: list[MachineSnapshot]
    active_alerts: list[Alert]
    replay_state: ReplayState


class TelemetryFrame(XpmModel):
    """Batched telemetry, coalesced per plant tick and flushed every
    ``api.ws_flush_ms``."""

    type: Literal["telemetry"] = "telemetry"
    plant_id: PlantId
    dataset_ts: UtcDatetime
    ts: UtcDatetime
    updates: list[TelemetryUpdate]


class RiskFrame(XpmModel):
    """Batched risk updates.

    There is deliberately **no** frame-level ``dataset_ts``: each update carries
    its own, and the store's dataset clock is advanced from those.
    """

    type: Literal["risk"] = "risk"
    plant_id: PlantId
    ts: UtcDatetime
    updates: list[RiskUpdate]


class AlertFrame(Alert):
    """The REST ``Alert`` model spread into a frame."""

    type: Literal["alert"] = "alert"


class ExplanationFrame(Explanation):
    """The REST ``Explanation`` spread into a frame, sent immediately after its
    ``alert`` frame and within the same second."""

    type: Literal["explanation"] = "explanation"


class ReplayStateFrame(ReplayState):
    """The retained MQTT ``ReplayState`` broadcast to dashboard clients."""

    type: Literal["replay_state"] = "replay_state"


class ConfigFrame(ConfigResponse):
    """Pushed after a successful ``PUT /api/config``."""

    type: Literal["config"] = "config"


class PingFrame(XpmModel):
    """Server heartbeat, every ``api.ws_ping_seconds``, **regardless of replay
    state**, so a paused replay never looks like a dead socket (R11)."""

    type: Literal["ping"] = "ping"
    ts: UtcDatetime


class ErrorFrame(XpmModel):
    """Protocol or backpressure error."""

    type: Literal["error"] = "error"
    code: str
    message: str
    request_id: str | None


ServerFrame = Annotated[
    HelloFrame
    | SnapshotFrame
    | TelemetryFrame
    | RiskFrame
    | AlertFrame
    | ExplanationFrame
    | ReplayStateFrame
    | ConfigFrame
    | PingFrame
    | ErrorFrame,
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
# Client -> server frames: exactly one
# --------------------------------------------------------------------------- #


class PongFrame(XpmModel):
    """The only message a client may send. Anything else is answered with an
    ``error`` frame, ``code="unsupported_client_message"``, and ignored."""

    type: Literal["pong"] = "pong"
    ts: UtcDatetime


#: The client frame union. It has exactly one member today; it is kept as a
#: named union so the generated TypeScript stays stable if another client frame
#: is ever added.
ClientFrame = PongFrame
