"""The frozen SHAP background sample (R3, ADR-003).

``shap.TreeExplainer(model, data=background,
feature_perturbation="interventional", model_output="probability")`` marginalises
over this sample, so it is the thing that fixes the waterfall's base value. It is
therefore an **artefact**, not a runtime choice: ``train.py`` writes
``background.parquet`` next to the model and serving, what-if, model comparison
and the faithfulness check all read that one file.

Two properties matter and both are tested:

* **Deterministic** — a pure function of ``model.shap.background_seed`` and the
  training split, so two trainings of the same data produce the same base value
  and the same explanation for the same alert (R5).
* **NaN-free and representative** — a NaN in an interventional background
  silently poisons every SHAP value, and a background whose class mix is not the
  training mix moves the base value away from the model's own prior. Rows are
  drawn stratified by label with proportional allocation, which keeps the mix
  and keeps the rare positive class present at 256 rows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.model.dataset import TrainingMatrix

__all__ = ["BACKGROUND_COLUMN_ORDER_NOTE", "sample_background", "select_background_rows"]

#: ``background.parquet``'s columns are ``feature_names`` in registry order, so
#: a consumer can feed it to the explainer without reindexing. Stated here
#: because T-SHAP and T-API rely on it.
BACKGROUND_COLUMN_ORDER_NOTE: str = "columns are feature_names(plant_id) in registry order"


def select_background_rows(
    labels: np.ndarray[tuple[int, ...], np.dtype[np.int64]], *, rows: int, seed: int
) -> np.ndarray[tuple[int, ...], np.dtype[np.int64]]:
    """Row positions of a seeded, label-stratified sample, in ascending order.

    Allocation is proportional to the label mix, rounded, then clamped so that
    every class present in ``labels`` keeps at least one row whenever the budget
    allows it — with a ~3 % positive rate and 256 rows, plain rounding would
    still yield ~9 positives, but the clamp is what makes the guarantee hold for
    the tiny fixture too. When ``rows`` is at least the population size the
    whole population is returned, which is the ``min(256, n)`` case the tests
    exercise.
    """
    if rows < 1:
        raise ValueError("model.shap.background_rows must be >= 1")
    population = int(labels.shape[0])
    if population == 0:
        raise ValueError("cannot sample a SHAP background from an empty training split")
    order = np.arange(population, dtype=np.int64)
    if rows >= population:
        return order

    positives = order[labels == 1]
    negatives = order[labels != 1]
    n_positive = round(rows * positives.shape[0] / population)
    if positives.shape[0] > 0:
        n_positive = max(1, min(n_positive, positives.shape[0], rows - 1))
    n_negative = rows - n_positive
    if n_negative > negatives.shape[0]:
        n_negative = negatives.shape[0]
        n_positive = rows - n_negative

    generator = np.random.default_rng(seed)
    picked = np.concatenate(
        [
            generator.choice(positives, size=n_positive, replace=False),
            generator.choice(negatives, size=n_negative, replace=False),
        ]
    )
    picked.sort()
    return np.asarray(picked, dtype=np.int64)


def sample_background(matrix: TrainingMatrix, *, settings: Settings | None = None) -> pd.DataFrame:
    """``background.parquet``'s body for ``matrix``'s plant.

    Drawn from the **training** split only: the held-out rows have to stay
    unseen, and the base value must describe what the model was fitted on.
    """
    resolved = settings if settings is not None else get_settings()
    shap_settings = resolved.model.shap
    picked = select_background_rows(
        matrix.y_train,
        rows=shap_settings.background_rows,
        seed=shap_settings.background_seed,
    )
    sample = matrix.x_train[picked]
    if not bool(np.isfinite(sample).all()):
        raise ValueError(
            "the SHAP background contains a non-finite value; interventional "
            "TreeExplainer would return NaN for every feature"
        )
    return pd.DataFrame(sample, columns=list(matrix.feature_names))
