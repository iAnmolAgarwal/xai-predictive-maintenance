"""The registry is the serving contract on disk (backend.md §3.7).

Two things are load-bearing and both are asserted here: a freshly trained
version directory contains **exactly** the artefact set of §3.7 — no calibrator,
of any kind, anywhere (R16, ADR-016) — and a version whose feature order or
feature count disagrees with :mod:`xpm.features.registry` is refused rather than
served, because that mismatch would silently attribute every SHAP value to the
wrong feature name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from xpm.config import get_settings
from xpm.contracts.common import PLANT_IDS
from xpm.features.registry import feature_names, n_features
from xpm.model import registry, train
from xpm.model.registry import ModelVersion, RegistryError

from . import TINY_PLANT, tiny_matrix

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend" / "xpm"


@pytest.fixture(scope="module")
def trained_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real registry: both families of the tiny AI4I fixture."""
    root = tmp_path_factory.mktemp("registry")
    train.train_plant(TINY_PLANT, matrix=tiny_matrix(), root=root, data_sha256="0" * 64)
    return root


def test_version_directory_holds_exactly_the_documented_artefacts(trained_root: Path) -> None:
    for family, scorer in (("lgbm", "model.txt"), ("rf", "model.joblib")):
        entry = registry.resolve_version(trained_root, TINY_PLANT, family)
        written = sorted(item.name for item in entry.path.iterdir())
        assert written == sorted(
            [
                scorer,
                "background.parquet",
                "feature_meta.json",
                "feature_names.json",
                "manifest.json",
                "metrics.json",
                "model_card.md",
            ]
        )


def test_no_calibrator_artefact_exists(trained_root: Path) -> None:
    """R16: the registry contains one scorer per family and nothing that maps
    its probability to another probability."""
    found = [path.name for path in trained_root.rglob("*") if "calibrat" in path.name.lower()]
    assert found == []


