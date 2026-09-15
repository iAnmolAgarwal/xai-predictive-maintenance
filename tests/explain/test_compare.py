"""GBM vs RF on one alert: the table, the correlation and the commentary.

backend.md §4 asks for a non-empty ``commentary``, a finite ``rank_correlation``
and ``FeatureDisagreement`` rows whose ``delta == lgbm_shap - rf_shap``. The
commentary is additionally asserted to be *feature-aware* — it names the feature
the two models actually differ on — because a generic line would satisfy
"non-empty" while telling the user nothing.
"""

from __future__ import annotations

import math

import pytest

from xpm.contracts.rest import FeatureDisagreement, ModelComparison
from xpm.explain.compare import (
    UNDEFINED_CORRELATION,
    commentary,
    compare,
    compare_alert,
    rank_correlation,
)
from xpm.explain.explainer import Explainer, FeatureSnapshot

ALERT_ID = "alt_0123456789abcdef"


@pytest.fixture(scope="module")
def comparison(
    ai4i_lgbm: Explainer, ai4i_rf: Explainer, ai4i_snapshot: FeatureSnapshot
) -> ModelComparison:
    return compare_alert(
        ALERT_ID,
        ai4i_snapshot,
        lgbm=ai4i_lgbm,
        rf=ai4i_rf,
        machine_display_name="Milling Machine 1",
    )


def test_both_sides_explain_the_same_row(comparison: ModelComparison) -> None:
    assert comparison.alert_id == ALERT_ID
    assert comparison.lgbm.model_kind == "lgbm"
    assert comparison.rf.model_kind == "rf"
    assert comparison.lgbm.machine_id == comparison.rf.machine_id
    assert comparison.lgbm.dataset_ts == comparison.rf.dataset_ts
    assert comparison.lgbm.explanation_id != comparison.rf.explanation_id


def test_probability_delta_is_lgbm_minus_rf(comparison: ModelComparison) -> None:
    assert comparison.probability_delta == pytest.approx(
        comparison.lgbm.probability - comparison.rf.probability
    )


def test_every_disagreement_row_is_consistent(comparison: ModelComparison) -> None:
    assert comparison.disagreements
    union = {item.feature for item in comparison.lgbm.contributions} | {
        item.feature for item in comparison.rf.contributions
    }
    assert {row.feature for row in comparison.disagreements} == union
    for row in comparison.disagreements:
        assert isinstance(row, FeatureDisagreement)
        assert row.delta == pytest.approx(row.lgbm_shap - row.rf_shap)
        assert row.display_name
        for rank, explanation in ((row.lgbm_rank, comparison.lgbm), (row.rf_rank, comparison.rf)):
            names = [item.feature for item in explanation.contributions]
            if rank is None:
                assert row.feature not in names
            else:
                assert names[rank] == row.feature


def test_disagreements_are_ordered_by_absolute_delta(comparison: ModelComparison) -> None:
    deltas = [abs(row.delta) for row in comparison.disagreements]
    assert deltas == sorted(deltas, reverse=True)


def test_rank_correlation_is_finite(comparison: ModelComparison) -> None:
    assert math.isfinite(comparison.rank_correlation)
    assert -1.0 <= comparison.rank_correlation <= 1.0


def test_commentary_names_the_feature_the_models_differ_on(
    comparison: ModelComparison,
) -> None:
    worst = comparison.disagreements[0]
    assert comparison.commentary
    assert worst.display_name in comparison.commentary
    assert "LightGBM" in comparison.commentary and "RandomForest" in comparison.commentary
    assert f"{comparison.rank_correlation:.2f}" in comparison.commentary
    assert comparison.commentary.endswith(".")


def test_commentary_reports_which_model_scored_higher(comparison: ModelComparison) -> None:
    higher = "LightGBM" if comparison.probability_delta > 0 else "RandomForest"
    if abs(comparison.probability_delta) * 100.0 >= 1.0:
        assert comparison.commentary.startswith(higher)
    else:
        assert "the same" in comparison.commentary


