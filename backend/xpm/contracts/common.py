"""Shared identifier, clock and enumeration primitives for every wire shape.

Everything in :mod:`xpm.contracts` derives from this module. It carries no
imports from any other ``xpm`` module so the OpenAPI and WebSocket exporters can
import the contracts in isolation (backend.md §1).

Reference: backend.md §3.1 (identifiers, units, time, channel order),
§3.4.1 (``ChannelSpec``) and §3.4.2 (``Alert``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

__all__ = [
    "ALERT_ID_PATTERN",
    "ALERT_SEVERITIES",
    "DIRECTIONS",
    "EXPLANATION_ID_PATTERN",
    "FRAMINGS",
    "MACHINE_ID_PATTERN",
    "MACHINE_STATUSES",
    "MODEL_ID_PATTERN",
    "MODEL_KINDS",
    "PLANT_IDS",
    "REPLAY_COMMANDS",
    "REQUEST_ID_PATTERN",
    "RUN_ID_PATTERN",
    "SCHEMA_VERSION",
    "Alert",
    "AlertId",
    "AlertSeverity",
    "ChannelSpec",
    "Direction",
    "ExplanationId",
    "Framing",
    "HealthStatus",
    "MachineId",
    "MachineStatus",
    "ModelId",
    "ModelKind",
    "Percentile",
    "PlantId",
    "Probability",
    "ReplayCommandName",
    "ReplaySpeed",
    "RequestId",
    "RunId",
    "SchemaVersion",
    "ShapSpace",
    "UtcDatetime",
    "XpmModel",
]

#: Payload schema version carried by every MQTT message (backend.md §3.3).
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# Closed enumerations (backend.md §3.1)
# --------------------------------------------------------------------------- #

PlantId = Literal["ai4i", "ims"]
PLANT_IDS: tuple[PlantId, ...] = ("ai4i", "ims")

#: A *machine's* live condition. Never conflated with :data:`AlertSeverity`.
MachineStatus = Literal["healthy", "watch", "alert", "offline"]
MACHINE_STATUSES: tuple[MachineStatus, ...] = ("healthy", "watch", "alert", "offline")

#: An *alert's* graded seriousness. Never conflated with :data:`MachineStatus`.
AlertSeverity = Literal["medium", "high", "critical"]
ALERT_SEVERITIES: tuple[AlertSeverity, ...] = ("medium", "high", "critical")

#: The only two model discriminator spellings in the system (backend.md §0).
ModelKind = Literal["lgbm", "rf"]
MODEL_KINDS: tuple[ModelKind, ...] = ("lgbm", "rf")

#: Explanation template family for a feature (backend.md §3.9).
Framing = Literal["percentile", "threshold", "trend", "consecutive"]
FRAMINGS: tuple[Framing, ...] = ("percentile", "threshold", "trend", "consecutive")

Direction = Literal["up", "down"]
DIRECTIONS: tuple[Direction, ...] = ("up", "down")

#: ``GET /api/health`` overall verdict.
HealthStatus = Literal["ok", "degraded"]

#: Closed literal, not a union: every SHAP number in this system is a signed
#: probability contribution (R3/ADR-003).
ShapSpace = Literal["probability"]

ReplayCommandName = Literal["play", "pause", "set_speed", "seek", "restart"]
REPLAY_COMMANDS: tuple[ReplayCommandName, ...] = (
    "play",
    "pause",
    "set_speed",
    "seek",
    "restart",
)

#: Closed literal union, mirrored by ``replay.allowed_speeds`` in
#: ``config/settings.yaml``. Changing either is a contract change: edit both and
#: re-run ``make contracts`` (backend.md §3.3, §3.6).
# PEP 586 does not allow float parameters in ``Literal``, but Pydantic and JSON
# Schema both support them, and the plan pins this exact closed union so the
# generated TypeScript reads ``0.5 | 1 | 5 | 20``. The ignore is the price of
# that contract; a ``float`` here would silently widen the frontend's type.
ReplaySpeed = Literal[0.5, 1.0, 5.0, 20.0]  # type: ignore[valid-type]

# --------------------------------------------------------------------------- #
# Identifier patterns (backend.md §3.1)
# --------------------------------------------------------------------------- #

MACHINE_ID_PATTERN = r"^(ai4i|ims)-\d{2}$"
ALERT_ID_PATTERN = r"^alt_[0-9a-f]{16}$"
EXPLANATION_ID_PATTERN = r"^exp_[0-9a-f]{16}$"
RUN_ID_PATTERN = r"^run_[0-9a-f]{12}$"
REQUEST_ID_PATTERN = r"^req_[0-9a-f]{4}$"
MODEL_ID_PATTERN = r"^(lgbm|rf)@\d+\.\d+\.\d+$"

MachineId = Annotated[str, StringConstraints(pattern=MACHINE_ID_PATTERN)]
AlertId = Annotated[str, StringConstraints(pattern=ALERT_ID_PATTERN)]
ExplanationId = Annotated[str, StringConstraints(pattern=EXPLANATION_ID_PATTERN)]
RunId = Annotated[str, StringConstraints(pattern=RUN_ID_PATTERN)]
RequestId = Annotated[str, StringConstraints(pattern=REQUEST_ID_PATTERN)]
ModelId = Annotated[str, StringConstraints(pattern=MODEL_ID_PATTERN)]

#: Probabilities are floats in ``[0, 1]``, never percentages (backend.md §3.1).
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
#: Percentiles are ``0-100`` floats.
Percentile = Annotated[float, Field(ge=0.0, le=100.0)]
SchemaVersion = Annotated[int, Field(ge=1)]

# --------------------------------------------------------------------------- #
# The two clocks (backend.md §3.1)
# --------------------------------------------------------------------------- #


def _to_utc_millis(value: datetime) -> datetime:
    """Normalise to UTC at millisecond resolution.

    Naive input is read as UTC. Truncating to milliseconds here is what makes
    ``model_validate_json(model_dump_json(x)) == x`` total for every wire model:
    the serialised form carries exactly three fractional digits.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _iso_z(value: datetime) -> str:
    """Render as ``2026-09-14T10:22:31.500Z`` — UTC, milliseconds, ``Z`` suffix."""
    normalised = _to_utc_millis(value)
    return f"{normalised.strftime('%Y-%m-%dT%H:%M:%S')}.{normalised.microsecond // 1000:03d}Z"


