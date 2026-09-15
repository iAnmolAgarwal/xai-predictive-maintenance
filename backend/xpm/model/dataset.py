"""The training matrix: windowed features in, a leakage-free time split out.

Everything the fit sees comes from here, so this module decides what every SHAP
value in the dashboard is attributed to. Three rules, all from backend.md:

1. **Features** are exactly ``xpm.features.registry.feature_names(plant_id)`` in
   registry order, produced by :func:`~xpm.features.offline.build_feature_frame`
   — the same code path the streaming engine runs, so a model fitted here cannot
   drift from the vectors it is served (§1, `xpm.features`).
2. **Warm-up rows are dropped.** Until a machine has
   ``features.min_window_coverage`` of the longest window, part of its vector is
   ``NaN``. Those rows carry no usable windowed evidence and their NaNs would
   also poison the interventional SHAP background (R3), so they are removed. The
   NaNs are a strict prefix per machine — no feature is ever NaN once the
   longest window is covered — so "drop the warm-up" and "keep the rows with a
   complete vector" are the same operation, and :func:`drop_warmup_rows` asserts
   that equivalence rather than assuming it.
3. **The split is ``model.split: grouped_time``** — see :func:`split_timestamp`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np
import pandas as pd

from xpm.config import get_settings
from xpm.contracts.common import PlantId
from xpm.contracts.settings import Settings
from xpm.features.offline import build_feature_frame
from xpm.features.registry import feature_names

__all__ = [
    "TrainingMatrix",
    "build_training_frame",
    "build_training_matrix",
    "drop_warmup_rows",
    "label_column",
    "matrix_from_frame",
    "split_timestamp",
]

#: The supervised target per plant. AI4I ships native labels; IMS's
#: ``failure_imminent`` is the last ``plants.ims.label_horizon_hours`` before
#: end-of-record on a bearing that actually fails (§3.2.3, ADR-023).
_LABEL_COLUMNS: Final[dict[str, str]] = {"ai4i": "machine_failure", "ims": "failure_imminent"}

#: Index columns :func:`build_feature_frame` prepends to the feature block.
INDEX_COLUMNS: Final[tuple[str, str]] = ("machine_id", "dataset_ts")


def label_column(plant_id: PlantId) -> str:
    """The name of ``plant_id``'s binary target column."""
    return _LABEL_COLUMNS[plant_id]


@dataclass(frozen=True, slots=True)
class TrainingMatrix:
    """One plant's fit-ready data: feature order, both splits and provenance.

    ``x_train``/``x_test`` are ``float64`` C-ordered arrays whose columns are
    ``feature_names`` in registry order — the ordering the manifest hashes and
    serving re-checks (§3.7).
    """

    plant_id: PlantId
    feature_names: tuple[str, ...]
    x_train: np.ndarray[tuple[int, ...], np.dtype[np.float64]]
    y_train: np.ndarray[tuple[int, ...], np.dtype[np.int64]]
    x_test: np.ndarray[tuple[int, ...], np.dtype[np.float64]]
    y_test: np.ndarray[tuple[int, ...], np.dtype[np.int64]]
    train_index: pd.DataFrame
    """``machine_id`` and ``dataset_ts`` of every training row, in fit order."""
    test_index: pd.DataFrame
    label: str
    split_ts: datetime
    """First dataset instant of the held-out set; training is strictly before."""
    warmup_rows_dropped: int

    @property
    def n_features(self) -> int:
        return len(self.feature_names)

    @property
    def n_train_rows(self) -> int:
        return int(self.x_train.shape[0])

    @property
    def n_test_rows(self) -> int:
        return int(self.x_test.shape[0])

    @property
    def train_positives(self) -> int:
        return int(self.y_train.sum())

    @property
    def test_positives(self) -> int:
        return int(self.y_test.sum())

    def train_window(self) -> tuple[datetime, datetime]:
        """First and last dataset instant covered by the training split."""
        stamps = self.train_index["dataset_ts"]
        return (stamps.min().to_pydatetime(), stamps.max().to_pydatetime())


def drop_warmup_rows(frame: pd.DataFrame, plant_id: PlantId) -> tuple[pd.DataFrame, int]:
    """Remove each machine's warm-up prefix, returning the frame and the count.

    A row is warm-up when any feature is ``NaN``. Rule 2 in the module docstring
    claims those rows form a per-machine prefix; this function verifies it, so a
    future feature that goes NaN mid-series fails loudly here instead of
    silently deleting interior rows and creating a gap the windows never had.
    """
    names = list(feature_names(plant_id))
    complete = np.asarray(~frame.loc[:, names].isna().to_numpy().any(axis=1), dtype=np.bool_)
    for _, positions in frame.groupby("machine_id", sort=True).indices.items():
        flags = complete[positions]
        first_complete = int(flags.argmax()) if bool(flags.any()) else len(flags)
        if not bool(flags[first_complete:].all()):
            raise ValueError(
                f"{plant_id}: NaN features after the warm-up prefix; the training "
                "matrix would drop interior rows"
            )
    kept = frame.iloc[np.flatnonzero(complete)].reset_index(drop=True)
    return kept, int(len(frame) - len(kept))


