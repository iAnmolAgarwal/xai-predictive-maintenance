"""What-if: the 40 ms compute budget, the override allow-list, the gradients.

The definition-of-done number is the **client-side** round trip (< 150 ms);
backend.md §4 budgets 40 ms of it for one server-side recompute *including*
gradients, leaving the rest for HTTP and serialisation. That budget is asserted
here with ``pytest-benchmark`` against a real trained model.
"""

from __future__ import annotations

import math
from importlib import import_module

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from xpm.contracts.rest import Explanation, WhatIfRequest, WhatIfResponse
from xpm.contracts.settings import Settings
from xpm.explain.explainer import Explainer, FeatureSnapshot
from xpm.explain.whatif import (
    GRADIENT_STEP_FRACTION,
    MINIMUM_STEP,
    WhatIfError,
    gradients,
    overridable_features,
    step_for,
    whatif,
)
from xpm.features.registry import feature_meta

#: ``xpm.explain`` re-exports the ``whatif`` *function*, which shadows the
#: submodule of the same name on the package, so the module is fetched by path.
whatif_module = import_module("xpm.explain.whatif")

#: backend.md §4's server-side budget for one what-if recompute, in seconds.
WHATIF_BUDGET_SECONDS = 0.040

ALERT_ID = "alt_0123456789abcdef"


@pytest.fixture(scope="module")
def baseline(ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot) -> Explanation:
    return ai4i_lgbm.explain(
        ai4i_snapshot, alert_id=ALERT_ID, machine_display_name="Milling Machine 1"
    )


def _request(baseline: Explanation, settings: Settings, **overrides: float) -> WhatIfRequest:
    if not overrides:
        feature = overridable_features(baseline, settings)[0]
        overrides = {feature: 0.0}
    return WhatIfRequest(alert_id=ALERT_ID, model="lgbm", overrides=overrides)


def _whatif(
    explainer: Explainer,
    snapshot: FeatureSnapshot,
    baseline: Explanation,
    settings: Settings,
    **overrides: float,
) -> WhatIfResponse:
    return whatif(
        _request(baseline, settings, **overrides),
        explainer=explainer,
        snapshot=snapshot,
        baseline=baseline,
        machine_display_name="Milling Machine 1",
        settings=settings,
    )


def test_one_recompute_including_gradients_fits_the_budget(
    benchmark: BenchmarkFixture,
    ai4i_lgbm: Explainer,
    ai4i_snapshot: FeatureSnapshot,
    baseline: Explanation,
    settings: Settings,
) -> None:
    response = benchmark(_whatif, ai4i_lgbm, ai4i_snapshot, baseline, settings)
    assert response.gradients
    assert benchmark.stats.stats.mean < WHATIF_BUDGET_SECONDS


