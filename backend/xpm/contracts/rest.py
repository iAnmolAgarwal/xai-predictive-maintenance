"""REST request and response models (backend.md §3.4, §3.4.1 to §3.4.3).

Series responses are **columnar**, not rows-of-objects, so the frontend never
transposes on a scrub. All lists in one response are guaranteed equal length.

All SHAP quantities here are in **probability space** (R3/ADR-003), and there is
exactly one probability in the system (R16/ADR-016): ``Explanation.probability``,
``Explanation.output_value``, ``Alert.probability`` and ``RiskMessage.probability``
are the same number, and ``base_value + Σ shap + other_contributions_shap``
closes on it to 1e-6.
"""

from __future__ import annotations

from pydantic import Field

from xpm.contracts.common import (
    Alert,
    AlertId,
    AlertSeverity,
    ChannelSpec,
    Direction,
    ExplanationId,
    Framing,
    HealthStatus,
    MachineId,
    MachineStatus,
    ModelId,
    ModelKind,
    Percentile,
    PlantId,
    Probability,
    RunId,
    SchemaVersion,
    ShapSpace,
    UtcDatetime,
    XpmModel,
)
from xpm.contracts.mqtt import ReplayState

__all__ = [
    "Alert",
    "AlertMarker",
    "AlertPage",
    "ChannelSpec",
    "ConfigPatch",
    "ConfigResponse",
    "ConfigValue",
    "Explanation",
    "FeatureDisagreement",
    "GlobalImportance",
    "HealthResponse",
    "ImportanceFeature",
    "ImportancePoint",
    "MachineDetail",
    "MachineSummary",
    "ModelComparison",
    "ModelInfo",
    "Plant",
    "PlantSnapshot",
    "Problem",
    "RiskSeries",
    "SentenceSpan",
    "ShapContribution",
    "TelemetrySeries",
    "WhatIfRequest",
    "WhatIfResponse",
]

#: Every leaf type the flattened settings tree can carry (backend.md §3.4.2).
ConfigValue = float | int | bool | str | list[float] | list[str] | None


class Problem(XpmModel):
    """RFC-9457 ``application/problem+json`` error body (backend.md §3.4)."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


# --------------------------------------------------------------------------- #
# §3.4.1 Plant, channel, machine models
# --------------------------------------------------------------------------- #


class Plant(XpmModel):
    """A selectable plant. ``channels`` is the canonical order (§3.1)."""

    plant_id: PlantId
    display_name: str
    machine_count: int = Field(ge=1)
    available: bool
    """``False`` if ``data/processed/<plant>`` is genuinely missing."""
    unavailable_reason: str | None
    channels: list[ChannelSpec]
    dataset_start: UtcDatetime
    dataset_end: UtcDatetime
    row_interval_seconds: int = Field(ge=1)
    demo_machine_id: MachineId
    """Plant-floor deep-link target for the README GIF (R13)."""


class MachineSummary(XpmModel):
    """A machine tile's payload."""

    machine_id: MachineId
    plant_id: PlantId
    display_name: str
    status: MachineStatus
    probability: Probability | None
    dataset_ts: UtcDatetime | None
    open_alert_id: AlertId | None
    """At most one alert per machine is open at any dataset instant."""
    risk_sparkline: list[Probability | None]
    """Last ``api.sparkline_points`` probabilities, oldest first, right-aligned
    to the current dataset tick. ``None`` entries are ticks the machine was not
    yet scored for (warm-up or offline); the list is never padded with ``0.0``
    and may be shorter than the configured length while warming up."""


class MachineDetail(MachineSummary):
    """The machine detail view's payload."""

    channels: list[ChannelSpec]
    """Identical list and order to ``Plant.channels``."""
    alert_count: int = Field(ge=0)
    variant_mix: dict[str, int] | None
    """AI4I only, e.g. ``{"L": 500, "M": 250, "H": 84}``."""
    bearing: int | None
    """IMS only."""


# --------------------------------------------------------------------------- #
# §3.4.2 Series, alerts, importance, config, models
# --------------------------------------------------------------------------- #


