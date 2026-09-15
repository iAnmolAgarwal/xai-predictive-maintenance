"""What-if: move a slider, recompute the probability, the bars and the sentence.

``WhatIfRequest`` in, ``WhatIfResponse`` out (§3.4.3), on the **same explainer
object** the alert's stored explanation came from (R3), so the hypothetical
waterfall is comparable to the real one bar for bar.

Three rules:

* **Overrides are restricted to the sliders the panel offers** — the top
  ``explanation.top_k_whatif`` features of the baseline explanation. Anything
  else raises :class:`WhatIfError`, which the API maps to 422; the panel cannot
  offer a slider the server would refuse, and a crafted request cannot drive the
  model with an arbitrary feature.
* **The sentence is regenerated, and marked provisional.** It describes a
  hypothetical row, so an overridden feature keeps its new value but loses its
  percentile rank and its streak: the machine's history contains no such
  observation (see :meth:`FeatureSnapshot.with_overrides`).
* **``gradients`` are a central finite difference** on the served probability,
  ``(p(x+h) - p(x-h)) / 2h``, one pair of evaluations per overridable feature,
  which the client uses to approximate the curve between round trips (R7).

Step size, per §3.4.3, is ``0.01 * (nominal_max - nominal_min)`` of the
feature's source channel. Two documented fallbacks: a channel whose nominal
bounds are degenerate (``nominal_max == nominal_min``) uses the same fraction of
the feature's **background standard deviation**, and a feature that is constant
across the background too falls back to :data:`MINIMUM_STEP`, so a gradient is
always a finite number and never a division by zero.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Final

import numpy as np

from xpm.contracts.rest import Explanation, WhatIfRequest, WhatIfResponse
from xpm.contracts.settings import Settings
from xpm.explain import narrative
from xpm.explain.explainer import Explainer, FeatureSnapshot, QuantileFn
from xpm.features.registry import feature_index, feature_meta
from xpm.features.stats import Float64Array

__all__ = [
    "GRADIENT_STEP_FRACTION",
    "MINIMUM_STEP",
    "WhatIfError",
    "gradients",
    "overridable_features",
    "step_for",
    "whatif",
]

#: §3.4.3's step size: 1 % of the source channel's nominal span. It is a
#: numerical differentiation parameter, not a user-facing threshold, which is
#: why it lives here and not in ``settings.yaml``.
GRADIENT_STEP_FRACTION: Final[float] = 0.01

#: Last-resort step for a feature with no nominal span and no background
#: spread. Small enough to stay local, large enough to survive float64.
MINIMUM_STEP: Final[float] = 1e-6

#: Milliseconds per second, for ``compute_ms``.
_MS_PER_SECOND: Final[float] = 1000.0


class WhatIfError(ValueError):
    """A what-if request the server refuses. The API answers 422.

    Carries the offending feature and the sliders that *were* on offer, so the
    error body can tell a client exactly what to send instead.
    """

    def __init__(self, message: str, *, feature: str, allowed: tuple[str, ...]) -> None:
        super().__init__(message)
        self.feature = feature
        self.allowed = allowed


def overridable_features(explanation: Explanation, settings: Settings) -> tuple[str, ...]:
    """The sliders the panel may offer: the baseline's top ``top_k_whatif``."""
    return tuple(
        item.feature for item in explanation.contributions[: settings.explanation.top_k_whatif]
    )


def whatif(
    request: WhatIfRequest,
    *,
    explainer: Explainer,
    snapshot: FeatureSnapshot,
    baseline: Explanation,
    machine_display_name: str,
    settings: Settings,
    quantile: QuantileFn | None = None,
) -> WhatIfResponse:
    """Recompute probability, SHAP, sentence and gradients for one slider move."""
    started = time.perf_counter()
    if request.model != explainer.family:
        raise ValueError(
            f"request asks for {request.model!r}, this explainer serves {explainer.family!r}"
        )
    allowed = overridable_features(baseline, settings)
    _validate(request.overrides, allowed, snapshot)

    moved = snapshot.with_overrides(request.overrides)
    row = explainer.shap_row(moved)
    contributions, tail_shap, tail_count = explainer.contributions(moved, row, quantile=quantile)
    sentence, spans = narrative.compose(
        machine_display_name, row.probability, contributions, settings
    )
    slopes = gradients(explainer, moved, allowed)
    return WhatIfResponse(
        alert_id=request.alert_id,
        model_id=explainer.model_id,
        model_kind=explainer.family,
        shap_space="probability",
        baseline_probability=baseline.probability,
        probability=row.probability,
        base_value=row.base_value,
        output_value=row.probability,
        contributions=contributions,
        other_contributions_shap=tail_shap,
        other_contributions_count=tail_count,
        n_features=explainer.n_features,
        sentence=sentence,
        sentence_spans=spans,
        provisional=True,
        caveat=settings.explanation.caveat,
        gradients=slopes,
        compute_ms=(time.perf_counter() - started) * _MS_PER_SECOND,
    )


def gradients(
    explainer: Explainer,
    snapshot: FeatureSnapshot,
    features: tuple[str, ...],
) -> dict[str, float]:
    """``dp/dx`` at ``snapshot`` for each of ``features``, central difference.

    All ``2 * len(features)`` perturbed rows are scored in **one** model call:
    the per-call overhead dominates a ten-row batch, and the what-if budget is
    40 ms for the whole response.
    """
    if not features:
        return {}
    index = feature_index(snapshot.plant_id)
    base = snapshot.as_array()
    steps = [step_for(explainer, snapshot, feature) for feature in features]
    block = np.repeat(base[None, :], 2 * len(features), axis=0)
    for position, (feature, step) in enumerate(zip(features, steps, strict=True)):
        column = index[feature]
        block[2 * position, column] = base[column] + step
        block[2 * position + 1, column] = base[column] - step
    scored = explainer.probabilities(block)
    return {
        feature: float((scored[2 * position] - scored[2 * position + 1]) / (2.0 * step))
        for position, (feature, step) in enumerate(zip(features, steps, strict=True))
    }


def step_for(explainer: Explainer, snapshot: FeatureSnapshot, feature: str) -> float:
    """The finite-difference step for one feature (see the module docstring)."""
    meta = feature_meta(snapshot.plant_id)[feature]
    span = meta.nominal_max - meta.nominal_min
    if span > 0.0:
        return GRADIENT_STEP_FRACTION * span
    spread = _background_std(explainer, feature)
    if spread > 0.0:
        return GRADIENT_STEP_FRACTION * spread
    return MINIMUM_STEP


def _background_std(explainer: Explainer, feature: str) -> float:
    column: Float64Array = np.asarray(
        explainer.background.loc[:, feature].to_numpy(), dtype=np.float64
    )
    return float(np.std(column))


def _validate(
    overrides: Mapping[str, float], allowed: tuple[str, ...], snapshot: FeatureSnapshot
) -> None:
    known = feature_index(snapshot.plant_id)
    for feature, value in overrides.items():
        if feature not in known:
            raise WhatIfError(
                f"{feature!r} is not a feature of plant {snapshot.plant_id!r}",
                feature=feature,
                allowed=allowed,
            )
        if feature not in allowed:
            raise WhatIfError(
                f"{feature!r} is not one of this alert's what-if sliders",
                feature=feature,
                allowed=allowed,
            )
        if not np.isfinite(value):
            raise WhatIfError(
                f"{feature!r} was given a non-finite value",
                feature=feature,
                allowed=allowed,
            )
