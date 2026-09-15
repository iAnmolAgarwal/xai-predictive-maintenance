"""``shap.TreeExplainer`` in probability space, and the ``Explanation`` it fills.

One :class:`Explainer` per ``(plant_id, family)``, built exactly as R3/ADR-003
specifies::

    shap.TreeExplainer(model, data=background,
                       feature_perturbation="interventional",
                       model_output="probability")

and used unchanged for serving, what-if, model comparison and the faithfulness
script, so no two numbers on the screen can come from two different explainer
configurations. Construction loads a model and marginalises a 256-row
background; it is cached by :func:`get_explainer` and never rebuilt per request.

Two properties of this module are load-bearing.

**One probability (R16/ADR-016).** ``probability`` and ``output_value`` are the
served model's own predicted probability — :func:`xpm.model.evaluate.predict_proba`
— never a number re-derived from SHAP values and never a calibrated one. There
is no calibrator anywhere in this package.

**The waterfall closes exactly.** ``other_contributions_shap`` is computed as
``output_value - base_value - Σ contributions[].shap``, so
``base_value + Σ contributions[].shap + other_contributions_shap ==
output_value`` to floating-point noise, which is the invariant the frontend
draws against and ``tests/explain/test_explainer.py`` asserts to
:data:`ADDITIVITY_ATOL`. That tail term is the summed contributions of the
folded features **plus** the explainer's own additivity residual, and the
residual is not always negligible: measured on this repository's models,
interventional ``TreeExplainer`` reproduces LightGBM's own output to about
2e-3 in probability space for the 400-tree AI4I booster (1e-8 for IMS), with the
error growing with the tree count (9e-8 at 5 trees, 5e-3 at 50, 5e-2 at 400 in
raw score space). Attributing that residual to the roll-up rather than silently
spreading it over the drawn bars keeps every bar a real SHAP value and keeps the
arithmetic on screen exact. :data:`FULL_VECTOR_ADDITIVITY_ATOL` is the regression
guard on the residual itself.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from xpm.config import get_settings
from xpm.contracts.common import ModelKind, PlantId
from xpm.contracts.rest import Explanation, ShapContribution
from xpm.contracts.settings import Settings
from xpm.explain import narrative
from xpm.explain.framing import ClauseFacts, history_levels, resolve_clause
from xpm.features.online import FeatureVector
from xpm.features.registry import FeatureMeta, feature_index, feature_meta, feature_names
from xpm.features.stats import Float64Array
from xpm.model import evaluate as model_evaluate
from xpm.model import registry

__all__ = [
    "ADDITIVITY_ATOL",
    "FULL_VECTOR_ADDITIVITY_ATOL",
    "Explainer",
    "FeatureSnapshot",
    "QuantileFn",
    "ShapRow",
    "clear_explainer_cache",
    "explanation_id_for",
    "get_explainer",
]

#: Tolerance for the closing invariant the frontend draws against, §3.4.3:
#: ``|base + Σ contributions + other - output| < 1e-6``. It holds by
#: construction here; the constant exists so the tests state the contract.
ADDITIVITY_ATOL: Final[float] = 1e-6

#: Tolerance for the *raw* additivity of the untruncated SHAP vector,
#: ``|base + Σ all shap - probability|``. This is a property of the SHAP
#: implementation, not of this code: see the module docstring for the measured
#: numbers. Kept as a regression guard — a library upgrade that made it worse
#: would move the roll-up bar, and a release that made interventional TreeSHAP
#: exact would let this drop to :data:`ADDITIVITY_ATOL`.
FULL_VECTOR_ADDITIVITY_ATOL: Final[float] = 5e-3

#: ``Explanation.probability`` is a ``[0, 1]`` contract type; a model output of
#: 1 + 1e-16 must not become a validation error at the API boundary.
_PROBABILITY_BOUNDS: Final[tuple[float, float]] = (0.0, 1.0)

#: Length of the hex digest in ``exp_[0-9a-f]{16}`` (contracts §3.1).
_ID_HEX_DIGITS: Final[int] = 16

#: A feature -> ``(floor, ceiling)`` band read from a machine's own history.
Band = tuple[float, float]

#: ``(feature, percentile level) -> value``, satisfied by
#: :meth:`xpm.features.online.MachineFeatureState.quantile`. A ``None`` result
#: means the feature is still inside ``features.percentile_warmup_samples``.
QuantileFn = Callable[[str, float], float | None]


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    """One machine's feature vector at one instant, as the explainer needs it.

    Pure data, so the pipeline can persist it beside the alert and a later
    what-if or scrub can recompute against exactly the row that fired
    (ADR-027 stores explanations; what-if needs the vector they came from).
    ``values``, ``percentiles`` and ``streak_hours`` are positional and aligned
    to :func:`~xpm.features.registry.feature_names`, the same ordering the model
    artefact hashes.
    """

    plant_id: PlantId
    machine_id: str
    dataset_ts: datetime
    values: tuple[float, ...]
    percentiles: tuple[float | None, ...]
    streak_hours: tuple[float | None, ...]
    bands: Mapping[str, Band] = field(default_factory=dict)
    """Per-feature ``(floor, ceiling)`` from the machine's own history. Empty is
    valid: the channel's nominal bounds are then used (see
    :mod:`xpm.explain.framing`)."""

    def __post_init__(self) -> None:
        expected = len(feature_names(self.plant_id))
        for name, column in (
            ("values", self.values),
            ("percentiles", self.percentiles),
            ("streak_hours", self.streak_hours),
        ):
            if len(column) != expected:
                raise ValueError(
                    f"{self.plant_id}: {name} has {len(column)} entries, "
                    f"the feature vector has {expected}"
                )

    @classmethod
    def from_vector(
        cls, vector: FeatureVector, *, quantile: QuantileFn | None = None
    ) -> FeatureSnapshot:
        """Build a snapshot from the feature engine's own output.

        ``quantile`` is :meth:`MachineFeatureState.quantile`. Passing it
        materialises every feature's history band once, which is what makes the
        persisted snapshot self-contained; leaving it out falls back to the
        channels' nominal bounds.
        """
        values = tuple(float(item) for item in vector.values)
        return cls(
            plant_id=vector.plant_id,
            machine_id=vector.machine_id,
            dataset_ts=vector.dataset_ts,
            values=values,
            percentiles=tuple(_optional(float(item)) for item in vector.percentiles),
            streak_hours=tuple(_optional(float(item)) for item in vector.streak_hours),
            bands=bands_for(vector.plant_id, vector.names, quantile),
        )

    def as_array(self) -> Float64Array:
        """The positional vector the model scores."""
        return np.asarray(self.values, dtype=np.float64)

    def value_of(self, feature: str) -> float | None:
        """A feature's value, or ``None`` when it is not yet computable."""
        return _optional(self.values[self._position(feature)])

    def percentile_of(self, feature: str) -> float | None:
        return self.percentiles[self._position(feature)]

    def streak_of(self, feature: str) -> float | None:
        return self.streak_hours[self._position(feature)]

    def with_overrides(self, overrides: Mapping[str, float]) -> FeatureSnapshot:
        """A copy with ``overrides`` applied (the what-if vector).

        An overridden value is hypothetical, so its percentile rank and its
        streak are dropped rather than carried over from the real row: the
        machine's history contains no such observation, and reporting the old
        rank beside the new value would be the one number on the screen that is
        not true. The history *band* is kept — it describes the history, not the
        row.
        """
        values = list(self.values)
        percentiles = list(self.percentiles)
        streaks = list(self.streak_hours)
        for feature, replacement in overrides.items():
            position = self._position(feature)
            values[position] = float(replacement)
            percentiles[position] = None
            streaks[position] = None
        return FeatureSnapshot(
            plant_id=self.plant_id,
            machine_id=self.machine_id,
            dataset_ts=self.dataset_ts,
            values=tuple(values),
            percentiles=tuple(percentiles),
            streak_hours=tuple(streaks),
            bands=self.bands,
        )

    def _position(self, feature: str) -> int:
        position = feature_index(self.plant_id).get(feature)
        if position is None:
            raise KeyError(f"{feature!r} is not a feature of plant {self.plant_id!r}")
        return position