class HealthResponse(XpmModel):
    """``GET /api/health``."""

    status: HealthStatus
    version: str
    model_id: ModelId
    run_id: RunId | None
    """``None`` before the first replay tick."""
    db_ok: bool
    mqtt_connected: bool
    plants_available: list[str]
    replay: ReplayState | None
    """``None`` until the publisher has announced itself."""
    uptime_seconds: float


class TelemetrySeries(XpmModel):
    """``GET /api/telemetry`` — columnar, server-side LTTB downsampled."""

    machine_id: MachineId
    plant_id: PlantId
    dataset_ts: list[UtcDatetime]
    channels: dict[str, list[float | None]]
    """Each list has the same length as ``dataset_ts``; keys in canonical order."""
    n_points: int = Field(ge=0)
    max_points: int = Field(ge=1)
    """Echoed request cap."""
    downsampled: bool


class AlertMarker(XpmModel):
    """An alert glyph on the risk timeline."""

    alert_id: AlertId
    dataset_ts: UtcDatetime
    severity: AlertSeverity
    probability: Probability


class RiskSeries(XpmModel):
    """``GET /api/risk`` — columnar."""

    machine_id: MachineId
    plant_id: PlantId
    model_id: ModelId
    dataset_ts: list[UtcDatetime]
    probability: list[Probability]
    status: list[MachineStatus]
    alerts: list[AlertMarker]
    n_points: int = Field(ge=0)
    downsampled: bool


class AlertPage(XpmModel):
    """``GET /api/alerts`` — the only paging envelope in the API."""

    items: list[Alert]
    next_cursor: str | None
    """Opaque; encodes ``(dataset_ts_ms, alert_id)``."""
    limit: int = Field(ge=1)
    """Echoed page size; the frontend's paging code reads it."""


class ImportancePoint(XpmModel):
    """One beeswarm point: one alert's contribution for one feature."""

    shap: float
    """Probability space."""
    value_percentile: Percentile
    alert_id: AlertId


class ImportanceFeature(XpmModel):
    """One beeswarm row."""

    feature: str
    display_name: str
    mean_abs_shap: float
    points: list[ImportancePoint]


class GlobalImportance(XpmModel):
    """``GET /api/machines/{machine_id}/importance``."""

    machine_id: MachineId
    n_alerts: int = Field(ge=0)
    features: list[ImportanceFeature]
    """Sorted by ``mean_abs_shap`` descending, length <= ``limit``."""


class ConfigResponse(XpmModel):
    """``GET``/``PUT /api/config``."""

    schema_version: SchemaVersion
    run_id: RunId | None
    """The run this config is in force for (R5)."""
    values: dict[str, ConfigValue]
    """The **full flattened settings tree**, keyed by dotted path."""
    mutable_keys: list[str]
    """Exactly the keys ``ConfigPatch`` will accept; the only editability marker."""
    updated_at: UtcDatetime | None
    """``None`` if never patched."""


class ConfigPatch(XpmModel):
    """``PUT /api/config`` body. ``replay.speed`` is not patchable (R12)."""

    values: dict[str, float | int | list[float]]


class ModelInfo(XpmModel):
    """``GET /api/models`` element."""

    model_id: ModelId
    family: ModelKind
    version: str
    plant_id: PlantId
    trained_at: UtcDatetime
    seed: int
    n_features: int = Field(ge=1)
    n_train_rows: int = Field(ge=1)
    is_served: bool
    metrics: dict[str, float]
    """``pr_auc``, ``recall_at_p80``, ``brier``, ``ece``."""
    model_card_path: str


class FeatureDisagreement(XpmModel):
    """One row of the GBM-vs-RF disagreement table."""

    feature: str
    display_name: str
    lgbm_shap: float
    rf_shap: float
    delta: float
    """``lgbm_shap - rf_shap``."""
    lgbm_rank: int | None
    """``None`` if outside that model's ``top_k``."""
    rf_rank: int | None


# --------------------------------------------------------------------------- #
# §3.4.3 SHAP, explanation and what-if models
# --------------------------------------------------------------------------- #


