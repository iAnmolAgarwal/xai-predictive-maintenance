"""GBM vs RF for the same alert: two explanations, one disagreement table.

``ModelComparison`` (§3.4.3) is built from two explanations of the **same
snapshot** by two explainers that differ only in the fitted model — same
background size, same interventional perturbation, same probability space (R3)
— so every difference in the table is a difference between the two algorithms
and not between two explainer configurations.

* ``probability_delta`` is ``lgbm.probability - rf.probability``.
* ``rank_correlation`` is Spearman's rho over the **union of both top-k sets**,
  ranking each model's ``|shap|`` for those features. Union rather than
  intersection because a feature one model ranks first and the other ignores is
  exactly the disagreement the view exists to show.
* ``disagreements`` carries every union feature with ``delta = lgbm_shap -
  rf_shap`` and each model's rank inside its own top-k (``None`` when the
  feature did not make that model's cut, per §3.4.2).
* ``commentary`` is one backend-generated line naming the feature the two models
  disagree most about, in the display names the rest of the UI uses. The
  frontend composes no prose (§3.4.3).
"""

from __future__ import annotations

from typing import Final

import numpy as np
from scipy import stats

from xpm.contracts.common import PlantId
from xpm.contracts.rest import Explanation, FeatureDisagreement, ModelComparison
from xpm.explain.explainer import Explainer, FeatureSnapshot, QuantileFn, ShapRow
from xpm.explain.templates import format_number
from xpm.features.registry import feature_index, feature_meta

__all__ = ["compare", "compare_alert"]

#: Spearman's rho is undefined when either ranking is constant (one model gives
#: every union feature the same magnitude, or the union holds a single feature).
#: Reporting 0.0 — "no measurable rank agreement" — is the honest reading, and
#: keeps ``rank_correlation`` finite as the contract requires.
UNDEFINED_CORRELATION: Final[float] = 0.0

#: Above this rho the commentary calls the ranking agreement strong. It is a
#: wording choice inside one generated sentence, not a threshold any behaviour
#: depends on.
_STRONG_AGREEMENT: Final[float] = 0.5

#: Probability difference, in points, below which the commentary calls the two
#: scores "the same call". Also wording only.
_SAME_CALL_POINTS: Final[float] = 1.0

_PERCENT: Final[float] = 100.0


def compare(
    alert_id: str,
    *,
    lgbm: Explanation,
    rf: Explanation,
    lgbm_row: ShapRow,
    rf_row: ShapRow,
) -> ModelComparison:
    """Assemble the comparison from two finished explanations and their rows."""
    if lgbm.model_kind != "lgbm" or rf.model_kind != "rf":
        raise ValueError("compare() takes the lgbm explanation first and the rf one second")
    if lgbm.machine_id != rf.machine_id or lgbm.dataset_ts != rf.dataset_ts:
        raise ValueError("the two explanations describe different rows")

    plant_id = _plant_of(lgbm_row, rf_row)
    index = feature_index(plant_id)
    metas = feature_meta(plant_id)
    lgbm_ranks = {item.feature: position for position, item in enumerate(lgbm.contributions)}
    rf_ranks = {item.feature: position for position, item in enumerate(rf.contributions)}
    union = list(dict.fromkeys([*lgbm_ranks, *rf_ranks]))

    disagreements = sorted(
        (
            FeatureDisagreement(
                feature=feature,
                display_name=metas[feature].display_name,
                lgbm_shap=float(lgbm_row.values[index[feature]]),
                rf_shap=float(rf_row.values[index[feature]]),
                delta=float(lgbm_row.values[index[feature]] - rf_row.values[index[feature]]),
                lgbm_rank=lgbm_ranks.get(feature),
                rf_rank=rf_ranks.get(feature),
            )
            for feature in union
        ),
        key=lambda item: abs(item.delta),
        reverse=True,
    )
    correlation = rank_correlation(disagreements)
    return ModelComparison(
        alert_id=alert_id,
        lgbm=lgbm,
        rf=rf,
        probability_delta=lgbm.probability - rf.probability,
        rank_correlation=correlation,
        disagreements=disagreements,
        commentary=commentary(lgbm, rf, disagreements, correlation),
    )


