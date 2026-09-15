"""Feature-group ablation, reported per plant and honestly (R4, ADR-004).

Each group refits the **served** family on a subset of the feature vector, with
the same seed, the same hyperparameters and the same held-out split as the real
model, and reports PR-AUC and ROC-AUC against the full vector. That is the only
honest way to answer "are the windowed features worth their complexity?".

The answer is expected to differ per plant and the document says so rather than
hiding it: AI4I's rows are i.i.d. product records dealt into virtual machines
(ADR-024), so its "history" is synthetic and the windowed features may not beat
the raw channels. IMS is real run-to-failure vibration, where they should. No
test asserts a favourable AI4I ablation and no number here is massaged.

Groups are derived from :mod:`xpm.features.registry` metadata, never from
hardcoded feature names, so adding a channel or a window changes the ablation
automatically. A group that would leave a plant with no features (for instance
"drop the vibration bands" on AI4I, which has none) is skipped, and
:func:`run_ablation` reports which groups ran.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from xpm.config import get_settings
from xpm.contracts.common import PlantId
from xpm.contracts.settings import Settings
from xpm.features.registry import FeatureMeta, feature_meta
from xpm.model.dataset import TrainingMatrix
from xpm.model.evaluate import AblationResult
from xpm.model.train import fit_family

__all__ = ["FULL_GROUP", "FeatureGroup", "feature_groups", "run_ablation", "select_columns"]

#: The reference row every ΔPR-AUC is measured against.
FULL_GROUP: Final[str] = "full"


@dataclass(frozen=True, slots=True)
class FeatureGroup:
    """A named subset of the feature vector, defined by a predicate on metadata."""

    name: str
    description: str
    keep: Callable[[FeatureMeta], bool]


#: The ablation table. ``full`` first; every other row is a *removal*, so a
#: negative ΔPR-AUC means the removed group was carrying signal.
GROUPS: Final[tuple[FeatureGroup, ...]] = (
    FeatureGroup(FULL_GROUP, "Full feature vector", lambda meta: True),
    FeatureGroup(
        "raw_only",
        "Raw channels only (all windowed statistics dropped)",
        lambda meta: meta.stat is None,
    ),
    FeatureGroup(
        "windowed_only",
        "Windowed statistics only (raw channels dropped)",
        lambda meta: meta.stat is not None,
    ),
    FeatureGroup(
        "no_vibration_bands",
        "Vibration band energies dropped (raw and windowed)",
        lambda meta: not meta.vibration_like,
    ),
    FeatureGroup(
        "no_long_windows",
        "Longest window dropped",
        lambda meta: meta.window_hours is None or meta.window_hours < _longest_window(),
    ),
)


def _longest_window() -> int:
    """The largest ``features.windows_hours`` entry, read at call time."""
    return max(get_settings().features.windows_hours)


def feature_groups() -> tuple[FeatureGroup, ...]:
    """The ablation groups, full vector first."""
    return GROUPS


def select_columns(plant_id: PlantId, group: FeatureGroup, names: Sequence[str]) -> list[int]:
    """Column positions of ``names`` that ``group`` keeps."""
    meta: Mapping[str, FeatureMeta] = feature_meta(plant_id)
    return [position for position, name in enumerate(names) if group.keep(meta[name])]


def run_ablation(
    matrix: TrainingMatrix, *, settings: Settings | None = None
) -> list[AblationResult]:
    """Fit and score every applicable group on ``matrix``.

    A group that keeps no features, or that keeps every feature without being
    ``full`` (nothing to remove on this plant), is skipped: reporting a
    duplicate of the full row as if it were an ablation would be a fabricated
    line in the table.
    """
    resolved = settings if settings is not None else get_settings()
    names = matrix.feature_names
    results: list[AblationResult] = []
    reference: float | None = None
    for group in feature_groups():
        columns = select_columns(matrix.plant_id, group, names)
        if not columns:
            continue
        if group.name != FULL_GROUP and len(columns) == len(names):
            continue
        auprc, auroc = _score_subset(matrix, columns, resolved)
        if group.name == FULL_GROUP:
            reference = auprc
        results.append(
            AblationResult(
                plant_id=matrix.plant_id,
                group=group.name,
                description=group.description,
                n_features=len(columns),
                auprc=auprc,
                auroc=auroc,
                delta_auprc=auprc - (reference if reference is not None else auprc),
            )
        )
    return results


def _score_subset(
    matrix: TrainingMatrix, columns: Sequence[int], settings: Settings
) -> tuple[float, float]:
    """Refit the served family on ``columns`` and score the held-out split."""
    index = np.asarray(columns, dtype=np.int64)
    names = [matrix.feature_names[position] for position in columns]
    model = fit_family(
        settings.model.served,
        np.ascontiguousarray(matrix.x_train[:, index]),
        matrix.y_train,
        settings=settings,
        feature_names=names,
    )
    held_out = pd.DataFrame(np.ascontiguousarray(matrix.x_test[:, index]), columns=names)
    proba = np.asarray(model.predict_proba(held_out)[:, 1], dtype=np.float64)
    return (
        float(average_precision_score(matrix.y_test, proba)),
        float(roc_auc_score(matrix.y_test, proba)),
    )
