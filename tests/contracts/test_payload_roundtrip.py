"""Round-trip every MQTT, WebSocket and REST model through JSON.

Three things are proved here:

1. ``model_validate_json(model_dump_json(x)) == x`` for one instance of every
   wire model, so nothing silently loses a field or a type on the way out.
2. Both clocks serialise as ISO-8601 UTC strings with milliseconds and a ``Z``
   suffix — never epoch numbers — on every transport, including the hot
   telemetry path (backend.md §3.1, review item 5).
3. The MQTT object-map ``TelemetryMessage`` and the WebSocket positional
   ``TelemetryUpdate`` carry the same channel values for the same source row.
   That divergence is deliberate (ADR-025) and this is its guard.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from xpm.contracts import (
    Ai4iLabels,
    Ai4iMeta,
    Alert,
    AlertFrame,
    AlertMarker,
    AlertMessage,
    AlertPage,
    ChannelSpec,
    ConfigFrame,
    ConfigPatch,
    ConfigResponse,
    ErrorFrame,
    Explanation,
    ExplanationFrame,
    FailureModes,
    FeatureDisagreement,
    GlobalImportance,
    HealthResponse,
    Heartbeat,
    HelloFrame,
    ImportanceFeature,
    ImportancePoint,
    ImsLabels,
    ImsMeta,
    MachineDetail,
    MachineSnapshot,
    MachineSummary,
    ModelComparison,
    ModelInfo,
    PingFrame,
    Plant,
    PlantSnapshot,
    PongFrame,
    Problem,
    ReplayCommand,
    ReplayState,
    ReplayStateFrame,
    RiskFrame,
    RiskMessage,
    RiskSeries,
    RiskUpdate,
    SentenceSpan,
    ShapContribution,
    SnapshotFrame,
    TelemetryFrame,
    TelemetryMessage,
    TelemetrySeries,
    TelemetryUpdate,
    TopFeature,
    WhatIfRequest,
    WhatIfResponse,
)
from xpm.contracts.channels import AI4I_CHANNELS

TS = datetime(2026, 9, 14, 10, 22, 31, 500000, tzinfo=UTC)
DATASET_TS = datetime(2026, 1, 2, 10, 45, 0, tzinfo=UTC)
DATASET_START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
DATASET_END = datetime(2026, 1, 3, 21, 30, 0, tzinfo=UTC)

RUN_ID = "run_1a2b3c4d5e6f"
ALERT_ID = "alt_9f2c71ab40d3e155"
EXPLANATION_ID = "exp_5d4c3b2a1908f7e6"
MODEL_ID = "lgbm@1.0.0"
MACHINE_ID = "ai4i-03"

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

#: One AI4I source row, used by both the MQTT and the WebSocket builder.
SOURCE_ROW: dict[str, float] = {
    "air_temp": 298.9,
    "process_temp": 309.1,
    "temp_diff": 10.2,
    "rot_speed": 1502.0,
    "torque": 42.8,
    "power": 6730.4,
    "tool_wear": 108.0,
}

CAVEAT = (
    "SHAP attributions describe how this model arrived at this score. They are "
    "associations learned from historical data, not proof of physical cause."
)


def _telemetry_message() -> TelemetryMessage:
    return TelemetryMessage(
        run_id=RUN_ID,
        plant_id="ai4i",
        machine_id=MACHINE_ID,
        seq=417,
        ts=TS,
        dataset_ts=DATASET_TS,
        channels=dict(SOURCE_ROW),
        labels=Ai4iLabels(
            machine_failure=0,
            failure_modes=FailureModes(twf=0, hdf=0, pwf=0, osf=0, rnf=0),
        ),
        meta=Ai4iMeta(variant="M", source_row=4823),
    )


def _ims_telemetry_message() -> TelemetryMessage:
    return TelemetryMessage(
        run_id=RUN_ID,
        plant_id="ims",
        machine_id="ims-01",
        seq=12,
        ts=TS,
        dataset_ts=DATASET_TS,
        channels={"vibration_3khz": 0.031, "vibration_rms": 0.21},
        labels=ImsLabels(failure_imminent=0),
        meta=ImsMeta(bearing=1, source_file="2004.02.16.03.20.39"),
    )


def _top_features() -> list[TopFeature]:
    return [
        TopFeature(feature="torque_p95_4h", shap=0.312),
        TopFeature(feature="temp_diff_slope_1h", shap=0.188),
        TopFeature(feature="tool_wear_max_24h", shap=0.121),
    ]


def _risk_message() -> RiskMessage:
    return RiskMessage(
        run_id=RUN_ID,
        plant_id="ai4i",
        machine_id=MACHINE_ID,
        seq=417,
        ts=TS,
        dataset_ts=DATASET_TS,
        model_id=MODEL_ID,
        probability=0.7412,
        status="alert",
        alert_id=ALERT_ID,
        top_features=_top_features(),
    )


def _alert() -> Alert:
    return Alert(
        alert_id=ALERT_ID,
        run_id=RUN_ID,
        plant_id="ai4i",
        machine_id=MACHINE_ID,
        machine_display_name="Mill 03",
        dataset_ts=DATASET_TS,
        ts=TS,
        model_id=MODEL_ID,
        probability=0.7412,
        severity="high",
        headline="Torque stayed above its 95th percentile for 4 consecutive hours.",
        top_feature="torque_p95_4h",
        explanation_id=EXPLANATION_ID,
        closed_dataset_ts=None,
    )


def _contribution() -> ShapContribution:
    return ShapContribution(
        feature="vibration_3khz_p95_4h",
        display_name="Vibration @ 3 kHz — 95th pct over 4 h",
        shap=0.312,
        value=0.031,
        unit="g²/Hz",
        percentile=97.0,
        window_hours=4,
        stat="p95",
        framing="consecutive",
        consecutive_hours=4.0,
        threshold=None,
        direction="up",
        sentence=(
            "Vibration @ 3 kHz stayed above its 95th percentile for 4 "
            "consecutive hours (peaking at 0.031 g²/Hz)"
        ),
    )


def _explanation(kind: str = "lgbm") -> Explanation:
    return Explanation(
        explanation_id=EXPLANATION_ID,
        alert_id=ALERT_ID,
        machine_id=MACHINE_ID,
        model_id=MODEL_ID if kind == "lgbm" else "rf@1.0.0",
        model_kind="lgbm" if kind == "lgbm" else "rf",
        shap_space="probability",
        dataset_ts=DATASET_TS,
        base_value=0.031,
        output_value=0.7412,
        probability=0.7412,
        contributions=[_contribution()],
        other_contributions_shap=0.3982,
        other_contributions_count=146,
        n_features=147,
        sentence="Mill 03 was flagged at 74% risk because Vibration @ 3 kHz stayed high.",
        sentence_spans=[SentenceSpan(start=36, end=54, feature="vibration_3khz_p95_4h")],
        caveat=CAVEAT,
    )


def _machine_summary() -> MachineSummary:
    return MachineSummary(
        machine_id=MACHINE_ID,
        plant_id="ai4i",
        display_name="Mill 03",
        status="alert",
        probability=0.7412,
        dataset_ts=DATASET_TS,
        open_alert_id=ALERT_ID,
        risk_sparkline=[None, 0.12, 0.4, 0.7412],
    )


def _plant() -> Plant:
    return Plant(
        plant_id="ai4i",
        display_name="AI4I 2020 Milling Plant",
        machine_count=12,
        available=True,
        unavailable_reason=None,
        channels=list(AI4I_CHANNELS),
        dataset_start=DATASET_START,
        dataset_end=DATASET_END,
        row_interval_seconds=300,
        demo_machine_id=MACHINE_ID,
    )


def _replay_state() -> ReplayState:
    return ReplayState(
        run_id=RUN_ID,
        plant_id="ai4i",
        seed=42,
        speed=1.0,
        playing=True,
        loop=True,
        loop_index=0,
        dataset_ts=DATASET_TS,
        dataset_start=DATASET_START,
        dataset_end=DATASET_END,
        rows_published=5004,
        rows_total=10000,
        machine_count=12,
        ts=TS,
    )


def _config_response() -> ConfigResponse:
    return ConfigResponse(
        schema_version=1,
        run_id=RUN_ID,
        values={
            "alerting.probability_threshold": 0.6,
            "explanation.top_k": 8,
            "logging.json": True,
            "paths.data_dir": "data",
            "replay.allowed_speeds": [0.5, 1.0, 5.0, 20.0],
            "api.cors_origins": ["http://localhost:5173"],
            "plants.ims.enabled": None,
        },
        mutable_keys=["alerting.probability_threshold", "explanation.top_k"],
        updated_at=TS,
    )


def _telemetry_update() -> TelemetryUpdate:
    return TelemetryUpdate(
        machine_id=MACHINE_ID,
        dataset_ts=DATASET_TS,
        seq=417,
        values=[SOURCE_ROW[channel.name] for channel in AI4I_CHANNELS],
    )


def _machine_snapshot() -> MachineSnapshot:
    return MachineSnapshot(
        **_machine_summary().model_dump(),
        values=[SOURCE_ROW[channel.name] for channel in AI4I_CHANNELS],
    )


def _whatif_response() -> WhatIfResponse:
    return WhatIfResponse(
        alert_id=ALERT_ID,
        model_id=MODEL_ID,
        model_kind="lgbm",
        shap_space="probability",
        baseline_probability=0.7412,
        probability=0.6103,
        base_value=0.031,
        output_value=0.6103,
        contributions=[_contribution()],
        other_contributions_shap=0.2673,
        other_contributions_count=146,
        n_features=147,
        sentence="Mill 03 would be flagged at 61% risk.",
        sentence_spans=[SentenceSpan(start=0, end=7, feature="vibration_3khz_p95_4h")],
        provisional=True,
        caveat=CAVEAT,
        gradients={"vibration_3khz_p95_4h": -1.4},
        compute_ms=11.2,
    )


MODELS: tuple[BaseModel, ...] = (
    # MQTT (§3.3)
    _telemetry_message(),
    _ims_telemetry_message(),
    _risk_message(),
    AlertMessage(**_alert().model_dump()),
    ReplayCommand(command="set_speed", speed=5.0, dataset_ts=None, request_id="req_7c1f"),
    ReplayCommand(command="seek", dataset_ts=DATASET_TS, request_id="req_0a0b"),
    ReplayCommand(command="restart", request_id="req_00ff", seed=7, plant_id="ims"),
    _replay_state(),
    Heartbeat(service="api", ts=TS, healthy=True),
    # REST (§3.4)
    Problem(
        type="https://xpm.local/errors/not-found",
        title="Alert not found",
        status=404,
        detail="alt_deadbeefdeadbeef",
        instance="/api/alerts/alt_deadbeefdeadbeef",
    ),
    HealthResponse(
        status="ok",
        version="1.0.0",
        model_id=MODEL_ID,
        run_id=RUN_ID,
        db_ok=True,
        mqtt_connected=True,
        plants_available=["ai4i", "ims"],
        replay=_replay_state(),
        uptime_seconds=12.5,
    ),
    HealthResponse(
        status="degraded",
        version="1.0.0",
        model_id=MODEL_ID,
        run_id=None,
        db_ok=True,
        mqtt_connected=False,
        plants_available=["ai4i"],
        replay=None,
        uptime_seconds=0.5,
    ),
    _plant(),
    ChannelSpec(
        name="torque",
        display_name="Torque",
        unit="N·m",
        vibration_like=False,
        nominal_min=0.0,
        nominal_max=80.0,
    ),
    _machine_summary(),
    MachineDetail(
        **_machine_summary().model_dump(),
        channels=list(AI4I_CHANNELS),
        alert_count=3,
        variant_mix={"L": 500, "M": 250, "H": 84},
        bearing=None,
    ),
    TelemetrySeries(
        machine_id=MACHINE_ID,
        plant_id="ai4i",
        dataset_ts=[DATASET_TS],
        channels={name: [value] for name, value in SOURCE_ROW.items()},
        n_points=1,
        max_points=2000,
        downsampled=False,
    ),
    RiskSeries(
        machine_id=MACHINE_ID,
        plant_id="ai4i",
        model_id=MODEL_ID,
        dataset_ts=[DATASET_TS],
        probability=[0.7412],
        status=["alert"],
        alerts=[
            AlertMarker(
                alert_id=ALERT_ID,
                dataset_ts=DATASET_TS,
                severity="high",
                probability=0.7412,
            )
        ],
        n_points=1,
        downsampled=False,
    ),
    _alert(),
    AlertPage(items=[_alert()], next_cursor=None, limit=50),
    GlobalImportance(
        machine_id=MACHINE_ID,
        n_alerts=2,
        features=[
            ImportanceFeature(
                feature="torque_p95_4h",
                display_name="Torque — 95th pct over 4 h",
                mean_abs_shap=0.21,
                points=[ImportancePoint(shap=0.31, value_percentile=97.0, alert_id=ALERT_ID)],
            )
        ],
    ),
    _config_response(),
    ConfigPatch(values={"alerting.probability_threshold": 0.7, "explanation.top_k": 6}),
    ModelInfo(
        model_id=MODEL_ID,
        family="lgbm",
        version="1.0.0",
        plant_id="ai4i",
        trained_at=TS,
        seed=42,
        n_features=147,
        n_train_rows=7832,
        is_served=True,
        metrics={"pr_auc": 0.81, "recall_at_p80": 0.62, "brier": 0.04, "ece": 0.02},
        model_card_path="models/registry/lgbm/1.0.0/model_card.md",
    ),
    _contribution(),
    SentenceSpan(start=0, end=4, feature="torque_p95_4h"),
    _explanation(),
    ModelComparison(
        alert_id=ALERT_ID,
        lgbm=_explanation("lgbm"),
        rf=_explanation("rf"),
        probability_delta=0.08,
        rank_correlation=0.74,
        disagreements=[
            FeatureDisagreement(
                feature="torque_p95_4h",
                display_name="Torque — 95th pct over 4 h",
                lgbm_shap=0.31,
                rf_shap=0.18,
                delta=0.13,
                lgbm_rank=1,
                rf_rank=None,
            )
        ],
        commentary="LightGBM leans on torque where the forest leans on tool wear.",
    ),
    WhatIfRequest(alert_id=ALERT_ID, model="lgbm", overrides={"torque_p95_4h": 55.0}),
    _whatif_response(),
    PlantSnapshot(
        plant_id="ai4i",
        run_id=RUN_ID,
        dataset_ts=DATASET_TS,
        machines=[_machine_summary()],
        active_alerts=[_alert()],
        active_explanations=[_explanation()],
    ),
    # WebSocket (§3.5)
    HelloFrame(run_id=RUN_ID, server_time=TS, plant=_plant()),
    SnapshotFrame(
        plant_id="ai4i",
        run_id=RUN_ID,
        dataset_ts=DATASET_TS,
        machines=[_machine_snapshot()],
        active_alerts=[_alert()],
        replay_state=_replay_state(),
    ),
    TelemetryFrame(plant_id="ai4i", dataset_ts=DATASET_TS, ts=TS, updates=[_telemetry_update()]),
    RiskFrame(
        plant_id="ai4i",
        ts=TS,
        updates=[
            RiskUpdate(
                machine_id=MACHINE_ID,
                dataset_ts=DATASET_TS,
                probability=0.7412,
                status="alert",
                alert_id=ALERT_ID,
                model_id=MODEL_ID,
                top_features=_top_features(),
            )
        ],
    ),
    AlertFrame(**_alert().model_dump()),
    ExplanationFrame(**_explanation().model_dump()),
    ReplayStateFrame(**_replay_state().model_dump()),
    ConfigFrame(**_config_response().model_dump()),
    PingFrame(ts=TS),
    ErrorFrame(code="backpressure_dropped", message="dropped 12 frames", request_id=None),
    PongFrame(ts=TS),
    _telemetry_update(),
    _machine_snapshot(),
    TopFeature(feature="torque_p95_4h", shap=0.312),
)


def _ident(model: BaseModel) -> str:
    return type(model).__name__


@pytest.mark.parametrize("instance", MODELS, ids=_ident)
def test_json_round_trip(instance: BaseModel) -> None:
    restored = type(instance).model_validate_json(instance.model_dump_json())
    assert restored == instance


@pytest.mark.parametrize("instance", MODELS, ids=_ident)
def test_unknown_fields_are_rejected(instance: BaseModel) -> None:
    """Every wire model is ``extra="forbid"``."""
    payload: dict[str, Any] = instance.model_dump(mode="json", by_alias=True)
    payload["definitely_not_a_field"] = 1
    with pytest.raises(ValidationError):
        type(instance).model_validate(payload)


@pytest.mark.parametrize("instance", MODELS, ids=_ident)
def test_clocks_are_iso_strings(instance: BaseModel) -> None:
    """``ts`` and ``dataset_ts`` are ISO-8601 UTC strings, never epoch numbers."""
    payload = instance.model_dump(mode="json")
    for field in ("ts", "dataset_ts", "server_time", "dataset_start", "dataset_end"):
        value = payload.get(field)
        if value is None:
            continue
        # The columnar series models carry a list of instants under `dataset_ts`.
        stamps = value if isinstance(value, list) else [value]
        for stamp in stamps:
            assert isinstance(stamp, str), f"{_ident(instance)}.{field} is not a string"
            assert ISO_Z.match(stamp), f"{_ident(instance)}.{field} = {stamp!r}"


def test_frozen_models_reject_mutation() -> None:
    alert = _alert()
    with pytest.raises(ValidationError):
        alert.probability = 0.1  # type: ignore[misc]


def test_mqtt_object_map_and_ws_positional_agree() -> None:
    """The deliberate MQTT/WebSocket divergence carries identical values.

    MQTT is self-describing for Node-RED; the WebSocket is positional against
    ``Plant.channels`` for bandwidth. Same source row, same numbers (ADR-025).
    """
    message = _telemetry_message()
    update = _telemetry_update()
    assert len(update.values) == len(AI4I_CHANNELS)
    positional = {
        channel.name: value for channel, value in zip(AI4I_CHANNELS, update.values, strict=True)
    }
    assert positional == message.channels
    assert message.dataset_ts == update.dataset_ts
    assert message.seq == update.seq


def test_naive_datetimes_are_read_as_utc_and_truncated_to_milliseconds() -> None:
    frame = PingFrame(ts=datetime(2026, 9, 14, 10, 22, 31, 500999))
    assert frame.ts == datetime(2026, 9, 14, 10, 22, 31, 500000, tzinfo=UTC)
    assert frame.model_dump(mode="json")["ts"] == "2026-09-14T10:22:31.500Z"


def test_identifier_patterns_are_enforced() -> None:
    for bad in ("alt_nothexnothexno", "alt_9f2c71ab40d3e15", "9f2c71ab40d3e155"):
        with pytest.raises(ValidationError):
            AlertMarker(alert_id=bad, dataset_ts=DATASET_TS, severity="high", probability=0.5)
    with pytest.raises(ValidationError):
        MachineSummary.model_validate(
            {**_machine_summary().model_dump(mode="json"), "machine_id": "ai4i-3"}
        )


def test_probability_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        AlertMarker(alert_id=ALERT_ID, dataset_ts=DATASET_TS, severity="high", probability=1.5)


def test_replay_command_speed_is_a_closed_union() -> None:
    with pytest.raises(ValidationError):
        ReplayCommand(command="set_speed", speed=2.0, request_id="req_7c1f")  # type: ignore[arg-type]


def test_status_and_severity_are_different_enums() -> None:
    """A machine status is never an alert severity (review item 3)."""
    with pytest.raises(ValidationError):
        AlertMarker(
            alert_id=ALERT_ID,
            dataset_ts=DATASET_TS,
            severity="watch",  # type: ignore[arg-type]
            probability=0.5,
        )
    with pytest.raises(ValidationError):
        MachineSummary.model_validate(
            {**_machine_summary().model_dump(mode="json"), "status": "critical"}
        )


def test_every_model_instance_is_covered() -> None:
    """Guards against a model being added to the contracts but not exercised."""
    exercised = {type(model).__name__ for model in MODELS}
    missing = {
        "TelemetryMessage",
        "RiskMessage",
        "AlertMessage",
        "ReplayCommand",
        "ReplayState",
        "Heartbeat",
        "HelloFrame",
        "SnapshotFrame",
        "TelemetryFrame",
        "RiskFrame",
        "AlertFrame",
        "ExplanationFrame",
        "ReplayStateFrame",
        "ConfigFrame",
        "PingFrame",
        "ErrorFrame",
        "PongFrame",
        "Explanation",
        "WhatIfResponse",
        "PlantSnapshot",
    } - exercised
    assert not missing