class ShapContribution(XpmModel):
    """One waterfall bar, in probability space (R3)."""

    feature: str
    display_name: str
    shap: float
    """Signed probability-space contribution."""
    value: float | None
    """Raw feature value at alert time; ``None`` = not yet computable."""
    unit: str | None
    """``None`` for dimensionless / derived features."""
    percentile: Percentile | None
    """This value's percentile in the machine's own history."""
    window_hours: int | None
    """``1 | 4 | 24``; ``None`` for a raw channel."""
    stat: str | None
    """``"p95" | "mean" | "slope" | ...``; ``None`` for a raw channel."""
    framing: Framing
    consecutive_hours: float | None
    threshold: float | None
    direction: Direction
    """Drives the up/down glyph and the bar's side."""
    sentence: str
    """The rendered per-feature clause (backend.md §3.9)."""


class SentenceSpan(XpmModel):
    """Character offsets linking a slice of ``sentence`` to a waterfall bar."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    feature: str


class Explanation(XpmModel):
    """``GET /api/alerts/{alert_id}/explanation``. Stored, never recomputed."""

    explanation_id: ExplanationId
    alert_id: AlertId
    machine_id: MachineId
    model_id: ModelId
    model_kind: ModelKind
    shap_space: ShapSpace
    dataset_ts: UtcDatetime
    base_value: Probability
    output_value: Probability
    """Equals ``probability`` by construction."""
    probability: Probability
    contributions: list[ShapContribution]
    """Top ``explanation.top_k`` by ``|shap|`` descending."""
    other_contributions_shap: float
    """Summed tail, so the waterfall closes exactly."""
    other_contributions_count: int = Field(ge=0)
    """Drives the "N other features" roll-up label (R17)."""
    n_features: int = Field(ge=1)
    """Total features in the model vector."""
    sentence: str
    sentence_spans: list[SentenceSpan]
    caveat: str
    """SHAP-is-not-causation line, from config. Required (R13)."""


class ModelComparison(XpmModel):
    """``GET /api/alerts/{alert_id}/compare``."""

    alert_id: AlertId
    lgbm: Explanation
    rf: Explanation
    probability_delta: float
    """``lgbm.probability - rf.probability``."""
    rank_correlation: float
    disagreements: list[FeatureDisagreement]
    commentary: str
    """One backend-generated line; the frontend composes no prose."""


class WhatIfRequest(XpmModel):
    """``POST /api/whatif`` body."""

    alert_id: AlertId
    model: ModelKind = "lgbm"
    overrides: dict[str, float]
    """Feature -> new value; a subset of the ``explanation.top_k_whatif``
    sliders the panel offers."""


class WhatIfResponse(XpmModel):
    """``POST /api/whatif`` response."""

    alert_id: AlertId
    model_id: ModelId
    model_kind: ModelKind
    shap_space: ShapSpace
    baseline_probability: Probability
    """The stored alert's probability."""
    probability: Probability
    base_value: Probability
    output_value: Probability
    """Equals ``probability``."""
    contributions: list[ShapContribution]
    other_contributions_shap: float
    other_contributions_count: int = Field(ge=0)
    n_features: int = Field(ge=1)
    sentence: str
    """Regenerated; ``provisional`` marks it as hypothetical."""
    sentence_spans: list[SentenceSpan]
    provisional: bool = True
    caveat: str
    """The same string as ``Explanation.caveat`` (R13)."""
    gradients: dict[str, float]
    """``∂p/∂x`` per overridable feature, for the client's optimistic
    sub-frame approximation (R7)."""
    compute_ms: float = Field(ge=0.0)
    """Server-side compute only; **not** the definition-of-done number, which
    is the client-side round trip."""


class PlantSnapshot(XpmModel):
    """``GET /api/state_at`` — the exact historical state for scrubbing."""

    plant_id: PlantId
    run_id: RunId
    dataset_ts: UtcDatetime
    """The resolved row boundary; may differ from the requested instant."""
    machines: list[MachineSummary]
    active_alerts: list[Alert]
    active_explanations: list[Explanation]
    """Read from storage, never recomputed."""
