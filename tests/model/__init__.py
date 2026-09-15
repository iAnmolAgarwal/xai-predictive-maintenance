"""Tests for training, evaluation and the model registry (T-MODEL).

Shared fixture plumbing lives here rather than in a ``conftest.py`` so the
regeneration path is importable and can be called from the one test that owns
it (``test_train_determinism.py::test_tiny_fixture_is_current``).

``tests/fixtures/model/tiny_training_matrix.parquet`` is a **small, real** slice
of the AI4I training matrix: two machines, every positive row, and every
``NEGATIVE_STRIDE``-th negative row, after the warm-up prefix has been dropped.
It is real data, so a model trained on it behaves like the real thing; it is
tiny, so the whole model suite trains in seconds and never touches the full
datasets. Regenerate with::

    XPM_REGENERATE_GOLDENS=1 uv run pytest tests/model -k tiny_fixture
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd

from xpm.contracts.common import PlantId
from xpm.features.registry import feature_names
from xpm.model.dataset import TrainingMatrix, build_training_frame, label_column, matrix_from_frame

FIXTURE_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "fixtures" / "model"
TINY_MATRIX_PATH: Final[Path] = FIXTURE_DIR / "tiny_training_matrix.parquet"
METRICS_BOUNDS_PATH: Final[Path] = FIXTURE_DIR / "expected_metrics_bounds.json"

REGENERATE_ENV: Final[str] = "XPM_REGENERATE_GOLDENS"
"""Set this to rewrite the fixture instead of asserting against it."""

TINY_PLANT: Final[PlantId] = "ai4i"
TINY_MACHINES: Final[tuple[str, ...]] = ("ai4i-01", "ai4i-02")
NEGATIVE_STRIDE: Final[int] = 6
"""Keep every sixth negative row. Positives are all kept, so the fixture's
prevalence is far above AI4I's real 3.4 % — it exists to exercise the code
paths, not to estimate a metric."""


def build_tiny_frame() -> pd.DataFrame:
    """Rebuild the fixture body from the committed processed parquet."""
    frame, _ = build_training_frame(TINY_PLANT)
    selected = frame[frame["machine_id"].isin(list(TINY_MACHINES))].reset_index(drop=True)
    label = label_column(TINY_PLANT)
    positive = selected[label].to_numpy().astype(bool)
    stride = (selected.index % NEGATIVE_STRIDE) == 0
    kept = selected.loc[positive | stride].reset_index(drop=True)
    columns = ["machine_id", "dataset_ts", *feature_names(TINY_PLANT), label]
    return kept.loc[:, columns].astype({name: "float32" for name in feature_names(TINY_PLANT)})


def write_tiny_frame(frame: pd.DataFrame) -> None:
    """Write the fixture parquet (float32 + zstd keeps it well under 1 MB)."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(TINY_MATRIX_PATH, engine="pyarrow", compression="zstd", index=False)


def load_tiny_frame() -> pd.DataFrame:
    """The committed fixture, with features back in the float64 the fit uses."""
    frame = pd.read_parquet(TINY_MATRIX_PATH, engine="pyarrow")
    return frame.astype({name: "float64" for name in feature_names(TINY_PLANT)})


def tiny_matrix() -> TrainingMatrix:
    """The fixture split exactly as ``train.py`` would split the real matrix."""
    return matrix_from_frame(TINY_PLANT, load_tiny_frame())