@dataclass(frozen=True, slots=True)
class ShapRow:
    """One row's SHAP values in probability space, before any truncation."""

    plant_id: PlantId
    model_id: str
    model_kind: ModelKind
    base_value: float
    probability: float
    values: Float64Array
    """Signed probability-space contributions, in feature-registry order."""

    @property
    def additivity_error(self) -> float:
        """``|base + Σ shap - probability|`` — the explainer's own residual."""
        return float(abs(self.base_value + float(self.values.sum()) - self.probability))


def bands_for(
    plant_id: PlantId,
    features: Sequence[str],
    quantile: QuantileFn | None = None,
    settings: Settings | None = None,
) -> dict[str, Band]:
    """Read ``(floor, ceiling)`` history bands for ``features``.

    Returns an empty mapping when no quantile source is given, and skips any
    feature whose history is still inside
    ``features.percentile_warmup_samples`` — those fall back to nominal bounds
    rather than to an invented number.
    """
    if quantile is None:
        return {}
    resolved = settings if settings is not None else get_settings()
    low, high = history_levels(resolved)
    bands: dict[str, Band] = {}
    for feature in features:
        floor = quantile(feature, low)
        ceiling = quantile(feature, high)
        if floor is None or ceiling is None:
            continue
        bands[feature] = (float(floor), float(ceiling))
    return bands


