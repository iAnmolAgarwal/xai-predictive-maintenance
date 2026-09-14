"""Every default in ``config/settings.yaml`` loads, type-checks and is pinned.

Two assertions here are load-bearing for other tasks (backend.md §4):

* the literal set of ``ReplayCommand.speed`` equals ``replay.allowed_speeds``,
  so the closed union the frontend derives its ``Speed`` type from can never
  drift from the config list;
* flattening the loaded tree yields a superset of the guaranteed-present key
  table of §3.4.2, and ``mutable_keys`` is a subset of those keys.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from xpm.config import (
    data_dir,
    db_path,
    flatten_settings,
    get_settings,
    models_dir,
    project_root,
    reload_settings,
    reports_dir,
    resolve_path,
    settings_file,
)
from xpm.contracts import settings as settings_module
from xpm.contracts.mqtt import ReplayCommand
from xpm.contracts.settings import (
    CONFIG_FILE_ENV,
    MUTABLE_CONFIG_KEYS,
    Settings,
    default_settings_file,
)

#: The keys backend.md §3.4.2 guarantees on every ``ConfigResponse``, because
#: the frontend reads each of them at runtime rather than hard-coding it.
GUARANTEED_KEYS: tuple[tuple[str, object], ...] = (
    ("explanation.top_k", 8),
    ("explanation.top_k_whatif", 5),
    ("explanation.top_k_preview", 3),
    ("alerting.severity_bands.medium", 0.60),
    ("alerting.severity_bands.high", 0.75),
    ("alerting.severity_bands.critical", 0.90),
    ("alerting.probability_threshold", 0.60),
    ("alerting.watch_threshold", 0.35),
    ("replay.allowed_speeds", [0.5, 1.0, 5.0, 20.0]),
    ("api.sparkline_points", 60),
    ("api.ws_ping_seconds", 10),
    ("api.ws_flush_ms", 100),
    ("api.max_series_points", 2000),
    ("api.offline_after_seconds", 30),
)


@pytest.fixture
def pristine_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Drop every ``XPM_`` override (``tests/conftest.py`` sets one) and the cache."""
    for name in list(os.environ):
        if name.startswith("XPM_"):
            monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def defaults(pristine_env: None) -> Settings:
    """The shipped defaults, with no environment influence."""
    return get_settings()


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #


def test_settings_file_is_the_committed_yaml(pristine_env: None) -> None:
    located = settings_file()
    assert located.is_file()
    assert located.name == "settings.yaml"
    assert located.parent.name == "config"
    assert located == default_settings_file()


def test_paths_defaults(defaults: Settings) -> None:
    assert defaults.schema_version == 1
    assert defaults.paths.data_dir == Path("data")
    assert defaults.paths.db_path == Path("data/xpm.db")
    assert defaults.paths.models_dir == Path("models/registry")
    assert defaults.paths.reports_dir == Path("reports")


def test_mqtt_defaults(defaults: Settings) -> None:
    assert defaults.mqtt.host == "mosquitto"
    assert defaults.mqtt.port == 1883
    assert defaults.mqtt.keepalive_seconds == 30
    assert defaults.mqtt.topic_root == "xpm"
    assert defaults.mqtt.reconnect_min_seconds == 1.0
    assert defaults.mqtt.reconnect_max_seconds == 30.0


def test_plant_defaults(defaults: Settings) -> None:
    assert defaults.plants.default == "ai4i"
    ai4i = defaults.plants.ai4i
    assert ai4i.enabled is True
    assert ai4i.machine_count == 12
    assert ai4i.row_interval_seconds == 300
    assert ai4i.dataset_start.isoformat() == "2026-01-01T00:00:00+00:00"
    assert ai4i.demo_machine_id == "ai4i-03"
    ims = defaults.plants.ims
    assert ims.enabled is True
    assert ims.test_set == 2
    assert ims.machine_count == 4
    assert ims.row_interval_seconds == 600
    assert ims.sample_rate_hz == 20000
    assert ims.samples_per_file == 20480
    assert ims.label_horizon_hours == 24
    assert ims.welch_nperseg == 4096
    assert ims.welch_overlap == 0.5
    assert ims.demo_machine_id == "ims-01"
    assert ims.source_bytes == 1075597174
    assert ims.source_sha256 == "21001ac266c465f5d345ec42d7b508c6a6328487fd9d4d7774422dd5ea10ad83"
    assert ims.source_url.endswith("4.+Bearings.zip")


