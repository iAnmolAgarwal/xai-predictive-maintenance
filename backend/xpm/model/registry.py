"""The versioned model registry: the serving contract on disk (§3.7).

Layout, one directory per plant because the two plants have different feature
vectors (154 for ``ai4i``, 198 for ``ims``) and therefore different models::

    models/registry/
      current -> ai4i/lgbm/1.0.0        # the default plant's served model
      ai4i/
        current -> lgbm/1.0.0           # this plant's served family + version
        lgbm/1.0.0/
          model.txt            LightGBM native text booster (deterministic bytes)
          feature_names.json   ordered; the serving contract
          feature_meta.json    feature_meta_payload(plant_id)
          background.parquet   the frozen interventional SHAP background (R3)
          metrics.json         held-out metrics + calibration diagnostic
          model_card.md
          manifest.json
        rf/1.0.0/              same, with model.joblib instead of model.txt
      ims/ ...

The plant level is an addition to §3.7's sketch, which predates nothing else in
the plan: §3.7's own ``manifest.json`` carries ``plant_id`` and §3.4.1's
``ModelInfo`` is per plant, so two plants cannot share ``lgbm/1.0.0``. The
``current`` symlink is kept at both levels so ``ln -sfn`` is still the whole
rollback procedure and so the compose bootstrap's "train if
``models/registry/current`` is absent" check still works.

**No calibrator, of any kind, is ever written here** (R16, ADR-016):
:func:`artefact_names` is the complete artefact set and
``tests/model/test_registry.py`` asserts a freshly written version matches it
exactly.

:func:`validate_version` is the guard §3.7 calls the most likely silent failure
in the system: a model whose feature ordering disagrees with
:mod:`xpm.features.registry` would attribute every SHAP value to the wrong
feature name, so loading one is refused.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd

from xpm.config import models_dir, project_root
from xpm.contracts.common import MODEL_KINDS, ModelKind, PlantId
from xpm.features.registry import feature_meta_payload, feature_names, n_features

__all__ = [
    "CURRENT_LINK",
    "ModelVersion",
    "RegistryError",
    "VersionBump",
    "artefact_names",
    "bump_version",
    "code_sha",
    "feature_names_sha256",
    "list_versions",
    "load_background",
    "load_model",
    "next_version",
    "registry_root",
    "resolve_version",
    "save_version",
    "set_current",
    "validate_version",
]

#: Name of the rollback pointer at both registry levels.
CURRENT_LINK: Final[str] = "current"

#: The serialised scorer per family. LightGBM's native text format round-trips
#: byte-for-byte, which is what makes ``test_train_determinism.py`` an equality
#: assertion rather than a tolerance.
MODEL_FILENAMES: Final[dict[ModelKind, str]] = {"lgbm": "model.txt", "rf": "model.joblib"}

#: Everything a version directory holds besides the scorer.
SIDECAR_FILENAMES: Final[tuple[str, ...]] = (
    "feature_names.json",
    "feature_meta.json",
    "background.parquet",
    "metrics.json",
    "model_card.md",
    "manifest.json",
)

_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

VersionBump = Literal["major", "minor", "patch"]

#: Initial version of a family that has never been trained for a plant.
FIRST_VERSION: Final[str] = "1.0.0"


class RegistryError(RuntimeError):
    """A registry directory is missing, malformed, or disagrees with the code."""


def registry_root() -> Path:
    """Absolute ``paths.models_dir`` (``models/registry`` by default)."""
    return models_dir()


def artefact_names(family: ModelKind) -> tuple[str, ...]:
    """The complete, sorted file list of a version directory of ``family``."""
    return tuple(sorted((MODEL_FILENAMES[family], *SIDECAR_FILENAMES)))


def feature_names_sha256(names: tuple[str, ...]) -> str:
    """Hash of the feature **order**, not just its membership.

    ``json.dumps`` of the list preserves order and separators, so reordering two
    features changes the digest and serving refuses the model.
    """
    payload = json.dumps(list(names), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def code_sha() -> tuple[str | None, bool]:
    """``(git HEAD sha, working tree dirty)`` — ``(None, False)`` outside git.

    ``None`` is honest: an install from a wheel has no commit to name, and the
    manifest says so rather than inventing an identifier.
    """
    root = project_root()
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return (None, False)
    return (head.stdout.strip(), bool(status.stdout.strip()))


@dataclass(frozen=True, slots=True)
class Manifest:
    """``manifest.json`` (§3.7) plus the reproducibility block R5 asks for.

    ``train_run_id`` is deliberately **not** a replay ``run_id``: it uses the
    ``trn_`` prefix so the two can never be confused on the wire or in a log. It
    is the hash of everything that determines the artefact bytes — seed, plant,
    data digest, code sha, feature order and hyperparameters — so two runs with
    the same id must produce the same model, and a differing id names exactly
    which input moved.
    """

    model_id: str
    family: ModelKind
    version: str
    plant_id: PlantId
    trained_at: str
    seed: int
    n_features: int
    n_train_rows: int
    background_rows: int
    background_seed: int
    data_sha256: str
    code_sha: str | None
    feature_names_sha256: str
    train_run_id: str
    code_dirty: bool = False
    n_test_rows: int = 0
    train_positives: int = 0
    test_positives: int = 0
    label: str = ""
    split: str = ""
    split_ts: str = ""
    train_window_start: str = ""
    train_window_end: str = ""
    warmup_rows_dropped: int = 0
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    library_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Manifest:
        fields = {key: value for key, value in payload.items() if key in cls.__slots__}
        return cls(**fields)


@dataclass(frozen=True, slots=True)
class ModelVersion:
    """One resolved version directory."""

    root: Path
    plant_id: PlantId
    family: ModelKind
    version: str

    @property
    def path(self) -> Path:
        return self.root / self.plant_id / self.family / self.version

    @property
    def model_id(self) -> str:
        """The ``"lgbm@1.0.0"`` spelling §3.4.1's ``ModelInfo`` carries."""
        return f"{self.family}@{self.version}"

    def artefact(self, name: str) -> Path:
        return self.path / name

    @property
    def model_path(self) -> Path:
        return self.artefact(MODEL_FILENAMES[self.family])

    def manifest(self) -> Manifest:
        return Manifest.from_dict(_read_json(self.artefact("manifest.json")))

    def feature_names(self) -> tuple[str, ...]:
        loaded = _read_json(self.artefact("feature_names.json"))
        names = loaded["features"]
        return tuple(str(name) for name in names)

    def metrics(self) -> dict[str, Any]:
        return _read_json(self.artefact("metrics.json"))

    def card_relpath(self) -> str:
        """``ModelInfo.model_card_path``: repo-relative where possible."""
        card = self.artefact("model_card.md")
        try:
            return str(card.relative_to(project_root()))
        except ValueError:
            return str(card)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"registry artefact is missing: {path}")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_version(version: str) -> tuple[int, int, int]:
    """``"1.2.3"`` -> ``(1, 2, 3)``; anything else is a registry error."""
    match = _VERSION_PATTERN.match(version)
    if match is None:
        raise RegistryError(f"{version!r} is not a MAJOR.MINOR.PATCH version")
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def bump_version(version: str, bump: VersionBump) -> str:
    """Next version of ``version`` under ``--bump``."""
    major, minor, patch = parse_version(version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def list_versions(root: Path, plant_id: PlantId, family: ModelKind) -> list[str]:
    """Versions of ``family`` present for ``plant_id``, oldest first."""
    directory = root / plant_id / family
    if not directory.is_dir():
        return []
    found = [entry.name for entry in directory.iterdir() if entry.is_dir()]
    return sorted((name for name in found if _VERSION_PATTERN.match(name)), key=parse_version)


def next_version(root: Path, plant_id: PlantId, family: ModelKind, bump: VersionBump | None) -> str:
    """The version ``train.py`` should write.

    Without ``--bump`` a retrain **overwrites** the newest version: training is
    deterministic, so rewriting the same version with the same inputs is a
    no-op, and a demo that retrains on every boot must not grow the registry.
    """
    existing = list_versions(root, plant_id, family)
    if not existing:
        return FIRST_VERSION
    if bump is None:
        return existing[-1]
    return bump_version(existing[-1], bump)


def set_current(root: Path, plant_id: PlantId, family: ModelKind, version: str) -> None:
    """Point ``<plant>/current`` (and the top-level pointer) at a version.

    Both links are **relative**, so a registry directory stays valid when it is
    bind-mounted into a container at a different absolute path.
    """
    _relink(root / plant_id / CURRENT_LINK, Path(family) / version)
    _relink(root / CURRENT_LINK, Path(plant_id) / family / version)


def _relink(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def _read_link(link: Path) -> Path | None:
    if not link.is_symlink():
        return None
    return Path(os.readlink(link))


def resolve_version(
    root: Path,
    plant_id: PlantId,
    family: ModelKind | None = None,
    version: str = CURRENT_LINK,
) -> ModelVersion:
    """Resolve ``(plant, family, version)`` to a directory that exists.

    ``family=None`` with ``version="current"`` follows the plant's ``current``
    pointer, which is how the API loads the served model. An explicit family
    with ``version="current"`` means "the newest version of that family", which
    is how the comparison model is loaded without a second pointer.
    """
    if version == CURRENT_LINK and family is None:
        target = _read_link(root / plant_id / CURRENT_LINK)
        if target is None:
            raise RegistryError(
                f"{plant_id}: no current model in {root}; run `make train` to create one"
            )
        parts = target.parts
        if len(parts) != 2 or parts[0] not in MODEL_KINDS:
            raise RegistryError(f"{plant_id}: current points at {target}, not <family>/<version>")
        resolved_family: ModelKind = "lgbm" if parts[0] == "lgbm" else "rf"
        return _require(ModelVersion(root, plant_id, resolved_family, parts[1]))
    if family is None:
        raise RegistryError("an explicit version needs an explicit family")
    if version == CURRENT_LINK:
        existing = list_versions(root, plant_id, family)
        if not existing:
            raise RegistryError(f"{plant_id}/{family}: no versions in {root}")
        return _require(ModelVersion(root, plant_id, family, existing[-1]))
    return _require(ModelVersion(root, plant_id, family, version))


def _require(version: ModelVersion) -> ModelVersion:
    if not version.path.is_dir():
        raise RegistryError(f"registry version directory is missing: {version.path}")
    return version


def save_version(
    root: Path,
    *,
    plant_id: PlantId,
    family: ModelKind,
    version: str,
    model: Any,
    manifest: Manifest,
    background: pd.DataFrame,
    metrics: dict[str, Any],
    model_card: str,
) -> ModelVersion:
    """Write one complete version directory and return it.

    The artefact set written here is exactly :func:`artefact_names`; anything
    else in the directory (a calibrator, say — R16) is a bug, and a stale
    retrain of the same version cannot leave one behind because the directory is
    emptied of known artefacts first.
    """
    entry = ModelVersion(root, plant_id, family, version)
    entry.path.mkdir(parents=True, exist_ok=True)
    for stale in entry.path.iterdir():
        if stale.is_file():
            stale.unlink()

    if family == "lgbm":
        model.booster_.save_model(str(entry.model_path))
    else:
        _joblib_dump(model, entry.model_path)

    names = feature_names(plant_id)
    _write_json(
        entry.artefact("feature_names.json"),
        {
            "plant_id": plant_id,
            "n_features": len(names),
            "features": list(names),
            "sha256": feature_names_sha256(names),
        },
    )
    _write_json(entry.artefact("feature_meta.json"), dict(feature_meta_payload(plant_id)))
    background.to_parquet(
        entry.artefact("background.parquet"), engine="pyarrow", compression="zstd", index=False
    )
    _write_json(entry.artefact("metrics.json"), metrics)
    entry.artefact("model_card.md").write_text(model_card, encoding="utf-8")
    _write_json(entry.artefact("manifest.json"), manifest.to_dict())

    written = sorted(item.name for item in entry.path.iterdir() if item.is_file())
    expected = list(artefact_names(family))
    if written != expected:
        raise RegistryError(f"{entry.path}: wrote {written}, expected {expected}")
    return entry


def validate_version(entry: ModelVersion) -> Manifest:
    """Refuse a version whose feature contract disagrees with the code.

    Checks, in order: the artefact set is complete; the manifest's plant and
    family match the path; ``n_features`` matches
    :func:`~xpm.features.registry.n_features`; and the stored feature order
    hashes to ``feature_names_sha256``. The last one is §3.7's "single most
    likely silent failure".
    """
    missing = [name for name in artefact_names(entry.family) if not entry.artefact(name).is_file()]
    if missing:
        raise RegistryError(f"{entry.path}: missing artefacts {missing}")

    manifest = entry.manifest()
    if manifest.plant_id != entry.plant_id or manifest.family != entry.family:
        raise RegistryError(
            f"{entry.path}: manifest says {manifest.plant_id}/{manifest.family}, "
            f"path says {entry.plant_id}/{entry.family}"
        )

    expected_names = feature_names(entry.plant_id)
    stored_names = entry.feature_names()
    expected_count = n_features(entry.plant_id)
    if manifest.n_features != expected_count or len(stored_names) != expected_count:
        raise RegistryError(
            f"{entry.path}: model has {manifest.n_features} features, the feature "
            f"registry has {expected_count}; refusing to serve it"
        )
    stored_digest = feature_names_sha256(stored_names)
    if stored_digest != manifest.feature_names_sha256:
        raise RegistryError(f"{entry.path}: feature_names.json disagrees with its own manifest")
    if stored_digest != feature_names_sha256(expected_names):
        raise RegistryError(
            f"{entry.path}: feature order disagrees with xpm.features.registry; "
            "every SHAP value would be attributed to the wrong feature"
        )
    return manifest


def load_background(entry: ModelVersion) -> pd.DataFrame:
    """The frozen background sample, columns in registry order."""
    return pd.read_parquet(entry.artefact("background.parquet"), engine="pyarrow")


def load_model(entry: ModelVersion) -> Any:
    """The scorer: a ``lightgbm.Booster`` or a fitted ``RandomForestClassifier``.

    Validated first — an unvalidated load is the failure mode §3.7 warns about.
    """
    validate_version(entry)
    if entry.family == "lgbm":
        import lightgbm as lgb

        return lgb.Booster(model_file=str(entry.model_path))
    return _joblib_load(entry.model_path)


def _joblib_dump(model: Any, path: Path) -> None:
    # joblib ships no py.typed marker and is not in pyproject's mypy override
    # list (it arrives transitively with scikit-learn), so the import is
    # untyped; the two call sites are wrapped here rather than spread out.
    import joblib  # type: ignore[import-untyped]

    joblib.dump(model, path, compress=0)


def _joblib_load(path: Path) -> Any:
    # The ignore sits on the first import above; mypy needs it only once per
    # module for the same untyped package.
    import joblib

    return joblib.load(path)