def explanation_id_for(alert_id: str, model_id: str, model_kind: ModelKind) -> str:
    """A deterministic ``exp_…`` id for one alert's explanation by one model.

    Deterministic so that a replay with the same seed and the same config
    reproduces the same explanation ids (R5), and keyed by model so the
    comparison view's two explanations never collide.
    """
    digest = hashlib.blake2b(
        f"{alert_id}|{model_id}|{model_kind}".encode(), digest_size=_ID_HEX_DIGITS // 2
    ).hexdigest()
    return f"exp_{digest}"


class Explainer:
    """A cached ``TreeExplainer`` plus everything needed to fill an ``Explanation``."""

    __slots__ = ("_background", "_entry", "_explainer", "_metas", "_model", "_names", "_settings")

    def __init__(self, entry: registry.ModelVersion, settings: Settings | None = None) -> None:
        resolved = settings if settings is not None else get_settings()
        shap_settings = resolved.model.shap
        model = registry.load_model(entry)
        background = registry.load_background(entry)
        if not len(background) or len(background) > shap_settings.background_rows:
            raise ValueError(
                f"{entry.path}: background has {len(background)} rows, "
                f"model.shap.background_rows is {shap_settings.background_rows}"
            )
        self._entry = entry
        self._settings = resolved
        self._model = model
        self._background = background
        self._names = feature_names(entry.plant_id)
        self._metas = feature_meta(entry.plant_id)
        self._explainer = _build_tree_explainer(model, background, resolved)

    @classmethod
    def load(
        cls,
        plant_id: PlantId,
        family: ModelKind = "lgbm",
        *,
        root: Path | None = None,
        settings: Settings | None = None,
    ) -> Explainer:
        """Resolve ``family``'s current version for ``plant_id`` and build it."""
        registry_path = root if root is not None else registry.registry_root()
        return cls(registry.resolve_version(registry_path, plant_id, family), settings)

    @property
    def plant_id(self) -> PlantId:
        return self._entry.plant_id

    @property
    def family(self) -> ModelKind:
        return self._entry.family

    @property
    def model_id(self) -> str:
        """``"lgbm@1.0.0"``. Not unique across plants: key on (plant, model_id)."""
        return self._entry.model_id

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._names

    @property
    def n_features(self) -> int:
        return len(self._names)

    @property
    def background(self) -> pd.DataFrame:
        """The frozen 256-row interventional background, in registry order."""
        return self._background

    @property
    def base_value(self) -> float:
        """The background's mean predicted probability — the waterfall's origin."""
        return float(np.asarray(self._explainer.expected_value).reshape(-1)[-1])

    def background_medians(self) -> Float64Array:
        """Per-feature median of the background — the faithfulness ablation target."""
        return np.asarray(np.median(self._background.to_numpy(dtype=np.float64), axis=0))

    def probabilities(self, matrix: Float64Array) -> Float64Array:
        """Served probabilities for a ``(rows, n_features)`` matrix (R16)."""
        return _clip(model_evaluate.predict_proba(self._entry, self._model, matrix))

    def shap_rows(self, matrix: Float64Array) -> tuple[ShapRow, ...]:
        """SHAP values in probability space for every row of ``matrix``."""
        block = _as_matrix(matrix, self.n_features)
        values = _positive_class(self._explainer.shap_values(block, check_additivity=False))
        probabilities = self.probabilities(block)
        base = self.base_value
        return tuple(
            ShapRow(
                plant_id=self.plant_id,
                model_id=self.model_id,
                model_kind=self.family,
                base_value=base,
                probability=float(probabilities[position]),
                values=np.asarray(values[position], dtype=np.float64),
            )
            for position in range(block.shape[0])
        )

    def shap_row(self, snapshot: FeatureSnapshot) -> ShapRow:
        """SHAP values for one snapshot."""
        self._require_plant(snapshot)
        return self.shap_rows(snapshot.as_array())[0]

    def explain(
        self,
        snapshot: FeatureSnapshot,
        *,
        alert_id: str,
        machine_display_name: str,
        explanation_id: str | None = None,
        quantile: QuantileFn | None = None,
        row: ShapRow | None = None,
    ) -> Explanation:
        """The stored ``Explanation`` for one alert (§3.4.3).

        ``row`` lets a caller that already computed the SHAP values (the
        comparison view) reuse them instead of paying for a second pass.
        """
        self._require_plant(snapshot)
        shap_row = row if row is not None else self.shap_row(snapshot)
        contributions, tail_shap, tail_count = self.contributions(
            snapshot, shap_row, quantile=quantile
        )
        sentence, spans = narrative.compose(
            machine_display_name,
            shap_row.probability,
            contributions,
            self._settings,
        )
        return Explanation(
            explanation_id=explanation_id
            or explanation_id_for(alert_id, self.model_id, self.family),
            alert_id=alert_id,
            machine_id=snapshot.machine_id,
            model_id=self.model_id,
            model_kind=self.family,
            shap_space="probability",
            dataset_ts=snapshot.dataset_ts,
            base_value=shap_row.base_value,
            output_value=shap_row.probability,
            probability=shap_row.probability,
            contributions=contributions,
            other_contributions_shap=tail_shap,
            other_contributions_count=tail_count,
            n_features=self.n_features,
            sentence=sentence,
            sentence_spans=spans,
            caveat=self._settings.explanation.caveat,
        )

    def contributions(
        self,
        snapshot: FeatureSnapshot,
        row: ShapRow,
        *,
        quantile: QuantileFn | None = None,
    ) -> tuple[list[ShapContribution], float, int]:
        """Rank, truncate and render: ``(contributions, tail_shap, tail_count)``.

        Ranking is by ``|shap|`` descending over the whole vector, truncated to
        ``explanation.top_k`` and then filtered by ``explanation.min_abs_shap``
        so a bar too small to see never displaces a real one. The tail term is
        whatever is needed to close on ``output_value`` (see the module
        docstring), and the tail *count* is the honest number of features not
        drawn, which is what R17's "N other features" label reads.
        """
        budget = self._settings.explanation
        magnitudes = np.abs(row.values)
        ranked = [int(position) for position in np.argsort(-magnitudes, kind="stable")]
        kept = [
            position
            for position in ranked[: budget.top_k]
            if magnitudes[position] >= budget.min_abs_shap
        ]
        lazy_bands = self._resolve_bands(snapshot, kept, quantile)
        contributions = [
            narrative.contribution(
                self._facts(snapshot, position, lazy_bands),
                float(row.values[position]),
                self._settings,
            )
            for position in kept
        ]
        drawn = float(sum(item.shap for item in contributions))
        tail_shap = float(row.probability - row.base_value - drawn)
        return contributions, tail_shap, self.n_features - len(contributions)

    def _facts(
        self, snapshot: FeatureSnapshot, position: int, bands: Mapping[str, Band]
    ) -> ClauseFacts:
        meta = self._metas[self._names[position]]
        return resolve_clause(
            meta,
            value=_optional(snapshot.values[position]),
            percentile=snapshot.percentiles[position],
            streak_hours=snapshot.streak_hours[position],
            history_band=bands.get(meta.name),
            window_mean=self._window_mean(snapshot, meta),
            settings=self._settings,
        )

    def _window_mean(self, snapshot: FeatureSnapshot, meta: FeatureMeta) -> float | None:
        """The ``mean`` sibling of a slope feature, for ``{rate}`` (§3.9)."""
        if meta.stat != "slope" or meta.window_hours is None:
            return None
        sibling = f"{meta.channel}_mean_{meta.window_hours}h"
        if sibling not in feature_index(snapshot.plant_id):
            return None
        return snapshot.value_of(sibling)

    def _resolve_bands(
        self, snapshot: FeatureSnapshot, positions: Sequence[int], quantile: QuantileFn | None
    ) -> Mapping[str, Band]:
        """Bands for the drawn features: persisted first, then live, then none.

        Reading them lazily for the handful of features an explanation draws is
        deliberate — ``quantile`` is a percentile query per feature and the
        vector has 154 or 198 of them.
        """
        if quantile is None:
            return snapshot.bands
        wanted = [
            self._names[position]
            for position in positions
            if self._names[position] not in snapshot.bands
        ]
        if not wanted:
            return snapshot.bands
        merged = dict(snapshot.bands)
        merged.update(bands_for(snapshot.plant_id, wanted, quantile, self._settings))
        return merged

    def _require_plant(self, snapshot: FeatureSnapshot) -> None:
        if snapshot.plant_id != self.plant_id:
            raise ValueError(
                f"snapshot is for plant {snapshot.plant_id!r}, "
                f"this explainer serves {self.plant_id!r}"
            )