def test_demo_machine_ids_are_present_for_every_plant(defaults: Settings) -> None:
    """R13: the plant floor deep-links these, so they are not optional."""
    assert defaults.plants.ai4i.demo_machine_id.startswith("ai4i-")
    assert defaults.plants.ims.demo_machine_id.startswith("ims-")


def test_feature_defaults(defaults: Settings) -> None:
    features = defaults.features
    assert features.windows_hours == [1, 4, 24]
    assert features.stats == ["mean", "std", "min", "max", "p95", "slope", "ewma"]
    assert features.ewma_halflife_hours == 1.0
    assert features.slope_unit == "per_hour"
    assert features.slope_relative_when_mean_nonzero is True
    assert features.slope_zero_eps == 1.0e-12
    assert features.min_window_coverage == 0.6
    assert features.percentile_levels == [50, 75, 90, 95, 99]
    assert features.percentile_warmup_samples == 48
    assert features.percentile_algorithm == "tdigest"
    assert features.percentile_compression == 200
    assert features.streak_percentile == 95
    assert features.streak_min_hours == 1.0


def test_model_defaults(defaults: Settings) -> None:
    model = defaults.model
    assert model.served == "lgbm"
    assert model.seed == 42
    assert model.test_size == 0.2
    assert model.split == "grouped_time"
    assert model.shap.background_rows == 256
    assert model.shap.background_seed == 1337
    assert model.shap.feature_perturbation == "interventional"
    assert model.shap.model_output == "probability"
    assert model.lgbm.n_estimators == 400
    assert model.lgbm.learning_rate == 0.05
    assert model.lgbm.num_leaves == 31
    assert model.lgbm.min_child_samples == 20
    assert model.lgbm.subsample == 0.9
    assert model.lgbm.colsample_bytree == 0.8
    assert model.lgbm.class_weight == "balanced"
    assert model.rf.n_estimators == 500
    assert model.rf.max_depth == 12
    assert model.rf.min_samples_leaf == 5
    assert model.rf.class_weight == "balanced_subsample"
    assert model.evaluation.target_precision == 0.80
    assert model.evaluation.calibration_bins == 10


def test_there_is_no_calibration_key(defaults: Settings) -> None:
    """R16/ADR-016: no post-hoc calibrator exists anywhere in this system."""
    assert not hasattr(defaults.model, "calibration")
    assert not any("calibration." in key for key in flatten_settings(defaults))
    raw = yaml.safe_load(settings_file().read_text(encoding="utf-8"))
    assert "calibration" not in raw["model"]


def test_alerting_defaults(defaults: Settings) -> None:
    alerting = defaults.alerting
    assert alerting.probability_threshold == 0.60
    assert alerting.watch_threshold == 0.35
    assert alerting.consecutive_rows_to_open == 2
    assert alerting.consecutive_rows_to_close == 3
    assert alerting.cooldown_minutes == 60
    assert alerting.severity_bands.medium == 0.60
    assert alerting.severity_bands.high == 0.75
    assert alerting.severity_bands.critical == 0.90
    assert alerting.watch_threshold < alerting.probability_threshold


def test_explanation_defaults(defaults: Settings) -> None:
    explanation = defaults.explanation
    assert explanation.top_k == 8
    assert explanation.top_k_preview == 3
    assert explanation.top_k_whatif == 5
    assert explanation.max_sentence_features == 2
    assert explanation.min_abs_shap == 0.001
    assert explanation.caveat.startswith("SHAP attributions describe")
    assert "not proof of physical cause" in explanation.caveat


def test_replay_defaults(defaults: Settings) -> None:
    replay = defaults.replay
    assert replay.seed == 42
    assert replay.base_rate_hz == 2.0
    assert replay.speed == 1.0
    assert replay.allowed_speeds == [0.5, 1.0, 5.0, 20.0]
    assert replay.autostart is True
    assert replay.loop is True
    assert replay.publish_batch == 12


