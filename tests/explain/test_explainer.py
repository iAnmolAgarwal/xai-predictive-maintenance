"""The SHAP arithmetic: additivity, truncation, and the stored goldens.

The load-bearing assertions are the two the dashboard draws against:
``output_value == probability`` exactly (R16), and
``base_value + Σ contributions + other_contributions_shap == output_value`` to
1e-6 (R3, §3.4.3), which is what makes the waterfall close on the number the
user reads.

The **untruncated** sum is asserted separately and more loosely, against
:data:`~xpm.explain.explainer.FULL_VECTOR_ADDITIVITY_ATOL`. That is a measured
property of ``shap``'s interventional implementation, not of this package — see
the ``xpm.explain.explainer`` module docstring for the numbers behind it — and
the contract invariant above holds regardless because the roll-up bar carries
the residual.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from xpm.contracts.rest import Explanation
from xpm.contracts.settings import Settings
from xpm.explain import explainer as explainer_module
from xpm.explain.explainer import (
    ADDITIVITY_ATOL,
    FULL_VECTOR_ADDITIVITY_ATOL,
    Explainer,
    FeatureSnapshot,
    bands_for,
    clear_explainer_cache,
    explanation_id_for,
    get_explainer,
)
from xpm.model.dataset import build_training_matrix

from . import FIXTURE_DIR, GOLDEN_ALERT_ID, GOLDEN_RTOL, tiny_matrix

#: How many held-out rows the additivity assertions cover (backend.md §4).
ADDITIVITY_ROWS = 20

#: ``output_value == probability`` is exact by construction; §3.4.3 asks the API
#: to assert it to 1e-9 before responding, and so does this suite.
OUTPUT_VALUE_ATOL = 1e-9


def _explanation(explainer: Explainer, snapshot: FeatureSnapshot) -> Explanation:
    return explainer.explain(
        snapshot,
        alert_id=GOLDEN_ALERT_ID,
        machine_display_name="Machine 1",
    )


@pytest.mark.parametrize("plant_id", ["ai4i", "ims"])
@pytest.mark.parametrize("family", ["lgbm", "rf"])
def test_waterfall_closes_on_the_probability(
    plant_id: str, family: str, trained_root: Path, request: pytest.FixtureRequest
) -> None:
    """Both models, both plants, 20 held-out rows (backend.md §4)."""
    explainer = Explainer.load(plant_id, family, root=trained_root)  # type: ignore[arg-type]
    matrix = tiny_matrix(plant_id)  # type: ignore[arg-type]
    rows = matrix.x_test[:ADDITIVITY_ROWS]
    assert rows.shape[0] == ADDITIVITY_ROWS

    for shap_row in explainer.shap_rows(rows):
        assert shap_row.additivity_error <= FULL_VECTOR_ADDITIVITY_ATOL

    for position in range(rows.shape[0]):
        snapshot = FeatureSnapshot(
            plant_id=explainer.plant_id,
            machine_id=f"{plant_id}-01",
            dataset_ts=matrix.test_index["dataset_ts"].iloc[position].to_pydatetime(),
            values=tuple(float(value) for value in rows[position]),
            percentiles=(None,) * explainer.n_features,
            streak_hours=(None,) * explainer.n_features,
        )
        explanation = _explanation(explainer, snapshot)
        assert explanation.output_value == pytest.approx(
            explanation.probability, abs=OUTPUT_VALUE_ATOL
        )
        closure = (
            explanation.base_value
            + sum(item.shap for item in explanation.contributions)
            + explanation.other_contributions_shap
        )
        assert closure == pytest.approx(explanation.output_value, abs=ADDITIVITY_ATOL)
        assert explanation.shap_space == "probability"


def test_base_value_is_the_background_mean_probability(ai4i_lgbm: Explainer) -> None:
    """The waterfall's origin is the background's own mean prediction (R3)."""
    background = ai4i_lgbm.background.to_numpy(dtype=np.float64)
    assert ai4i_lgbm.base_value == pytest.approx(
        float(ai4i_lgbm.probabilities(background).mean()), abs=1e-9
    )


def test_top_k_and_min_abs_shap_truncation(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, settings: Settings
) -> None:
    explanation = _explanation(ai4i_lgbm, ai4i_snapshot)
    budget = settings.explanation
    assert 0 < len(explanation.contributions) <= budget.top_k
    magnitudes = [abs(item.shap) for item in explanation.contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert all(magnitude >= budget.min_abs_shap for magnitude in magnitudes)
    assert explanation.n_features == ai4i_lgbm.n_features
    assert explanation.other_contributions_count == ai4i_lgbm.n_features - len(
        explanation.contributions
    )


def test_a_tiny_contribution_folds_into_the_roll_up(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, settings: Settings
) -> None:
    """``explanation.min_abs_shap`` decides, not a literal in this package."""
    row = ai4i_lgbm.shap_row(ai4i_snapshot)
    ranked = np.argsort(-np.abs(row.values), kind="stable")[: settings.explanation.top_k]
    below = [
        int(position)
        for position in ranked
        if abs(float(row.values[position])) < settings.explanation.min_abs_shap
    ]
    drawn = {item.feature for item in _explanation(ai4i_lgbm, ai4i_snapshot).contributions}
    for position in below:
        assert ai4i_lgbm.feature_names[position] not in drawn


def test_explanation_carries_the_caveat_and_the_ids(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, settings: Settings
) -> None:
    explanation = _explanation(ai4i_lgbm, ai4i_snapshot)
    assert explanation.caveat == settings.explanation.caveat
    assert explanation.alert_id == GOLDEN_ALERT_ID
    assert explanation.machine_id == ai4i_snapshot.machine_id
    assert explanation.model_kind == "lgbm"
    assert explanation.model_id == ai4i_lgbm.model_id
    assert explanation.explanation_id == explanation_id_for(
        GOLDEN_ALERT_ID, ai4i_lgbm.model_id, "lgbm"
    )


def test_explanation_ids_are_deterministic_and_model_specific() -> None:
    """R5: same inputs, same id; and the two families never collide."""
    first = explanation_id_for(GOLDEN_ALERT_ID, "lgbm@1.0.0", "lgbm")
    assert first == explanation_id_for(GOLDEN_ALERT_ID, "lgbm@1.0.0", "lgbm")
    assert first != explanation_id_for(GOLDEN_ALERT_ID, "rf@1.0.0", "rf")
    assert first.startswith("exp_")
    assert len(first) == len("exp_") + 16


def test_a_feature_with_no_reading_is_drawn_without_a_level(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot
) -> None:
    """A warm-up NaN still gets a bar, and its clause claims no value."""
    row = ai4i_lgbm.shap_row(ai4i_snapshot)
    top = int(np.argmax(np.abs(row.values)))
    values = list(ai4i_snapshot.values)
    values[top] = math.nan
    blanked = FeatureSnapshot(
        plant_id=ai4i_snapshot.plant_id,
        machine_id=ai4i_snapshot.machine_id,
        dataset_ts=ai4i_snapshot.dataset_ts,
        values=tuple(values),
        percentiles=ai4i_snapshot.percentiles,
        streak_hours=ai4i_snapshot.streak_hours,
        bands=ai4i_snapshot.bands,
    )
    explanation = _explanation(ai4i_lgbm, blanked)
    blank = [item for item in explanation.contributions if item.value is None]
    assert blank, "the NaN feature should still carry a contribution"
    for item in blank:
        assert "no reading" in item.sentence
        assert item.feature not in {span.feature for span in explanation.sentence_spans}


def test_snapshot_rejects_a_vector_of_the_wrong_length(ai4i_snapshot: FeatureSnapshot) -> None:
    with pytest.raises(ValueError, match="feature vector has"):
        FeatureSnapshot(
            plant_id="ai4i",
            machine_id="ai4i-01",
            dataset_ts=ai4i_snapshot.dataset_ts,
            values=(0.0,),
            percentiles=ai4i_snapshot.percentiles,
            streak_hours=ai4i_snapshot.streak_hours,
        )


def test_snapshot_rejects_an_unknown_feature(ai4i_snapshot: FeatureSnapshot) -> None:
    with pytest.raises(KeyError, match="not a feature of plant"):
        ai4i_snapshot.value_of("no_such_feature")


def test_explainer_refuses_a_snapshot_from_another_plant(
    ai4i_lgbm: Explainer, ims_snapshot: FeatureSnapshot
) -> None:
    with pytest.raises(ValueError, match="this explainer serves"):
        ai4i_lgbm.shap_row(ims_snapshot)


def test_overrides_drop_the_percentile_and_the_streak(ai4i_snapshot: FeatureSnapshot) -> None:
    feature = "torque"
    moved = ai4i_snapshot.with_overrides({feature: 42.0})
    assert moved.value_of(feature) == 42.0
    assert moved.percentile_of(feature) is None
    assert moved.streak_of(feature) is None
    assert moved.bands == ai4i_snapshot.bands
    assert ai4i_snapshot.value_of(feature) != 42.0


def test_bands_come_from_history_and_skip_warm_up_features(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot
) -> None:
    """A band is a real pair of history quantiles or it is absent."""
    assert ai4i_snapshot.bands, "the replayed machine should have warmed up"
    for floor, ceiling in ai4i_snapshot.bands.values():
        assert floor <= ceiling
    assert bands_for("ai4i", ai4i_lgbm.feature_names, None) == {}
    assert bands_for("ai4i", ("torque",), lambda _feature, _level: None) == {}


def test_get_explainer_caches_one_object_per_plant_and_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API builds four explainers at startup, never one per request."""
    built: list[tuple[str, str]] = []

    def fake_load(plant_id: str, family: str = "lgbm", **_: object) -> object:
        built.append((plant_id, family))
        return object()

    monkeypatch.setattr(explainer_module.Explainer, "load", staticmethod(fake_load))
    clear_explainer_cache()
    try:
        first = get_explainer("ai4i", "lgbm")
        assert get_explainer("ai4i", "lgbm") is first
        assert get_explainer("ai4i", "rf") is not first
        assert built == [("ai4i", "lgbm"), ("ai4i", "rf")]
    finally:
        clear_explainer_cache()