def split_timestamp(stamps: pd.Series, labels: pd.Series, *, test_size: float) -> pd.Timestamp:
    """The ``grouped_time`` cut: the first dataset instant of the held-out set.

    ``model.split: grouped_time`` is "group by machine, split by ``dataset_ts``,
    no leakage": one cut in dataset time, applied to every machine at once, so
    no machine has a training row later than any of its test rows and no window
    ever spans the cut.

    The cut is the **later** of two quantiles of ``dataset_ts`` at
    ``1 - test_size``: over all rows, and over the positive rows only. The
    all-rows quantile is the plain time split and is what AI4I gets, whose
    failures are spread through the run. The positives-only quantile is what
    keeps IMS trainable: its 144 positives are by construction the last 24 h of
    one bearing, so a plain time split puts **every** positive in the held-out
    set and leaves the fit with none. Taking the later of the two means the
    held-out set is never larger than the plain time split, and the fit always
    sees roughly ``1 - test_size`` of the positives. Both numbers land in
    ``docs/EVALUATION.md`` per plant, because on IMS this makes the held-out set
    small and positive-rich and that has to be read with the metrics.
    """
    positives = stamps.loc[labels.to_numpy().astype(bool)]
    if positives.empty:
        raise ValueError("training data contains no positive rows; nothing to learn")
    quantile = 1.0 - test_size
    overall_cut = stamps.quantile(quantile, interpolation="higher")
    positive_cut = positives.quantile(quantile, interpolation="higher")
    cut = max(overall_cut, positive_cut)
    return pd.Timestamp(cut)


def build_training_frame(
    plant_id: PlantId,
    *,
    frame: pd.DataFrame | None = None,
    settings: Settings | None = None,
) -> tuple[pd.DataFrame, int]:
    """The windowed frame for ``plant_id`` with its warm-up prefix removed.

    ``frame`` is a processed-parquet frame for testing; ``None`` loads the
    committed one.
    """
    built = build_feature_frame(plant_id, frame=frame, settings=settings)
    return drop_warmup_rows(built, plant_id)


def matrix_from_frame(
    plant_id: PlantId,
    frame: pd.DataFrame,
    *,
    warmup_rows_dropped: int = 0,
    settings: Settings | None = None,
) -> TrainingMatrix:
    """Split an already-windowed, warm-up-free feature frame into a matrix.

    Kept separate from :func:`build_training_matrix` so the tests can feed
    ``tests/fixtures/model/tiny_training_matrix.parquet`` straight in and never
    touch the full datasets.
    """
    resolved = settings if settings is not None else get_settings()
    names = feature_names(plant_id)
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise ValueError(f"{plant_id}: feature frame is missing {len(missing)} columns")
    label = label_column(plant_id)
    if label not in frame.columns:
        raise ValueError(f"{plant_id}: feature frame has no {label!r} column")

    ordered = frame.sort_values(list(INDEX_COLUMNS), kind="stable").reset_index(drop=True)
    stamps = pd.to_datetime(ordered["dataset_ts"], utc=True)
    labels = ordered[label].astype("int64")
    cut = split_timestamp(stamps, labels, test_size=resolved.model.test_size)

    is_train = np.asarray((stamps < cut).to_numpy(), dtype=np.bool_)
    features = ordered.loc[:, list(names)].to_numpy(dtype=np.float64)
    index = pd.DataFrame({"machine_id": ordered["machine_id"].astype(str), "dataset_ts": stamps})
    target = np.asarray(labels.to_numpy(), dtype=np.int64)

    train_positions = np.flatnonzero(is_train)
    test_positions = np.flatnonzero(~is_train)
    train_rows = int(train_positions.shape[0])
    if train_rows == 0 or train_rows == len(ordered):
        raise ValueError(f"{plant_id}: the grouped_time split left one side empty")

    return TrainingMatrix(
        plant_id=plant_id,
        feature_names=names,
        x_train=np.ascontiguousarray(features[train_positions]),
        y_train=target[train_positions],
        x_test=np.ascontiguousarray(features[test_positions]),
        y_test=target[test_positions],
        train_index=index.iloc[train_positions].reset_index(drop=True),
        test_index=index.iloc[test_positions].reset_index(drop=True),
        label=label,
        split_ts=cut.to_pydatetime(),
        warmup_rows_dropped=warmup_rows_dropped,
    )


def build_training_matrix(
    plant_id: PlantId,
    *,
    frame: pd.DataFrame | None = None,
    settings: Settings | None = None,
) -> TrainingMatrix:
    """Committed processed parquet -> fit-ready :class:`TrainingMatrix`."""
    built, dropped = build_training_frame(plant_id, frame=frame, settings=settings)
    return matrix_from_frame(plant_id, built, warmup_rows_dropped=dropped, settings=settings)
