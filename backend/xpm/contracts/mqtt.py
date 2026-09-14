"""MQTT payload models (backend.md §3.3).

MQTT payloads are *per machine, self-describing and object-mapped* so that a
Node-RED debug node, an ``mosquitto_sub`` session and a lab-report screenshot
are all readable without a channel-order lookup table. The WebSocket telemetry
and risk frames are batched and positional instead; that divergence is a
decision (ADR-025), not drift, and both shapes are generated from this package.
"""

from __future__ import annotations

from pydantic import Field

from xpm.contracts.common import (
    SCHEMA_VERSION,
    Alert,
    AlertId,
    MachineId,
    MachineStatus,
    ModelId,
    PlantId,
    Probability,
    ReplayCommandName,
    ReplaySpeed,
    RequestId,
    RunId,
    SchemaVersion,
    UtcDatetime,
    XpmModel,
)

__all__ = [
    "Ai4iLabels",
    "Ai4iMeta",
    "AlertMessage",
    "FailureModes",
    "Heartbeat",
    "ImsLabels",
    "ImsMeta",
    "ReplayCommand",
    "ReplayState",
    "RiskMessage",
    "TelemetryMessage",
    "TopFeature",
]


class FailureModes(XpmModel):
    """AI4I's five native failure-mode flags, 0/1."""

    twf: int
    hdf: int
    pwf: int
    osf: int
    rnf: int


class Ai4iLabels(XpmModel):
    """Labels travelling with an AI4I row."""

    machine_failure: int
    failure_modes: FailureModes


class ImsLabels(XpmModel):
    """Labels travelling with an IMS window; ``failure_modes`` does not exist."""

    failure_imminent: int


class Ai4iMeta(XpmModel):
    """Provenance of an AI4I row."""

    variant: str
    source_row: int


class ImsMeta(XpmModel):
    """Provenance of an IMS window."""

    bearing: int
    source_file: str


class TelemetryMessage(XpmModel):
    """``xpm/{plant}/{machine_id}/telemetry`` — QoS 0, not retained."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: RunId
    plant_id: PlantId
    machine_id: MachineId
    seq: int
    ts: UtcDatetime
    dataset_ts: UtcDatetime
    channels: dict[str, float | None]
    """Keyed by ``ChannelSpec.name`` in canonical order for the plant."""
    labels: Ai4iLabels | ImsLabels
    meta: Ai4iMeta | ImsMeta


class TopFeature(XpmModel):
    """A preview contribution, in probability space (R3)."""

    feature: str
    shap: float


class RiskMessage(XpmModel):
    """``xpm/{plant}/{machine_id}/risk`` — QoS 0, not retained."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: RunId
    plant_id: PlantId
    machine_id: MachineId
    seq: int
    ts: UtcDatetime
    dataset_ts: UtcDatetime
    model_id: ModelId
    probability: Probability
    status: MachineStatus
    alert_id: AlertId | None
    """``None`` unless ``status == "alert"``."""
    top_features: list[TopFeature]
    """Length ``explanation.top_k_preview``; probability space (R3)."""


class AlertMessage(Alert):
    """``xpm/{plant}/{machine_id}/alert`` — QoS 1, not retained.

    Field-for-field the REST :class:`~xpm.contracts.common.Alert` plus
    ``schema_version``.
    """

    schema_version: SchemaVersion = SCHEMA_VERSION


class ReplayCommand(XpmModel):
    """``xpm/control/replay/cmd`` — QoS 1. The API is the only writer.

    ``speed`` is a **closed literal union** deliberately: the generated
    TypeScript must read ``0.5 | 1 | 5 | 20 | null`` so the frontend derives
    ``type Speed = NonNullable<ReplayCommand["speed"]>`` from the contract.
    It is pinned to ``replay.allowed_speeds`` by
    ``tests/contracts/test_settings.py``; changing one without the other fails.
    """

    schema_version: SchemaVersion = SCHEMA_VERSION
    command: ReplayCommandName
    speed: ReplaySpeed | None = None
    """Required iff ``command == "set_speed"``."""
    dataset_ts: UtcDatetime | None = None
    """Required iff ``command == "seek"``."""
    request_id: RequestId
    """``"req_" + 4 hex``; echoed in any resulting error frame."""
    seed: int | None = None
    """``restart`` only."""
    plant_id: PlantId | None = None
    """``restart`` only."""


class ReplayState(XpmModel):
    """``xpm/control/replay/state`` — QoS 1, **retained**.

    A late subscriber therefore gets the transport state immediately.
    """

    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: RunId
    plant_id: PlantId
    seed: int
    speed: ReplaySpeed
    playing: bool
    loop: bool
    loop_index: int = Field(ge=0)
    dataset_ts: UtcDatetime
    dataset_start: UtcDatetime
    dataset_end: UtcDatetime
    rows_published: int = Field(ge=0)
    rows_total: int = Field(ge=0)
    machine_count: int = Field(ge=1)
    ts: UtcDatetime


class Heartbeat(XpmModel):
    """``xpm/system/heartbeat`` — QoS 0, not retained."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    service: str
    ts: UtcDatetime
    healthy: bool