@cache
def get_explainer(plant_id: PlantId, family: ModelKind = "lgbm") -> Explainer:
    """The process-wide cached explainer for ``(plant_id, family)``.

    Building one loads a model and a 256-row background; the API builds each of
    the four (two plants x two families) once at startup and never per request.
    Call :func:`clear_explainer_cache` after a retrain.
    """
    return Explainer.load(plant_id, family)


def clear_explainer_cache() -> None:
    """Drop every cached explainer (used after a retrain or in tests)."""
    get_explainer.cache_clear()


def _build_tree_explainer(model: Any, background: pd.DataFrame, settings: Settings) -> Any:
    """R3's explainer, with the whole background actually used.

    ``shap`` wraps a bare frame in an ``Independent`` masker capped at 100 rows
    and warns that it subsampled; an explicit masker sized to the background is
    the difference between marginalising over the frozen sample the manifest
    records and over an arbitrary 100-row subset of it. The frozen sample is
    ``min(model.shap.background_rows, training rows)`` — the whole training split
    when it is smaller, which is the case for the tiny test fixture.
    """
    import shap

    shap_settings = settings.model.shap
    masker = shap.maskers.Independent(background, max_samples=len(background))
    return shap.TreeExplainer(
        model,
        data=masker,
        feature_perturbation=shap_settings.feature_perturbation,
        model_output=shap_settings.model_output,
    )


def _positive_class(raw: Any) -> Float64Array:
    """Normalise ``shap_values`` output to ``(rows, features)`` for class 1.

    LightGBM boosters return a 2-D array for a binary objective; scikit-learn
    classifiers return one array per class, stacked on a third axis. Taking the
    last class is taking the positive one in both cases.
    """
    if isinstance(raw, list):
        return np.asarray(raw[-1], dtype=np.float64)
    array = np.asarray(raw, dtype=np.float64)
    if array.ndim == 3:
        return np.asarray(array[:, :, -1], dtype=np.float64)
    return array


def _as_matrix(matrix: Float64Array, n_features: int) -> Float64Array:
    block = np.atleast_2d(np.asarray(matrix, dtype=np.float64))
    if block.shape[1] != n_features:
        raise ValueError(f"expected {n_features} features per row, got {block.shape[1]}")
    return block


def _clip(values: Float64Array) -> Float64Array:
    low, high = _PROBABILITY_BOUNDS
    return np.asarray(np.clip(values, low, high), dtype=np.float64)


def _optional(value: float) -> float | None:
    """``NaN`` is §3.1's "not yet computable"; the wire spells it ``null``."""
    return None if np.isnan(value) else float(value)
