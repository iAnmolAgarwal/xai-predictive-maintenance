"""The settings schema, mirroring ``config/settings.yaml`` (backend.md §3.6).

Sources, highest priority first: explicit init kwargs, ``XPM_``-prefixed
environment variables with ``__`` as the nested delimiter
(``XPM_ALERTING__PROBABILITY_THRESHOLD=0.7``), then the YAML file. Sources are
deep-merged, so an env override replaces one leaf and leaves its siblings alone.

The YAML file is located by ``XPM_CONFIG_FILE`` if set, else by walking up from
this module to the first directory containing ``config/settings.yaml``.

Every threshold, percentile, window, top-k and speed multiplier in the system
resolves through this model; no business module contains a numeric literal a
user could plausibly want to change.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from xpm.contracts.common import (
    MachineId,
    ModelKind,
    Percentile,
    Probability,
    ReplaySpeed,
    SchemaVersion,
    UtcDatetime,
)

__all__ = [
    "CONFIG_FILE_ENV",
    "DEFAULT_CONFIG_RELPATH",
    "ENV_NESTED_DELIMITER",
    "ENV_PREFIX",
    "MUTABLE_CONFIG_KEYS",
    "Ai4iPlantSettings",
    "AlertingSettings",
    "ApiSettings",
    "EvaluationSettings",
    "ExplanationSettings",
    "FeaturesSettings",
    "ImsPlantSettings",
    "LgbmSettings",
    "LoggingSettings",
    "ModelSettings",
    "MqttSettings",
    "PathsSettings",
    "PlantsSettings",
    "RandomForestSettings",
    "ReplaySettings",
    "Settings",
    "SettingsSection",
    "SeverityBands",
    "ShapSettings",
    "SpeedSetting",
    "default_settings_file",
]

ENV_PREFIX = "XPM_"
ENV_NESTED_DELIMITER = "__"
CONFIG_FILE_ENV = "XPM_CONFIG_FILE"
DEFAULT_CONFIG_RELPATH = Path("config") / "settings.yaml"

#: The only dotted keys ``PUT /api/config`` accepts (backend.md §3.4.2).
#: ``replay.speed`` is deliberately absent: speed changes go through
#: ``POST /api/replay/command`` and nowhere else (R12).
MUTABLE_CONFIG_KEYS: tuple[str, ...] = (
    "alerting.probability_threshold",
    "alerting.watch_threshold",
    "alerting.consecutive_rows_to_open",
    "alerting.consecutive_rows_to_close",
    "alerting.cooldown_minutes",
    "alerting.severity_bands.medium",
    "alerting.severity_bands.high",
    "alerting.severity_bands.critical",
    "explanation.top_k",
    "features.percentile_levels",
)


def _as_float(value: Any) -> Any:
    """Coerce an environment string or an int to a float.

    ``XPM_REPLAY__SPEED=5`` arrives as the string ``"5"``; the speed literal is
    a closed union of floats, which would otherwise reject it.
    """
    if isinstance(value, str | int) and not isinstance(value, bool):
        try:
            return float(value)
        except ValueError:
            return value
    return value


#: ``replay.speed`` / ``replay.allowed_speeds`` leaf: the wire literal, with
#: environment strings coerced to floats first.
SpeedSetting = Annotated[ReplaySpeed, BeforeValidator(_as_float)]


def default_settings_file() -> Path:
    """Locate ``config/settings.yaml``.

    ``XPM_CONFIG_FILE`` wins if set; otherwise walk up from this module until a
    directory holds ``config/settings.yaml``. The relative path is returned as a
    last resort so the error message names something recognisable.
    """
    override = os.environ.get(CONFIG_FILE_ENV)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / DEFAULT_CONFIG_RELPATH
        if candidate.is_file():
            return candidate
    return DEFAULT_CONFIG_RELPATH


class SettingsSection(BaseModel):
    """Base for every settings sub-tree: frozen, unknown keys rejected."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", protected_namespaces=(), populate_by_name=True
    )


class PathsSettings(SettingsSection):
    """Filesystem layout. Resolved to absolute paths by :mod:`xpm.config`."""

    data_dir: Path
    db_path: Path
    models_dir: Path
    reports_dir: Path


class MqttSettings(SettingsSection):
    """Broker connection (backend.md §3.3)."""

    host: str
    port: int = Field(ge=1, le=65535)
    keepalive_seconds: int = Field(ge=1)
    topic_root: str
    reconnect_min_seconds: float = Field(gt=0.0)
    reconnect_max_seconds: float = Field(gt=0.0)


class Ai4iPlantSettings(SettingsSection):
    """AI4I 2020: 10 000 rows dealt round-robin into 12 machines (§3.2.1)."""

    enabled: bool
    machine_count: int = Field(ge=1)
    row_interval_seconds: int = Field(ge=1)
    dataset_start: UtcDatetime
    demo_machine_id: MachineId


class ImsPlantSettings(SettingsSection):
    """NASA IMS test set 2: 4 bearings, 984 files (§3.2.2, §3.2.3)."""

    enabled: bool
    test_set: int = Field(ge=1)
    machine_count: int = Field(ge=1)
    row_interval_seconds: int = Field(ge=1)
    sample_rate_hz: int = Field(ge=1)
    samples_per_file: int = Field(ge=1)
    label_horizon_hours: int = Field(ge=1)
    welch_nperseg: int = Field(ge=1)
    welch_overlap: float = Field(ge=0.0, lt=1.0)
    demo_machine_id: MachineId
    source_url: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bytes: int = Field(ge=1)