def compare_alert(
    alert_id: str,
    snapshot: FeatureSnapshot,
    *,
    lgbm: Explainer,
    rf: Explainer,
    machine_display_name: str,
    quantile: QuantileFn | None = None,
) -> ModelComparison:
    """Explain one snapshot with both families and compare the results."""
    rows: dict[str, ShapRow] = {}
    explanations: dict[str, Explanation] = {}
    for explainer in (lgbm, rf):
        row = explainer.shap_row(snapshot)
        rows[explainer.family] = row
        explanations[explainer.family] = explainer.explain(
            snapshot,
            alert_id=alert_id,
            machine_display_name=machine_display_name,
            quantile=quantile,
            row=row,
        )
    return compare(
        alert_id,
        lgbm=explanations["lgbm"],
        rf=explanations["rf"],
        lgbm_row=rows["lgbm"],
        rf_row=rows["rf"],
    )


def rank_correlation(disagreements: list[FeatureDisagreement]) -> float:
    """Spearman's rho of ``|shap|`` over the union, or 0.0 when undefined."""
    if len(disagreements) < 2:
        return UNDEFINED_CORRELATION
    left = np.abs(np.asarray([item.lgbm_shap for item in disagreements], dtype=np.float64))
    right = np.abs(np.asarray([item.rf_shap for item in disagreements], dtype=np.float64))
    if left.std() == 0.0 or right.std() == 0.0:
        return UNDEFINED_CORRELATION
    rho = float(stats.spearmanr(left, right).statistic)
    return UNDEFINED_CORRELATION if not np.isfinite(rho) else rho


def commentary(
    lgbm: Explanation,
    rf: Explanation,
    disagreements: list[FeatureDisagreement],
    correlation: float,
) -> str:
    """One line naming where the two models actually differ."""
    points = (lgbm.probability - rf.probability) * _PERCENT
    if abs(points) < _SAME_CALL_POINTS:
        verdict = (
            f"LightGBM and RandomForest score this row the same, at "
            f"{lgbm.probability:.0%} and {rf.probability:.0%}"
        )
    else:
        higher, lower = ("LightGBM", "RandomForest") if points > 0 else ("RandomForest", "LightGBM")
        verdict = (
            f"{higher} scores this row {format_number(abs(points))} points higher than "
            f"{lower} ({lgbm.probability:.0%} vs {rf.probability:.0%})"
        )
    agreement = (
        f"they rank the same features similarly (rho {correlation:.2f})"
        if correlation >= _STRONG_AGREEMENT
        else f"they rank the features differently (rho {correlation:.2f})"
    )
    if not disagreements:
        return f"{verdict}, and neither model attributed the row to any feature."
    worst = disagreements[0]
    return (
        f"{verdict}; {agreement}, and they differ most on {worst.display_name}, "
        f"which LightGBM {_pushes(worst.lgbm_shap)} and RandomForest "
        f"{_pushes(worst.rf_shap)}."
    )


def _pushes(shap_value: float) -> str:
    """ "pushes risk up by 0.12" / "pushes risk down by 0.01" / "leaves it flat"."""
    if shap_value == 0.0:
        return "leaves it flat"
    direction = "up" if shap_value > 0.0 else "down"
    return f"pushes risk {direction} by {format_number(abs(shap_value))}"


def _plant_of(lgbm_row: ShapRow, rf_row: ShapRow) -> PlantId:
    """The plant both SHAP rows describe."""
    if lgbm_row.plant_id != rf_row.plant_id:
        raise ValueError("the two explanations describe different plants")
    return lgbm_row.plant_id