#: Both clocks (``ts`` wall-clock, ``dataset_ts`` dataset-time) use this type.
#: The backend never serialises epoch-ms on the wire, including on the hot
#: telemetry path (backend.md §3.1, §3.5).
UtcDatetime = Annotated[
    datetime,
    AfterValidator(_to_utc_millis),
    PlainSerializer(_iso_z, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}, mode="serialization"),
]


# --------------------------------------------------------------------------- #
# Base model
# --------------------------------------------------------------------------- #


class XpmModel(BaseModel):
    """Base for every serialised shape: frozen, and unknown fields are rejected.

    ``protected_namespaces`` is cleared because the contracts legitimately carry
    ``model_id``, ``model_kind`` and ``model_card_path`` fields (backend.md §3.3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())


# --------------------------------------------------------------------------- #
# Shapes shared by more than one transport
# --------------------------------------------------------------------------- #


class ChannelSpec(XpmModel):
    """One sensor channel. The 16 rows live in :mod:`xpm.contracts.channels`."""

    name: str
    display_name: str
    unit: str
    """Rendered verbatim by the frontend; ``""`` for dimensionless, never null."""
    vibration_like: bool
    nominal_min: float
    nominal_max: float


class Alert(XpmModel):
    """An opened alert (backend.md §3.4.2).

    Defined here rather than in :mod:`xpm.contracts.rest` because the MQTT
    ``AlertMessage`` and the WebSocket ``alert`` frame both extend it, and
    ``rest`` imports from ``mqtt``. It is re-exported from both
    :mod:`xpm.contracts.rest` and :mod:`xpm.contracts`.
    """

    alert_id: AlertId
    run_id: RunId
    plant_id: PlantId
    machine_id: MachineId
    machine_display_name: str
    dataset_ts: UtcDatetime
    ts: UtcDatetime
    model_id: ModelId
    probability: Probability
    severity: AlertSeverity
    headline: str
    top_feature: str
    explanation_id: ExplanationId
    closed_dataset_ts: UtcDatetime | None