def test_api_defaults(defaults: Settings) -> None:
    api = defaults.api
    assert api.host == "0.0.0.0"
    assert api.port == 8000
    assert api.cors_origins == ["http://localhost:5173", "http://localhost:4173"]
    assert api.ws_flush_ms == 100
    assert api.ws_queue_max == 512
    assert api.ws_ping_seconds == 10
    assert api.offline_after_seconds == 30
    assert api.sparkline_points == 60
    assert api.max_series_points == 2000
    assert api.history_retention_rows == 500000


def test_logging_defaults(defaults: Settings) -> None:
    assert defaults.logging.level == "INFO"
    assert defaults.logging.json_logs is True
    assert flatten_settings(defaults)["logging.json"] is True


def test_settings_are_frozen(defaults: Settings) -> None:
    with pytest.raises(ValidationError):
        defaults.alerting.probability_threshold = 0.9  # type: ignore[misc]


def test_example_file_carries_the_same_defaults(pristine_env: None) -> None:
    """``settings.example.yaml`` documents alternatives, not different values."""
    example = settings_file().parent / "settings.example.yaml"
    assert example.is_file()
    loaded = Settings(**yaml.safe_load(example.read_text(encoding="utf-8")))
    assert loaded == get_settings()


# --------------------------------------------------------------------------- #
# Environment overrides
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("env_name", "env_value", "path", "expected"),
    [
        ("XPM_REPLAY__SPEED", "5", ("replay", "speed"), 5.0),
        (
            "XPM_ALERTING__PROBABILITY_THRESHOLD",
            "0.7",
            ("alerting", "probability_threshold"),
            0.7,
        ),
        ("XPM_REPLAY__LOOP", "false", ("replay", "loop"), False),
        ("XPM_REPLAY__AUTOSTART", "true", ("replay", "autostart"), True),
        ("XPM_API__WS_PING_SECONDS", "3", ("api", "ws_ping_seconds"), 3),
        ("XPM_EXPLANATION__TOP_K", "12", ("explanation", "top_k"), 12),
        ("XPM_LOGGING__LEVEL", "DEBUG", ("logging", "level"), "DEBUG"),
        ("XPM_MQTT__HOST", "localhost", ("mqtt", "host"), "localhost"),
    ],
)
def test_env_override(
    pristine_env: None,
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    env_value: str,
    path: tuple[str, str],
    expected: object,
) -> None:
    monkeypatch.setenv(env_name, env_value)
    get_settings.cache_clear()
    node: Any = get_settings()
    for part in path:
        node = getattr(node, part)
    assert node == expected