def test_no_module_imports_sklearn_calibration() -> None:
    """The permanent guard: the serving path may not acquire a calibrator."""
    offenders = [
        path.relative_to(BACKEND_ROOT).as_posix()
        for path in BACKEND_ROOT.rglob("*.py")
        if "sklearn.calibration" in path.read_text(encoding="utf-8")
        or "CalibratedClassifierCV" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_current_pointer_resolves_to_the_served_family(trained_root: Path) -> None:
    served = registry.resolve_version(trained_root, TINY_PLANT)
    assert served.family == "lgbm"
    assert (trained_root / TINY_PLANT / "current").is_symlink()
    assert (trained_root / "current").is_symlink()
    # Relative, so a bind mount at another absolute path still resolves.
    assert not (trained_root / "current").readlink().is_absolute()
    assert served.model_id == "lgbm@1.0.0"
    assert served.card_relpath().endswith("model_card.md")


def test_round_trip_manifest_background_and_model(trained_root: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    manifest = registry.validate_version(entry)
    assert manifest.n_features == n_features(TINY_PLANT)
    assert manifest.plant_id == TINY_PLANT
    assert manifest.family == "lgbm"
    assert manifest.train_run_id.startswith("trn_")

    background = registry.load_background(entry)
    assert list(background.columns) == list(feature_names(TINY_PLANT))
    assert manifest.background_rows == len(background)

    booster = registry.load_model(entry)
    proba = booster.predict(tiny_matrix().x_test)
    assert proba.shape == (tiny_matrix().n_test_rows,)
    assert ((proba >= 0.0) & (proba <= 1.0)).all()

    forest = registry.load_model(registry.resolve_version(trained_root, TINY_PLANT, "rf"))
    assert forest.n_features_in_ == n_features(TINY_PLANT)


def test_metrics_json_is_the_scored_block(trained_root: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    metrics = entry.metrics()
    assert set(metrics) >= {"auroc", "auprc", "brier", "ece", "reliability"}
    assert len(metrics["reliability"]) >= 2


def test_reordered_feature_names_are_refused(trained_root: Path, tmp_path: Path) -> None:
    """§3.7's "single most likely silent failure"."""
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    copy_root = tmp_path / "tampered"
    _copy_version(entry, copy_root)
    tampered = ModelVersion(copy_root, TINY_PLANT, "lgbm", entry.version)

    names = list(feature_names(TINY_PLANT))
    names[0], names[1] = names[1], names[0]
    payload = json.loads(tampered.artefact("feature_names.json").read_text(encoding="utf-8"))
    payload["features"] = names
    payload["sha256"] = registry.feature_names_sha256(tuple(names))
    tampered.artefact("feature_names.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = json.loads(tampered.artefact("manifest.json").read_text(encoding="utf-8"))
    manifest["feature_names_sha256"] = payload["sha256"]
    tampered.artefact("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RegistryError, match="feature order disagrees"):
        registry.load_model(tampered)


def test_feature_count_mismatch_is_refused(trained_root: Path, tmp_path: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    copy_root = tmp_path / "shortened"
    _copy_version(entry, copy_root)
    tampered = ModelVersion(copy_root, TINY_PLANT, "lgbm", entry.version)
    manifest = json.loads(tampered.artefact("manifest.json").read_text(encoding="utf-8"))
    manifest["n_features"] = 3
    tampered.artefact("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RegistryError, match="refusing to serve"):
        registry.validate_version(tampered)


def test_manifest_disagreeing_with_its_own_feature_file_is_refused(
    trained_root: Path, tmp_path: Path
) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    copy_root = tmp_path / "selfinconsistent"
    _copy_version(entry, copy_root)
    tampered = ModelVersion(copy_root, TINY_PLANT, "lgbm", entry.version)
    manifest = json.loads(tampered.artefact("manifest.json").read_text(encoding="utf-8"))
    manifest["feature_names_sha256"] = "0" * 64
    tampered.artefact("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RegistryError, match="disagrees with its own manifest"):
        registry.validate_version(tampered)


def test_manifest_from_another_plant_is_refused(trained_root: Path, tmp_path: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    copy_root = tmp_path / "wrongplant"
    _copy_version(entry, copy_root)
    tampered = ModelVersion(copy_root, TINY_PLANT, "lgbm", entry.version)
    manifest = json.loads(tampered.artefact("manifest.json").read_text(encoding="utf-8"))
    manifest["plant_id"] = "ims"
    tampered.artefact("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RegistryError, match="manifest says"):
        registry.validate_version(tampered)


def test_missing_artefact_is_refused(trained_root: Path, tmp_path: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "lgbm")
    copy_root = tmp_path / "incomplete"
    _copy_version(entry, copy_root)
    tampered = ModelVersion(copy_root, TINY_PLANT, "lgbm", entry.version)
    tampered.artefact("background.parquet").unlink()

    with pytest.raises(RegistryError, match="missing artefacts"):
        registry.validate_version(tampered)


def test_resolution_errors_name_the_fix(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="make train"):
        registry.resolve_version(tmp_path, "ai4i")
    with pytest.raises(RegistryError, match="no versions"):
        registry.resolve_version(tmp_path, "ai4i", "lgbm")
    with pytest.raises(RegistryError, match="needs an explicit family"):
        registry.resolve_version(tmp_path, "ai4i", None, "1.0.0")
    with pytest.raises(RegistryError, match="directory is missing"):
        registry.resolve_version(tmp_path, "ai4i", "lgbm", "9.9.9")

    (tmp_path / "ai4i").mkdir()
    (tmp_path / "ai4i" / "current").symlink_to(Path("nonsense"), target_is_directory=True)
    with pytest.raises(RegistryError, match="not <family>/<version>"):
        registry.resolve_version(tmp_path, "ai4i")


def test_missing_json_artefact_reports_its_path(tmp_path: Path) -> None:
    entry = ModelVersion(tmp_path, "ai4i", "lgbm", "1.0.0")
    entry.path.mkdir(parents=True)
    with pytest.raises(RegistryError, match="artefact is missing"):
        entry.manifest()


def test_versions_are_listed_and_bumped_in_order(trained_root: Path) -> None:
    assert registry.list_versions(trained_root, TINY_PLANT, "lgbm") == ["1.0.0"]
    assert registry.list_versions(trained_root, "ims", "lgbm") == []
    assert registry.next_version(trained_root, TINY_PLANT, "lgbm", None) == "1.0.0"
    assert registry.next_version(trained_root, TINY_PLANT, "lgbm", "patch") == "1.0.1"
    assert registry.next_version(trained_root, TINY_PLANT, "lgbm", "minor") == "1.1.0"
    assert registry.next_version(trained_root, TINY_PLANT, "lgbm", "major") == "2.0.0"
    assert registry.next_version(trained_root, "ims", "rf", "minor") == "1.0.0"
    with pytest.raises(RegistryError, match=r"MAJOR\.MINOR\.PATCH"):
        registry.bump_version("1.0", "patch")


def test_retraining_a_version_replaces_its_artefacts(tmp_path: Path) -> None:
    """A stale file from an earlier layout must not survive a retrain."""
    matrix = tiny_matrix()
    train.train_plant(TINY_PLANT, matrix=matrix, root=tmp_path, data_sha256="0" * 64)
    entry = registry.resolve_version(tmp_path, TINY_PLANT, "lgbm")
    (entry.path / "calibrator.joblib").write_text("stale", encoding="utf-8")
    (entry.path / "scratch").mkdir()  # a directory is left alone, not unlinked
    train.train_plant(TINY_PLANT, matrix=matrix, root=tmp_path, data_sha256="0" * 64)
    assert not (entry.path / "calibrator.joblib").exists()
    assert (entry.path / "scratch").is_dir()
    assert registry.list_versions(tmp_path, TINY_PLANT, "lgbm") == ["1.0.0"]


def test_bumping_keeps_the_old_version_and_moves_current(tmp_path: Path) -> None:
    matrix = tiny_matrix()
    train.train_plant(TINY_PLANT, matrix=matrix, root=tmp_path, data_sha256="0" * 64)
    train.train_plant(TINY_PLANT, matrix=matrix, root=tmp_path, data_sha256="0" * 64, bump="minor")
    assert registry.list_versions(tmp_path, TINY_PLANT, "lgbm") == ["1.0.0", "1.1.0"]
    assert registry.resolve_version(tmp_path, TINY_PLANT).version == "1.1.0"


def test_save_version_rejects_an_unexpected_extra_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The artefact-set check is an assertion, not a comment."""
    matrix = tiny_matrix()
    monkeypatch.setattr(registry, "SIDECAR_FILENAMES", (*registry.SIDECAR_FILENAMES, "ghost.json"))
    with pytest.raises(RegistryError, match="expected"):
        train.train_plant(TINY_PLANT, matrix=matrix, root=tmp_path, data_sha256="0" * 64)


def test_registry_root_follows_settings() -> None:
    assert registry.registry_root().name == "registry"


def test_code_sha_reports_the_checkout() -> None:
    head, dirty = registry.code_sha()
    assert head is None or (len(head) == 40 and int(head, 16) >= 0)
    assert isinstance(dirty, bool)


def test_code_sha_is_none_outside_a_git_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An install from a wheel has no commit to name, and says so."""
    monkeypatch.setattr(registry, "project_root", lambda: tmp_path)
    assert registry.code_sha() == (None, False)


def _copy_version(entry: ModelVersion, root: Path) -> None:
    target = root / entry.plant_id / entry.family / entry.version
    target.mkdir(parents=True)
    for item in entry.path.iterdir():
        target.joinpath(item.name).write_bytes(item.read_bytes())


def test_background_parquet_is_readable_as_a_frame(trained_root: Path) -> None:
    entry = registry.resolve_version(trained_root, TINY_PLANT, "rf")
    frame = registry.load_background(entry)
    assert isinstance(frame, pd.DataFrame)
    assert not frame.isna().to_numpy().any()


def _register_both_plants(root: Path, *, default_first: bool) -> None:
    """Register the default plant and the other plant in the given order.

    The default plant is trained for real from the tiny fixture; the other plant
    is registered through :func:`registry.set_current` — the exact call
    ``train.train_plant`` makes at the end of a run — because its 198-feature
    model cannot be built from the 154-feature AI4I fixture.
    """
    settings = get_settings()
    other = next(plant for plant in PLANT_IDS if plant != settings.plants.default)

    def train_default() -> None:
        train.train_plant(
            settings.plants.default, matrix=tiny_matrix(), root=root, data_sha256="0" * 64
        )

    def register_other() -> None:
        registry.set_current(root, other, settings.model.served, registry.FIRST_VERSION)

    steps = [train_default, register_other] if default_first else [register_other, train_default]
    for step in steps:
        step()


@pytest.mark.parametrize("default_first", [True, False])
def test_top_level_current_tracks_the_default_plant_whatever_the_order(
    tmp_path: Path, default_first: bool
) -> None:
    """``make train`` trains every plant; the top-level link must not drift.

    It names ``plants.default``'s served model, so training order — ai4i then
    ims, or the reverse — cannot change what a reader following
    ``models/registry/current`` gets.
    """
    settings = get_settings()
    other = next(plant for plant in PLANT_IDS if plant != settings.plants.default)
    _register_both_plants(tmp_path, default_first=default_first)

    served = registry.resolve_version(tmp_path, settings.plants.default)
    top = (tmp_path / registry.CURRENT_LINK).readlink()
    assert not top.is_absolute()
    assert top == Path(settings.plants.default) / served.family / served.version
    # Each plant keeps its own pointer regardless.
    assert (tmp_path / settings.plants.default / registry.CURRENT_LINK).is_symlink()
    assert (tmp_path / other / registry.CURRENT_LINK).is_symlink()


def test_a_non_default_plant_alone_never_writes_the_top_level_link(tmp_path: Path) -> None:
    settings = get_settings()
    other = next(plant for plant in PLANT_IDS if plant != settings.plants.default)
    registry.set_current(tmp_path, other, settings.model.served, registry.FIRST_VERSION)
    assert not (tmp_path / registry.CURRENT_LINK).is_symlink()