class PlantsSettings(SettingsSection):
    """The two selectable plants."""

    default: Literal["ai4i", "ims"]
    ai4i: Ai4iPlantSettings
    ims: ImsPlantSettings


class FeaturesSettings(SettingsSection):
    """The rolling-window engine (backend.md §1, §3.9)."""

    windows_hours: list[int]
    stats: list[str]
    ewma_halflife_hours: float = Field(gt=0.0)
    slope_unit: str
    slope_relative_when_mean_nonzero: bool
    slope_zero_eps: float = Field(gt=0.0)
    min_window_coverage: float = Field(ge=0.0, le=1.0)
    percentile_levels: list[Percentile]
    percentile_warmup_samples: int = Field(ge=1)
    percentile_algorithm: str
    percentile_compression: int = Field(ge=1)
    streak_percentile: Percentile
    streak_min_hours: float = Field(ge=0.0)


class ShapSettings(SettingsSection):
    """TreeExplainer configuration (R3/ADR-003)."""

    background_rows: int = Field(ge=1)
    background_seed: int
    feature_perturbation: Literal["interventional"]
    model_output: Literal["probability"]


class LgbmSettings(SettingsSection):
    """LightGBM hyperparameters."""

    n_estimators: int = Field(ge=1)
    learning_rate: float = Field(gt=0.0)
    num_leaves: int = Field(ge=2)
    min_child_samples: int = Field(ge=1)
    subsample: float = Field(gt=0.0, le=1.0)
    colsample_bytree: float = Field(gt=0.0, le=1.0)
    class_weight: str


class RandomForestSettings(SettingsSection):
    """RandomForest hyperparameters (the comparison model)."""

    n_estimators: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    min_samples_leaf: int = Field(ge=1)
    class_weight: str


class EvaluationSettings(SettingsSection):
    """Evaluation reporting only; nothing here is in the serving path (R16)."""

    target_precision: float = Field(gt=0.0, le=1.0)
    calibration_bins: int = Field(ge=2)


class ModelSettings(SettingsSection):
    """Training and serving.

    There is deliberately **no** ``calibration`` key: no post-hoc calibrator
    exists in this system, class imbalance is handled by ``class_weight`` /
    ``scale_pos_weight`` inside the fit (R16, ADR-016).
    """

    served: ModelKind
    seed: int
    test_size: float = Field(gt=0.0, lt=1.0)
    split: str
    shap: ShapSettings
    lgbm: LgbmSettings
    rf: RandomForestSettings
    evaluation: EvaluationSettings


class SeverityBands(SettingsSection):
    """Lower bound -> severity (backend.md §3.3)."""

    medium: Probability
    high: Probability
    critical: Probability


class AlertingSettings(SettingsSection):
    """Alert opening, closing and grading."""

    probability_threshold: Probability
    watch_threshold: Probability
    consecutive_rows_to_open: int = Field(ge=1)
    consecutive_rows_to_close: int = Field(ge=1)
    cooldown_minutes: int = Field(ge=0)
    severity_bands: SeverityBands


class ExplanationSettings(SettingsSection):
    """Waterfall budget, sentence budget and the required caveat (R13)."""

    top_k: int = Field(ge=1)
    top_k_preview: int = Field(ge=1)
    top_k_whatif: int = Field(ge=1)
    max_sentence_features: int = Field(ge=1)
    min_abs_shap: float = Field(ge=0.0)
    caveat: str


class ReplaySettings(SettingsSection):
    """The deterministic MQTT publisher."""

    seed: int
    base_rate_hz: float = Field(gt=0.0)
    speed: SpeedSetting
    allowed_speeds: list[SpeedSetting]
    """Mirrored by ``ReplayCommand.speed``; changing it is a contract change."""
    autostart: bool
    loop: bool
    publish_batch: int = Field(ge=1)


class ApiSettings(SettingsSection):
    """FastAPI, WebSocket hub and series budgets."""

    host: str
    port: int = Field(ge=1, le=65535)
    cors_origins: list[str]
    ws_flush_ms: int = Field(ge=1)
    ws_queue_max: int = Field(ge=1)
    ws_ping_seconds: int = Field(ge=1)
    offline_after_seconds: int = Field(ge=1)
    sparkline_points: int = Field(ge=1)
    max_series_points: int = Field(ge=1)
    history_retention_rows: int = Field(ge=1)


class LoggingSettings(SettingsSection):
    """Structured logging."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    json_logs: bool = Field(alias="json")
    """Serialised as ``logging.json``; ``json`` shadows a ``BaseModel``
    attribute, so the field is named ``json_logs`` and aliased."""


class Settings(BaseSettings):
    """The whole ``config/settings.yaml`` tree, frozen."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
        populate_by_name=True,
        case_sensitive=False,
    )

    schema_version: SchemaVersion
    paths: PathsSettings
    mqtt: MqttSettings
    plants: PlantsSettings
    features: FeaturesSettings
    model: ModelSettings
    alerting: AlertingSettings
    explanation: ExplanationSettings
    replay: ReplaySettings
    api: ApiSettings
    logging: LoggingSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Init kwargs beat ``XPM_*`` env vars, which beat the YAML file."""
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=default_settings_file()),
        )
