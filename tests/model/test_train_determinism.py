"""Two trainings of the same inputs must produce the same artefacts (R5).

The compose bootstrap retrains when the registry is empty and CI retrains on
every push, so "the model is a pure function of the committed data plus a seed"
(ADR-022) is load-bearing: if it were false, a grader's alert ids, waterfalls
and explanation sentences would differ from the ones in the documents.

This file also owns the tiny fixture and the training matrix rules —
:mod:`xpm.model.dataset`'s warm-up drop and ``grouped_time`` split — because
those decide which rows the determinism claim is about.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from xpm.config import get_settings
from xpm.features.registry import feature_names
from xpm.model import registry, train
from xpm.model.dataset import (
    drop_warmup_rows,
    label_column,
    matrix_from_frame,
    split_timestamp,
)

from . import (
    REGENERATE_ENV,
    TINY_MACHINES,
    TINY_MATRIX_PATH,
    TINY_PLANT,
    build_tiny_frame,
    load_tiny_frame,
    tiny_matrix,
    write_tiny_frame,
)


def test_tiny_fixture_is_current() -> None:
    """The fixture is a real slice of the AI4I matrix, regenerable on demand.

    ``XPM_REGENERATE_GOLDENS=1 uv run pytest tests/model -k tiny_fixture``
    rewrites it; otherwise this asserts the committed file still matches what
    the feature engine produces today, which is what makes a feature change show
    up here instead of as a mysterious metric drift.
    """
    rebuilt = build_tiny_frame()
    if os.environ.get(REGENERATE_ENV):
        write_tiny_frame(rebuilt)
    committed = pd.read_parquet(TINY_MATRIX_PATH, engine="pyarrow")
    pd.testing.assert_frame_equal(committed, rebuilt)
    assert TINY_MATRIX_PATH.stat().st_size < 1_000_000
    assert set(committed["machine_id"]) == set(TINY_MACHINES)


def test_matrix_is_split_in_time_with_positives_on_both_sides() -> None:
    matrix = tiny_matrix()
    assert matrix.feature_names == feature_names(TINY_PLANT)
    assert matrix.n_features == len(feature_names(TINY_PLANT))
    assert matrix.label == label_column(TINY_PLANT)
    assert matrix.train_positives > 0
    assert matrix.test_positives > 0
    assert matrix.x_train.shape == (matrix.n_train_rows, matrix.n_features)
    assert matrix.x_test.shape == (matrix.n_test_rows, matrix.n_features)
    # No leakage: every training instant is strictly before every held-out one.
    assert matrix.train_index["dataset_ts"].max() < matrix.split_ts
    assert matrix.test_index["dataset_ts"].min() >= matrix.split_ts
    start, end = matrix.train_window()
    assert start <= end < matrix.split_ts
    # Both machines are on both sides: the cut is in time, not by machine.
    assert set(matrix.train_index["machine_id"]) == set(TINY_MACHINES)
    assert set(matrix.test_index["machine_id"]) == set(TINY_MACHINES)


def test_split_falls_back_to_the_positive_quantile() -> None:
    """The IMS shape: every positive at the end of the run still trains."""
    stamps = pd.Series(pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC"))
    labels = pd.Series([0] * 80 + [1] * 20)
    cut = split_timestamp(stamps, labels, test_size=0.2)
    assert cut == stamps.iloc[96]
    assert int(labels[stamps < cut].sum()) == 16

    spread = pd.Series([1 if index % 10 == 0 else 0 for index in range(100)])
    plain = split_timestamp(stamps, spread, test_size=0.2)
    assert plain == stamps.iloc[80]

    with pytest.raises(ValueError, match="no positive rows"):
        split_timestamp(stamps, pd.Series([0] * 100), test_size=0.2)


def test_warmup_prefix_is_dropped_and_interior_nans_are_refused() -> None:
    names = list(feature_names(TINY_PLANT))
    frame = pd.DataFrame(
        {
            "machine_id": ["ai4i-01"] * 4,
            "dataset_ts": pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC"),
            **{name: [np.nan, np.nan, 1.0, 2.0] for name in names},
        }
    )
    kept, dropped = drop_warmup_rows(frame, TINY_PLANT)
    assert dropped == 2
    assert len(kept) == 2

    frame.loc[3, names[0]] = np.nan
    with pytest.raises(ValueError, match="after the warm-up prefix"):
        drop_warmup_rows(frame, TINY_PLANT)

    empty = frame.iloc[:2]
    kept_none, dropped_none = drop_warmup_rows(empty, TINY_PLANT)
    assert len(kept_none) == 0
    assert dropped_none == 2


def test_matrix_rejects_a_frame_that_is_not_a_feature_matrix() -> None:
    frame = load_tiny_frame()
    with pytest.raises(ValueError, match="missing"):
        matrix_from_frame(TINY_PLANT, frame.drop(columns=[feature_names(TINY_PLANT)[0]]))
    with pytest.raises(ValueError, match="no 'machine_failure' column"):
        matrix_from_frame(TINY_PLANT, frame.drop(columns=[label_column(TINY_PLANT)]))


def test_split_that_leaves_one_side_empty_is_refused() -> None:
    """A single-instant frame cannot be split, and says so."""
    frame = load_tiny_frame().copy()
    frame["dataset_ts"] = frame["dataset_ts"].iloc[0]
    with pytest.raises(ValueError, match="left one side empty"):
        matrix_from_frame(TINY_PLANT, frame)


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The same matrix trained twice into two independent registries."""
    matrix = tiny_matrix()
    roots = (tmp_path_factory.mktemp("run-a"), tmp_path_factory.mktemp("run-b"))
    for root in roots:
        train.train_plant(TINY_PLANT, matrix=matrix, root=root, data_sha256="0" * 64)
    return roots