def test_explainer_refuses_an_oversized_background(
    trained_root: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """A background bigger than ``model.shap.background_rows`` is a config drift."""
    from xpm.model import registry

    entry = registry.resolve_version(trained_root, "ims", "lgbm")
    shrunken = settings.model_copy(
        update={
            "model": settings.model.model_copy(
                update={"shap": settings.model.shap.model_copy(update={"background_rows": 1})}
            )
        }
    )
    with pytest.raises(ValueError, match="background has"):
        Explainer(entry, shrunken)


@pytest.mark.parametrize("plant_id", ["ai4i", "ims"])
def test_golden_explanation(
    plant_id: str,
    request: pytest.FixtureRequest,
    update_goldens: bool,
) -> None:
    """The full ``Explanation`` for one alert-level row per plant.

    Regenerate with ``uv run pytest tests/explain --update-goldens``.
    """
    explainer: Explainer = request.getfixturevalue(f"{plant_id}_lgbm")
    snapshot: FeatureSnapshot = request.getfixturevalue(f"{plant_id}_snapshot")
    explanation = explainer.explain(
        snapshot,
        alert_id=GOLDEN_ALERT_ID,
        machine_display_name="Bearing 1" if plant_id == "ims" else "Milling Machine 1",
    )
    produced = json.loads(explanation.model_dump_json())
    path = FIXTURE_DIR / f"golden_explanation_{plant_id}.json"

    if update_goldens:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(produced, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return

    expected = json.loads(path.read_text(encoding="utf-8"))
    _assert_matches(expected, produced, path=plant_id)
    assert Explanation.model_validate(expected) == explanation


def _assert_matches(expected: Any, produced: Any, *, path: str) -> None:
    """Compare exactly, except for floats, which are compared to a tolerance.

    Strings, ordering and structure are the contract; the last bits of a SHAP
    float are the LightGBM build's business.
    """
    if isinstance(expected, dict):
        assert isinstance(produced, dict)
        assert expected.keys() == produced.keys(), path
        for key in expected:
            _assert_matches(expected[key], produced[key], path=f"{path}.{key}")
        return
    if isinstance(expected, list):
        assert isinstance(produced, list)
        assert len(expected) == len(produced), path
        for position, (left, right) in enumerate(zip(expected, produced, strict=True)):
            _assert_matches(left, right, path=f"{path}[{position}]")
        return
    if isinstance(expected, float) and isinstance(produced, float):
        assert produced == pytest.approx(expected, rel=GOLDEN_RTOL, abs=GOLDEN_RTOL), path
        return
    assert produced == expected, path


def test_the_tiny_matrices_are_real_held_out_data() -> None:
    """The fixtures are slices of the committed data, not synthetic rows."""
    matrix = build_training_matrix("ims")
    assert matrix.n_test_rows > 0
    assert matrix.feature_names == tiny_matrix("ims").feature_names


def test_background_medians_are_the_ablation_target(ai4i_lgbm: Explainer) -> None:
    """``scripts/faithfulness.py`` ablates to these values."""
    medians = ai4i_lgbm.background_medians()
    assert medians.shape == (ai4i_lgbm.n_features,)
    expected = ai4i_lgbm.background.to_numpy(dtype=np.float64)
    assert medians == pytest.approx(np.median(expected, axis=0))


def test_a_matrix_of_the_wrong_width_is_refused(ai4i_lgbm: Explainer) -> None:
    with pytest.raises(ValueError, match="features per row"):
        ai4i_lgbm.probabilities(np.zeros((1, 3)))


def test_bands_are_read_lazily_for_the_drawn_features_only(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, settings: Settings
) -> None:
    """The pipeline may pass the live quantile query instead of pre-materialising."""
    asked: list[str] = []

    def quantile(feature: str, level: float) -> float | None:
        asked.append(feature)
        return 0.0 if level < 50.0 else 1.0

    bare = FeatureSnapshot(
        plant_id=ai4i_snapshot.plant_id,
        machine_id=ai4i_snapshot.machine_id,
        dataset_ts=ai4i_snapshot.dataset_ts,
        values=ai4i_snapshot.values,
        percentiles=ai4i_snapshot.percentiles,
        streak_hours=ai4i_snapshot.streak_hours,
    )
    explanation = ai4i_lgbm.explain(
        bare,
        alert_id=GOLDEN_ALERT_ID,
        machine_display_name="Milling Machine 1",
        quantile=quantile,
    )
    drawn = {item.feature for item in explanation.contributions}
    assert set(asked) == drawn
    assert len(asked) == 2 * len(drawn) <= 2 * settings.explanation.top_k


def test_a_snapshot_that_already_carries_bands_is_not_re_queried(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot
) -> None:
    def explode(feature: str, level: float) -> float | None:
        raise AssertionError(f"{feature} at {level} should have come from the snapshot")

    ai4i_lgbm.explain(
        ai4i_snapshot,
        alert_id=GOLDEN_ALERT_ID,
        machine_display_name="Milling Machine 1",
        quantile=explode,
    )
