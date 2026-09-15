"""Fit, freeze and version the two models of one plant.

LightGBM is the served model and RandomForest is the comparison model (ADR-026);
both are fitted on the same matrix, the same split and the same seed, so the
dashboard's comparison view differs only by algorithm.

**Determinism is a requirement, not a nicety** (R5): the compose bootstrap
retrains when the registry is empty, CI retrains on every push, and
``tests/model/test_train_determinism.py`` asserts two runs produce byte-identical
``model.txt``. That is why every estimator is constructed with an explicit seed,
a single thread, and LightGBM's ``deterministic`` / ``force_row_wise`` flags:
LightGBM's default multi-threaded histogram construction is order-dependent and
would make the booster bytes differ run to run on the same data.

**No calibrator is fitted here** (R16, ADR-016). Class imbalance is handled
inside the fit by ``class_weight`` (both families), so the probability the model
returns is the probability the whole system uses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from xpm.config import get_settings
from xpm.contracts.common import MODEL_KINDS, ModelKind, PlantId
from xpm.contracts.settings import Settings
from xpm.data import loader
from xpm.model import background as background_module
from xpm.model import card, evaluate, registry
from xpm.model.dataset import TrainingMatrix, build_training_matrix
from xpm.model.registry import Manifest, ModelVersion, VersionBump

__all__ = ["TrainedModel", "fit_family", "make_lgbm", "make_rf", "train_plant", "train_run_id"]

#: LightGBM applies ``subsample`` only when bagging runs every *k*-th iteration;
#: with the default 0 the ``model.lgbm.subsample`` leaf in settings.yaml would
#: be silently ignored. Bagging every iteration is the only reading of that leaf
#: that makes it mean what it says, so the frequency is a code constant rather
#: than a second user-facing knob.
LGBM_SUBSAMPLE_FREQ: Final[int] = 1

#: One thread everywhere. Both libraries' parallel reductions are order- and
#: thread-count-dependent, so a multi-threaded fit would be reproducible only on
#: an identical core count. The full training run is seconds either way.
FIT_THREADS: Final[int] = 1

#: How many ranked features the model card prints.
CARD_TOP_FEATURES: Final[int] = 15


@dataclass(frozen=True, slots=True)
class TrainedModel:
    """One fitted family, its registry location and what it scored."""

    entry: ModelVersion
    family: ModelKind
    manifest: Manifest
    metrics: evaluate.ModelMetrics
    importances: dict[str, float]
    is_served: bool


def make_lgbm(settings: Settings) -> Any:
    """The served LightGBM classifier, configured for reproducible bytes."""
    import lightgbm as lgb

    params = settings.model.lgbm
    return lgb.LGBMClassifier(
        objective="binary",
        n_estimators=params.n_estimators,
        learning_rate=params.learning_rate,
        num_leaves=params.num_leaves,
        min_child_samples=params.min_child_samples,
        subsample=params.subsample,
        subsample_freq=LGBM_SUBSAMPLE_FREQ,
        colsample_bytree=params.colsample_bytree,
        class_weight=params.class_weight,
        random_state=settings.model.seed,
        n_jobs=FIT_THREADS,
        deterministic=True,
        force_row_wise=True,
        verbose=-1,
    )


def make_rf(settings: Settings) -> Any:
    """The comparison RandomForest."""
    from sklearn.ensemble import RandomForestClassifier

    params = settings.model.rf
    return RandomForestClassifier(
        n_estimators=params.n_estimators,
        max_depth=params.max_depth,
        min_samples_leaf=params.min_samples_leaf,
        class_weight=params.class_weight,
        random_state=settings.model.seed,
        n_jobs=FIT_THREADS,
    )


def hyperparameters(family: ModelKind, settings: Settings) -> dict[str, Any]:
    """The family's settings block as it goes into the manifest and the card."""
    block = settings.model.lgbm if family == "lgbm" else settings.model.rf
    params: dict[str, Any] = dict(block.model_dump())
    params["seed"] = settings.model.seed
    params["n_jobs"] = FIT_THREADS
    if family == "lgbm":
        params["subsample_freq"] = LGBM_SUBSAMPLE_FREQ
        params["deterministic"] = True
        params["force_row_wise"] = True
    return params


def fit_family(
    family: ModelKind,
    features: np.ndarray[Any, Any],
    labels: np.ndarray[Any, Any],
    *,
    settings: Settings,
    feature_names: Sequence[str] | None = None,
) -> Any:
    """Fit one family on an arbitrary column subset (the ablation uses this too).

    ``feature_names`` makes the fit see named columns, so ``model.txt`` carries
    the real feature names and scikit-learn can check the names again at predict
    time; pass the same names to :func:`_proba_from_estimator`.
    """
    columns = list(feature_names) if feature_names is not None else None
    frame = pd.DataFrame(features, columns=columns) if columns is not None else features
    model = make_lgbm(settings) if family == "lgbm" else make_rf(settings)
    model.fit(frame, labels)
    return model


def feature_importances(family: ModelKind, model: Any, names: Sequence[str]) -> dict[str, float]:
    """Native importances, normalised to sum to 1 so families are comparable.

    An all-zero importance vector (a model that split on nothing) is returned as
    zeros rather than dividing by zero.
    """
    raw = np.asarray(model.feature_importances_, dtype=np.float64)
    total = float(raw.sum())
    scaled = raw / total if total > 0.0 else raw
    return {name: float(value) for name, value in zip(names, scaled, strict=True)}


