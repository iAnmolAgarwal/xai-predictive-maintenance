"""Tests for the SHAP service, the templater and what-if (T-SHAP).

The shared plumbing lives here rather than in ``conftest.py`` so the golden
regeneration path is importable.

Both plants are exercised against **real, trained models**: the suite trains
LightGBM and RandomForest once per session into a temporary registry — AI4I from
``tests/fixtures/model/tiny_training_matrix.parquet`` (T-MODEL's committed slice
of the real matrix) and IMS from the committed processed parquet — so no test
depends on ``make train`` having been run, and every SHAP number in the goldens
comes from a fit a fresh clone can reproduce.

Regenerate the goldens with::

    uv run pytest tests/explain --update-goldens
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

from xpm.contracts.common import PlantId
from xpm.explain.explainer import Explainer, FeatureSnapshot, QuantileFn
from xpm.features.offline import build_vectors
from xpm.features.online import FeatureVector, OnlineFeatureEngine
from xpm.features.registry import feature_names
from xpm.model import train
from xpm.model.dataset import TrainingMatrix, build_training_matrix, matrix_from_frame

FIXTURE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "fixtures" / "explain"
TINY_MATRIX_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "fixtures" / "model" / "tiny_training_matrix.parquet"
)

#: The machine each plant's golden explanation is taken from. ``ai4i-01`` is in
#: T-MODEL's tiny fixture; ``ims-01`` is the bearing that actually fails.
GOLDEN_MACHINES: Final[dict[str, str]] = {"ai4i": "ai4i-01", "ims": "ims-01"}

#: Placeholder-free ids for the fixtures, matching the contract patterns.
GOLDEN_ALERT_ID: Final[str] = "alt_0123456789abcdef"

#: Relative tolerance when a golden float is compared. The structure, the
#: strings and the feature order are compared exactly; the SHAP values are
#: compared with a tolerance because they come from a LightGBM fit, and a
#: different libomp build can move the last bits without changing anything the
#: user sees.
GOLDEN_RTOL: Final[float] = 1e-6


def tiny_matrix(plant_id: PlantId) -> TrainingMatrix:
    """A small but real training matrix for ``plant_id``."""
    if plant_id == "ai4i":
        names = list(feature_names("ai4i"))
        frame = pd.read_parquet(TINY_MATRIX_PATH, engine="pyarrow")
        return matrix_from_frame("ai4i", frame.astype({name: "float64" for name in names}))
    return build_training_matrix("ims")


def train_registry(root: Path) -> Path:
    """Fit both families of both plants into ``root`` and return it."""
    for plant_id in ("ai4i", "ims"):
        train.train_plant(plant_id, matrix=tiny_matrix(plant_id), root=root, data_sha256="0" * 64)
    return root


def riskiest_snapshot(
    plant_id: PlantId, explainer: Explainer, *, with_bands: bool = True
) -> FeatureSnapshot:
    """The highest-scoring complete row of the golden machine's own history.

    Highest-scoring because that is the row an alert would fire on, which is the
    row the dashboard explains. With ``with_bands`` the machine is replayed
    through :class:`OnlineFeatureEngine` up to that row so the snapshot carries
    the history bands the pipeline would pass in.
    """
    machine_id = GOLDEN_MACHINES[plant_id]
    vectors = build_vectors(plant_id, machine_id)
    best = riskiest_index(vectors, explainer)
    if not with_bands:
        return FeatureSnapshot.from_vector(vectors[best])
    return FeatureSnapshot.from_vector(vectors[best], quantile=quantile_at(vectors, best))


def riskiest_index(vectors: Sequence[FeatureVector], explainer: Explainer) -> int:
    """Position of the highest-scoring row whose feature vector is complete."""
    matrix = np.vstack([vector.values for vector in vectors])
    complete = ~np.isnan(matrix).any(axis=1)
    if not complete.any():
        raise AssertionError("no complete feature vector in this history")
    scores = np.full(len(vectors), -np.inf)
    scores[complete] = explainer.probabilities(matrix[complete])
    return int(np.argmax(scores))


def quantile_at(vectors: Sequence[FeatureVector], row_index: int) -> QuantileFn:
    """The live percentile query, holding history up to ``row_index``.

    The machine is replayed from its own rows' channel values, so this is the
    same :class:`MachineFeatureState` the streaming pipeline would hold at the
    instant the alert fires.
    """
    first = vectors[0]
    engine = OnlineFeatureEngine(first.plant_id)
    for vector in vectors[: row_index + 1]:
        engine.update_row(vector.machine_id, vector.dataset_ts, dict(vector.channels))
    return engine.state_for(first.machine_id).quantile
