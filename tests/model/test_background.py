"""The frozen SHAP background (R3, ADR-003).

A NaN anywhere in an interventional background silently turns every SHAP value
into NaN, and a background that is not drawn from the training mix moves the
waterfall's base value away from the model's own prior. Both are asserted here,
along with the determinism that makes two trainings explain an alert the same
way.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xpm.config import get_settings
from xpm.features.registry import feature_names
from xpm.model.background import sample_background, select_background_rows

from . import TINY_PLANT, tiny_matrix


def test_background_is_deterministic_and_nan_free() -> None:
    matrix = tiny_matrix()
    first = sample_background(matrix)
    second = sample_background(matrix)
    pd.testing.assert_frame_equal(first, second)
    assert not first.isna().to_numpy().any()
    assert np.isfinite(first.to_numpy()).all()
    assert list(first.columns) == list(feature_names(TINY_PLANT))


def test_background_size_is_min_of_the_setting_and_the_split() -> None:
    """``min(model.shap.background_rows, n_train_rows)``.

    The tiny fixture has fewer than 256 training rows, so the whole split is the
    background; the real plants take the configured 256.
    """
    matrix = tiny_matrix()
    configured = get_settings().model.shap.background_rows
    assert len(sample_background(matrix)) == min(configured, matrix.n_train_rows)

    labels = np.array([0] * 900 + [1] * 100, dtype=np.int64)
    picked = select_background_rows(labels, rows=configured, seed=1337)
    assert picked.shape == (configured,)
    assert np.array_equal(picked, np.sort(picked))
    assert len(set(picked.tolist())) == configured


def test_background_preserves_the_class_mix() -> None:
    """Representativeness: the sampled prevalence tracks the training one."""
    labels = np.array([0] * 900 + [1] * 100, dtype=np.int64)
    rows = 256
    picked = select_background_rows(labels, rows=rows, seed=1337)
    prevalence = float(labels[picked].mean())
    assert prevalence == pytest.approx(labels.mean(), abs=0.01)

    rare = np.array([0] * 999 + [1], dtype=np.int64)
    picked_rare = select_background_rows(rare, rows=rows, seed=1337)
    assert int(rare[picked_rare].sum()) == 1, "the positive class must survive rounding"

    absent = np.zeros(1000, dtype=np.int64)
    picked_absent = select_background_rows(absent, rows=rows, seed=1337)
    assert picked_absent.shape == (rows,)

    # Allocation is proportional in both directions: with a 1 % negative class
    # the background keeps roughly 1 % negatives, and never zero of them.
    mostly_positive = np.array([1] * 990 + [0] * 10, dtype=np.int64)
    picked_positive = select_background_rows(mostly_positive, rows=rows, seed=1337)
    negatives = int((mostly_positive[picked_positive] == 0).sum())
    assert 0 < negatives <= 10
    assert float(mostly_positive[picked_positive].mean()) == pytest.approx(
        mostly_positive.mean(), abs=0.01
    )


def test_a_single_class_split_still_yields_a_background() -> None:
    """The clamp: there are no negatives to allocate, so every row is positive."""
    labels = np.ones(500, dtype=np.int64)
    picked = select_background_rows(labels, rows=64, seed=1337)
    assert picked.shape == (64,)
    assert int(labels[picked].sum()) == 64


def test_sampling_depends_on_the_seed() -> None:
    labels = np.array([0] * 900 + [1] * 100, dtype=np.int64)
    first = select_background_rows(labels, rows=64, seed=1337)
    assert np.array_equal(first, select_background_rows(labels, rows=64, seed=1337))
    assert not np.array_equal(first, select_background_rows(labels, rows=64, seed=7))


def test_degenerate_requests_are_refused() -> None:
    labels = np.array([0, 1], dtype=np.int64)
    with pytest.raises(ValueError, match="background_rows must be >= 1"):
        select_background_rows(labels, rows=0, seed=1)
    with pytest.raises(ValueError, match="empty training split"):
        select_background_rows(np.array([], dtype=np.int64), rows=8, seed=1)


def test_a_non_finite_training_row_is_refused() -> None:
    """The warm-up drop should make this impossible; if it ever does not, the
    background must fail loudly rather than poison every SHAP value."""
    matrix = tiny_matrix()
    matrix.x_train[0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        sample_background(matrix)