def test_compare_rejects_the_families_in_the_wrong_order(
    comparison: ModelComparison,
    ai4i_lgbm: Explainer,
    ai4i_rf: Explainer,
    ai4i_snapshot: FeatureSnapshot,
) -> None:
    lgbm_row = ai4i_lgbm.shap_row(ai4i_snapshot)
    rf_row = ai4i_rf.shap_row(ai4i_snapshot)
    with pytest.raises(ValueError, match="lgbm explanation first"):
        compare(
            ALERT_ID,
            lgbm=comparison.rf,
            rf=comparison.lgbm,
            lgbm_row=rf_row,
            rf_row=lgbm_row,
        )


def test_compare_rejects_two_different_rows(
    comparison: ModelComparison,
    ai4i_lgbm: Explainer,
    ai4i_rf: Explainer,
    ai4i_snapshot: FeatureSnapshot,
) -> None:
    other = comparison.rf.model_copy(update={"machine_id": "ai4i-09"})
    with pytest.raises(ValueError, match="different rows"):
        compare(
            ALERT_ID,
            lgbm=comparison.lgbm,
            rf=other,
            lgbm_row=ai4i_lgbm.shap_row(ai4i_snapshot),
            rf_row=ai4i_rf.shap_row(ai4i_snapshot),
        )


def test_compare_rejects_two_different_plants(
    comparison: ModelComparison,
    ai4i_lgbm: Explainer,
    ai4i_rf: Explainer,
    ims_lgbm: Explainer,
    ai4i_snapshot: FeatureSnapshot,
    ims_snapshot: FeatureSnapshot,
) -> None:
    with pytest.raises(ValueError, match="different plants"):
        compare(
            ALERT_ID,
            lgbm=comparison.lgbm,
            rf=comparison.rf,
            lgbm_row=ims_lgbm.shap_row(ims_snapshot),
            rf_row=ai4i_rf.shap_row(ai4i_snapshot),
        )


def _row(feature: str, lgbm: float, rf: float) -> FeatureDisagreement:
    return FeatureDisagreement(
        feature=feature,
        display_name=feature,
        lgbm_shap=lgbm,
        rf_shap=rf,
        delta=lgbm - rf,
        lgbm_rank=0,
        rf_rank=0,
    )


def test_rank_correlation_is_zero_when_it_is_undefined() -> None:
    """A single feature, or a flat ranking, has no measurable rho."""
    assert rank_correlation([_row("a", 0.2, 0.1)]) == UNDEFINED_CORRELATION
    flat = [_row("a", 0.2, 0.1), _row("b", 0.2, 0.3)]
    assert rank_correlation(flat) == UNDEFINED_CORRELATION


def test_rank_correlation_is_one_for_identical_rankings() -> None:
    rows = [_row("a", 0.3, 0.6), _row("b", 0.2, 0.4), _row("c", 0.1, 0.2)]
    assert rank_correlation(rows) == pytest.approx(1.0)


def test_the_two_explanations_keep_their_own_probabilities(
    comparison: ModelComparison,
) -> None:
    """R16: one probability per model, and each waterfall closes on its own."""
    for explanation in (comparison.lgbm, comparison.rf):
        closure = (
            explanation.base_value
            + sum(item.shap for item in explanation.contributions)
            + explanation.other_contributions_shap
        )
        assert closure == pytest.approx(explanation.output_value, abs=1e-6)
        assert explanation.output_value == pytest.approx(explanation.probability, abs=1e-9)


def test_commentary_when_both_models_agree_on_the_score(comparison: ModelComparison) -> None:
    levelled = comparison.rf.model_copy(
        update={
            "probability": comparison.lgbm.probability,
            "output_value": comparison.lgbm.probability,
        }
    )
    line = commentary(comparison.lgbm, levelled, list(comparison.disagreements), 0.9)
    assert "score this row the same" in line


def test_commentary_with_no_contributions_says_so(comparison: ModelComparison) -> None:
    line = commentary(comparison.lgbm, comparison.rf, [], 0.0)
    assert line.endswith("neither model attributed the row to any feature.")


def test_commentary_reports_a_flat_contribution_as_flat(comparison: ModelComparison) -> None:
    line = commentary(
        comparison.lgbm,
        comparison.rf,
        [_row("torque", 0.5, 0.0)],
        0.1,
    )
    assert "leaves it flat" in line
    assert "pushes risk up by 0.5" in line