def train_run_id(
    *,
    seed: int,
    plant_id: PlantId,
    data_sha256: str,
    code_sha: str | None,
    feature_digest: str,
    params: Mapping[str, Any],
) -> str:
    """Identifier of one training input set (R5's reproducibility scope).

    Prefixed ``trn_`` and **never** ``run_``: a replay ``run_id`` identifies a
    stream of dataset rows, this identifies a set of model inputs, and conflating
    them in a log would be a real debugging trap.
    """
    payload = "|".join(
        [
            str(seed),
            plant_id,
            data_sha256,
            code_sha or "",
            feature_digest,
            json.dumps(dict(params), sort_keys=True, default=str),
        ]
    )
    return "trn_" + hashlib.blake2b(payload.encode("utf-8"), digest_size=6).hexdigest()


def _library_versions() -> dict[str, str]:
    import lightgbm as lgb
    import sklearn

    return {
        "lightgbm": str(lgb.__version__),
        "scikit_learn": str(sklearn.__version__),
        "numpy": np.__version__,
    }


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def train_plant(
    plant_id: PlantId,
    *,
    matrix: TrainingMatrix | None = None,
    root: Path | None = None,
    settings: Settings | None = None,
    bump: VersionBump | None = None,
    families: Sequence[ModelKind] = MODEL_KINDS,
    data_sha256: str | None = None,
) -> list[TrainedModel]:
    """Train, score, card and register every ``families`` model for ``plant_id``.

    ``matrix`` lets the tests train on ``tiny_training_matrix.parquet``;
    ``None`` builds the real one from the committed processed parquet.
    ``data_sha256`` defaults to that parquet's digest from its data manifest, so
    the manifest can prove which bytes the model was fitted on.
    """
    resolved = settings if settings is not None else get_settings()
    registry_path = root if root is not None else registry.registry_root()
    training = matrix if matrix is not None else build_training_matrix(plant_id, settings=resolved)
    digest = (
        data_sha256
        if data_sha256 is not None
        else str(loader.load_manifest(plant_id)["parquet_sha256"])
    )
    sample = background_module.sample_background(training, settings=resolved)
    head, dirty = registry.code_sha()
    feature_digest = registry.feature_names_sha256(training.feature_names)
    window_start, window_end = training.train_window()
    trained_at = _iso(datetime.now(UTC))

    trained: list[TrainedModel] = []
    for family in families:
        version = registry.next_version(registry_path, plant_id, family, bump)
        model = fit_family(
            family,
            training.x_train,
            training.y_train,
            settings=resolved,
            feature_names=training.feature_names,
        )
        entry = ModelVersion(registry_path, plant_id, family, version)
        proba = _proba_from_estimator(model, training.x_test, training.feature_names)
        metrics = evaluate.score_predictions(training.y_test, proba, settings=resolved)
        importances = feature_importances(family, model, training.feature_names)
        params = hyperparameters(family, resolved)
        manifest = Manifest(
            model_id=entry.model_id,
            family=family,
            version=version,
            plant_id=plant_id,
            trained_at=trained_at,
            seed=resolved.model.seed,
            n_features=training.n_features,
            n_train_rows=training.n_train_rows,
            background_rows=int(sample.shape[0]),
            background_seed=resolved.model.shap.background_seed,
            data_sha256=digest,
            code_sha=head,
            feature_names_sha256=feature_digest,
            train_run_id=train_run_id(
                seed=resolved.model.seed,
                plant_id=plant_id,
                data_sha256=digest,
                code_sha=head,
                feature_digest=feature_digest,
                params=params,
            ),
            code_dirty=dirty,
            n_test_rows=training.n_test_rows,
            train_positives=training.train_positives,
            test_positives=training.test_positives,
            label=training.label,
            split=resolved.model.split,
            split_ts=_iso(training.split_ts),
            train_window_start=_iso(window_start),
            train_window_end=_iso(window_end),
            warmup_rows_dropped=training.warmup_rows_dropped,
            hyperparameters=params,
            library_versions=_library_versions(),
        )
        registry.save_version(
            registry_path,
            plant_id=plant_id,
            family=family,
            version=version,
            model=model,
            manifest=manifest,
            background=sample,
            metrics=metrics.to_dict(),
            model_card=card.render_model_card(
                manifest,
                metrics=metrics.summary(),
                importances=importances,
                top_k=CARD_TOP_FEATURES,
            ),
        )
        registry.validate_version(entry)
        trained.append(
            TrainedModel(
                entry=entry,
                family=family,
                manifest=manifest,
                metrics=metrics,
                importances=importances,
                is_served=family == resolved.model.served,
            )
        )

    served = resolved.model.served
    for item in trained:
        if item.family == served:
            registry.set_current(
                registry_path, plant_id, served, item.entry.version, settings=resolved
            )
    return trained


def _proba_from_estimator(
    model: Any, features: np.ndarray[Any, Any], names: Sequence[str]
) -> np.ndarray[tuple[int, ...], np.dtype[np.float64]]:
    """Positive-class probability straight from the in-memory estimator.

    Both families are scikit-learn estimators at this point, and both were fitted
    with named columns, so the rows are handed back as a frame with the same
    names — otherwise scikit-learn warns about the mismatch on every call.
    :func:`xpm.model.evaluate.predict_proba` is the counterpart for the bare
    ``Booster`` the registry stores.
    """
    frame = pd.DataFrame(features, columns=list(names))
    return np.asarray(model.predict_proba(frame)[:, 1], dtype=np.float64)