def test_env_override_leaves_siblings_alone(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sources are deep-merged, so one leaf does not blank out its section."""
    monkeypatch.setenv("XPM_ALERTING__WATCH_THRESHOLD", "0.2")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.alerting.watch_threshold == 0.2
    assert settings.alerting.probability_threshold == 0.60
    assert settings.alerting.severity_bands.high == 0.75


def test_env_override_of_a_nested_severity_band(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XPM_ALERTING__SEVERITY_BANDS", '{"medium":0.5,"high":0.7,"critical":0.95}')
    get_settings.cache_clear()
    assert get_settings().alerting.severity_bands.medium == 0.5


def test_invalid_env_override_is_rejected(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XPM_REPLAY__SPEED", "3.0")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


def test_unknown_key_in_the_yaml_is_rejected(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``extra="forbid"`` catches a typo before it silently does nothing."""
    raw = yaml.safe_load(settings_file().read_text(encoding="utf-8"))
    raw["alerting"]["probabilty_threshold"] = 0.6
    broken = tmp_path / "settings.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(broken))
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


def test_config_file_env_selects_the_file(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = yaml.safe_load(settings_file().read_text(encoding="utf-8"))
    raw["api"]["ws_flush_ms"] = 250
    alternative = tmp_path / "settings.yaml"
    alternative.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(alternative))
    get_settings.cache_clear()
    assert settings_file() == alternative
    assert get_settings().api.ws_flush_ms == 250


# --------------------------------------------------------------------------- #
# Caching and path resolution
# --------------------------------------------------------------------------- #


def test_get_settings_is_cached(pristine_env: None) -> None:
    assert get_settings() is get_settings()


def test_reload_settings_rereads(pristine_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    monkeypatch.setenv("XPM_EXPLANATION__TOP_K", "4")
    second = reload_settings()
    assert first is not second
    assert second.explanation.top_k == 4
    assert get_settings() is second


def test_relative_paths_resolve_against_the_project_root(pristine_env: None) -> None:
    root = project_root()
    assert (root / "config" / "settings.yaml").is_file()
    assert data_dir() == root / "data"
    assert db_path() == root / "data" / "xpm.db"
    assert models_dir() == root / "models" / "registry"
    assert reports_dir() == root / "reports"


def test_absolute_paths_are_left_alone(pristine_env: None, tmp_path: Path) -> None:
    assert resolve_path(tmp_path) == tmp_path


def test_xpm_paths_env_override_is_honoured(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XPM_PATHS__DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    assert data_dir() == tmp_path


# --------------------------------------------------------------------------- #
# The contract couplings
# --------------------------------------------------------------------------- #


def _speed_literals() -> set[float]:
    """``get_args(ReplayCommand.speed)`` minus ``None``.

    The annotation is ``Literal[...] | None``, so the union members are unwrapped
    one level before the literal values are collected.
    """
    speeds: set[float] = set()
    for member in get_args(ReplayCommand.model_fields["speed"].annotation):
        if member is type(None):
            continue
        speeds.update(value for value in get_args(member) if isinstance(value, float | int))
    return speeds


def test_replay_speed_literal_matches_allowed_speeds(defaults: Settings) -> None:
    """The generated ``Speed`` type and the config list can never drift."""
    assert _speed_literals() == set(defaults.replay.allowed_speeds)


def test_changing_allowed_speeds_is_a_contract_change(defaults: Settings) -> None:
    """Editing the YAML list alone must fail this coupling, not pass quietly."""
    drifted = defaults.model_copy(
        update={"replay": defaults.replay.model_copy(update={"allowed_speeds": [0.5, 1.0]})}
    )
    assert _speed_literals() != set(drifted.replay.allowed_speeds)


def test_configured_speed_is_one_of_the_allowed_speeds(defaults: Settings) -> None:
    assert defaults.replay.speed in defaults.replay.allowed_speeds


def test_flattened_tree_contains_every_guaranteed_key(defaults: Settings) -> None:
    flat = flatten_settings(defaults)
    for key, expected in GUARANTEED_KEYS:
        assert key in flat, f"{key} missing from ConfigResponse.values"
        assert flat[key] == expected


def test_mutable_keys_are_a_subset_of_the_flattened_tree(defaults: Settings) -> None:
    flat = flatten_settings(defaults)
    assert set(MUTABLE_CONFIG_KEYS) <= set(flat)


def test_replay_speed_is_not_mutable() -> None:
    """R12: speed changes go through POST /api/replay/command and nowhere else."""
    assert "replay.speed" not in MUTABLE_CONFIG_KEYS
    assert "replay.allowed_speeds" not in MUTABLE_CONFIG_KEYS


def test_mutable_keys_match_the_plan() -> None:
    assert MUTABLE_CONFIG_KEYS == (
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


def test_flatten_uses_dotted_keys_and_json_scalars(defaults: Settings) -> None:
    flat = flatten_settings(defaults)
    assert flat["plants.ai4i.dataset_start"] == "2026-01-01T00:00:00.000Z"
    assert flat["paths.db_path"] == "data/xpm.db"
    assert flat["api.cors_origins"] == [
        "http://localhost:5173",
        "http://localhost:4173",
    ]
    assert all(not isinstance(value, dict) for value in flat.values())


def test_flatten_defaults_to_the_cached_settings(pristine_env: None) -> None:
    assert flatten_settings() == flatten_settings(get_settings())


def test_a_non_numeric_speed_override_is_reported_as_a_literal_error(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The float coercion passes non-numeric strings through untouched."""
    monkeypatch.setenv("XPM_REPLAY__SPEED", "fast")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


def test_project_root_falls_back_to_the_cwd(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CONFIG_FILE_ENV, str(tmp_path / "absent.yaml"))
    assert project_root() == Path.cwd()


def test_default_settings_file_falls_back_to_the_relative_path(
    pristine_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to walk up to — an install without the repo's ``config/`` tree."""
    monkeypatch.setattr(
        settings_module, "DEFAULT_CONFIG_RELPATH", Path("config") / "not-shipped.yaml"
    )
    assert default_settings_file() == Path("config") / "not-shipped.yaml"