def test_the_response_is_provisional_and_carries_the_contract_fields(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    response = _whatif(ai4i_lgbm, ai4i_snapshot, baseline, settings)
    assert response.provisional is True
    assert response.shap_space == "probability"
    assert response.alert_id == ALERT_ID
    assert response.model_id == ai4i_lgbm.model_id
    assert response.model_kind == "lgbm"
    assert response.caveat == settings.explanation.caveat
    assert response.baseline_probability == baseline.probability
    assert response.output_value == pytest.approx(response.probability, abs=1e-9)
    closure = (
        response.base_value
        + sum(item.shap for item in response.contributions)
        + response.other_contributions_shap
    )
    assert closure == pytest.approx(response.output_value, abs=1e-6)
    assert response.compute_ms > 0.0
    assert response.n_features == ai4i_lgbm.n_features


def test_the_sentence_is_regenerated_for_the_hypothetical_row(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    feature = overridable_features(baseline, settings)[0]
    current = ai4i_snapshot.value_of(feature)
    assert current is not None
    response = _whatif(
        ai4i_lgbm, ai4i_snapshot, baseline, settings, **{feature: current * 0.1 - 1.0}
    )
    assert response.sentence != baseline.sentence
    for span in response.sentence_spans:
        assert response.sentence[span.start : span.end]


def test_an_overridden_feature_reports_no_percentile(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    """A hypothetical value has no rank in the machine's real history."""
    feature = overridable_features(baseline, settings)[0]
    response = _whatif(ai4i_lgbm, ai4i_snapshot, baseline, settings, **{feature: 1.0})
    moved = [item for item in response.contributions if item.feature == feature]
    for item in moved:
        assert item.percentile is None
        assert item.consecutive_hours is None
        assert item.value == 1.0


def test_only_the_top_k_whatif_sliders_are_offered(
    baseline: Explanation, settings: Settings
) -> None:
    allowed = overridable_features(baseline, settings)
    assert len(allowed) == min(
        settings.explanation.top_k_whatif,
        len(baseline.contributions),
    )
    assert allowed == tuple(
        item.feature for item in baseline.contributions[: settings.explanation.top_k_whatif]
    )


def test_a_feature_outside_the_sliders_is_refused(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    allowed = set(overridable_features(baseline, settings))
    outsider = next(name for name in ai4i_lgbm.feature_names if name not in allowed)
    with pytest.raises(WhatIfError, match="what-if sliders") as raised:
        _whatif(ai4i_lgbm, ai4i_snapshot, baseline, settings, **{outsider: 1.0})
    assert raised.value.feature == outsider
    assert set(raised.value.allowed) == allowed


def test_an_unknown_feature_is_refused(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    with pytest.raises(WhatIfError, match="not a feature of plant"):
        _whatif(ai4i_lgbm, ai4i_snapshot, baseline, settings, no_such_feature=1.0)


def test_a_non_finite_override_is_refused(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    feature = overridable_features(baseline, settings)[0]
    with pytest.raises(WhatIfError, match="non-finite"):
        _whatif(ai4i_lgbm, ai4i_snapshot, baseline, settings, **{feature: math.inf})


def test_a_request_for_the_other_family_is_refused(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    request = WhatIfRequest(alert_id=ALERT_ID, model="rf", overrides={})
    with pytest.raises(ValueError, match="this explainer serves"):
        whatif(
            request,
            explainer=ai4i_lgbm,
            snapshot=ai4i_snapshot,
            baseline=baseline,
            machine_display_name="Milling Machine 1",
            settings=settings,
        )


def test_gradients_cover_every_slider_and_are_finite(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, baseline: Explanation, settings: Settings
) -> None:
    allowed = overridable_features(baseline, settings)
    slopes = gradients(ai4i_lgbm, ai4i_snapshot, allowed)
    assert set(slopes) == set(allowed)
    assert all(math.isfinite(value) for value in slopes.values())
    assert gradients(ai4i_lgbm, ai4i_snapshot, ()) == {}


def test_the_gradient_step_is_one_percent_of_the_nominal_span(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot
) -> None:
    meta = feature_meta("ai4i")["torque"]
    expected = GRADIENT_STEP_FRACTION * (meta.nominal_max - meta.nominal_min)
    assert step_for(ai4i_lgbm, ai4i_snapshot, "torque") == pytest.approx(expected)


def test_a_degenerate_nominal_span_falls_back_to_the_background_spread(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documented fallback: no nominal span, so the background's own spread."""
    metas = dict(feature_meta("ai4i"))
    flattened = metas["torque"]
    metas["torque"] = type(flattened)(
        **{
            **{field: getattr(flattened, field) for field in flattened.__slots__},
            "nominal_min": 1.0,
            "nominal_max": 1.0,
        }
    )
    monkeypatch.setattr(whatif_module, "feature_meta", lambda _plant: metas)
    spread = float(ai4i_lgbm.background.loc[:, "torque"].std(ddof=0))
    assert step_for(ai4i_lgbm, ai4i_snapshot, "torque") == pytest.approx(
        GRADIENT_STEP_FRACTION * spread
    )


def test_a_constant_feature_falls_back_to_the_minimum_step(
    ai4i_lgbm: Explainer, ai4i_snapshot: FeatureSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    metas = dict(feature_meta("ai4i"))
    flattened = metas["torque"]
    metas["torque"] = type(flattened)(
        **{
            **{field: getattr(flattened, field) for field in flattened.__slots__},
            "nominal_min": 1.0,
            "nominal_max": 1.0,
        }
    )
    monkeypatch.setattr(whatif_module, "feature_meta", lambda _plant: metas)
    frame = ai4i_lgbm.background.copy()
    frame.loc[:, "torque"] = 3.0
    monkeypatch.setattr(type(ai4i_lgbm), "background", property(lambda _self: frame))
    assert step_for(ai4i_lgbm, ai4i_snapshot, "torque") == MINIMUM_STEP