def test_lgbm_booster_bytes_are_identical(two_runs: tuple[Path, Path]) -> None:
    first, second = (registry.resolve_version(root, TINY_PLANT, "lgbm") for root in two_runs)
    assert first.model_path.read_bytes() == second.model_path.read_bytes()


def test_manifests_agree_apart_from_the_wall_clock(two_runs: tuple[Path, Path]) -> None:
    first, second = (
        registry.resolve_version(root, TINY_PLANT, "lgbm").manifest().to_dict() for root in two_runs
    )
    assert first.pop("trained_at")
    second.pop("trained_at")
    assert first == second
    assert first["train_run_id"].startswith("trn_")


def test_both_families_predict_identically_across_runs(two_runs: tuple[Path, Path]) -> None:
    matrix = tiny_matrix()
    for family in ("lgbm", "rf"):
        predictions = []
        for root in two_runs:
            entry = registry.resolve_version(root, TINY_PLANT, family)
            model = registry.load_model(entry)
            predictions.append(
                model.predict(matrix.x_test)
                if family == "lgbm"
                else model.predict_proba(
                    pd.DataFrame(matrix.x_test, columns=list(matrix.feature_names))
                )[:, 1]
            )
        np.testing.assert_array_equal(predictions[0], predictions[1])


def test_importances_and_backgrounds_are_identical(two_runs: tuple[Path, Path]) -> None:
    matrix = tiny_matrix()
    settings = get_settings()
    runs = [
        train.train_plant(
            TINY_PLANT, matrix=matrix, root=root, settings=settings, data_sha256="0" * 64
        )
        for root in two_runs
    ]
    for left, right in zip(runs[0], runs[1], strict=True):
        assert left.importances == right.importances
        # summary(), not to_dict(): the reliability curve carries NaN for empty
        # bins and NaN never equals itself.
        assert left.metrics.summary() == right.metrics.summary()
    first, second = (
        registry.load_background(registry.resolve_version(root, TINY_PLANT, "lgbm"))
        for root in two_runs
    )
    pd.testing.assert_frame_equal(first, second)


def test_hyperparameters_come_from_settings() -> None:
    settings = get_settings()
    params = train.hyperparameters("lgbm", settings)
    assert params["n_estimators"] == settings.model.lgbm.n_estimators
    assert params["seed"] == settings.model.seed
    assert params["subsample_freq"] == train.LGBM_SUBSAMPLE_FREQ
    assert train.hyperparameters("rf", settings)["max_depth"] == settings.model.rf.max_depth


def test_train_run_id_changes_with_every_input() -> None:
    base = {
        "seed": 42,
        "plant_id": TINY_PLANT,
        "data_sha256": "0" * 64,
        "code_sha": "abc",
        "feature_digest": "def",
        "params": {"n_estimators": 400},
    }
    identifier = train.train_run_id(**base)
    assert identifier.startswith("trn_")
    assert train.train_run_id(**{**base, "seed": 43}) != identifier
    assert train.train_run_id(**{**base, "data_sha256": "1" * 64}) != identifier
    assert train.train_run_id(**{**base, "params": {"n_estimators": 401}}) != identifier
    assert train.train_run_id(**base) == identifier


def test_a_model_with_no_splits_gets_zero_importances() -> None:
    """Guard on the normalisation: no division by zero on a degenerate fit."""

    class _Stub:
        feature_importances_ = np.zeros(3)

    assert train.feature_importances("lgbm", _Stub(), ["a", "b", "c"]) == {
        "a": 0.0,
        "b": 0.0,
        "c": 0.0,
    }
