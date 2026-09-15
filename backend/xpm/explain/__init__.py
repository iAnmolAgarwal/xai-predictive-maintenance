"""SHAP in probability space, the explanation templater and what-if (§1, §3.9).

The entry points downstream tasks use:

* :func:`~xpm.explain.explainer.get_explainer` — the cached
  ``shap.TreeExplainer`` for one ``(plant, family)``, built exactly as
  R3/ADR-003 specifies and shared by serving, what-if, model comparison and
  ``scripts/faithfulness.py``;
* :class:`~xpm.explain.explainer.FeatureSnapshot` — the pure-data feature vector
  an explanation is computed from, built from the feature engine's
  :class:`~xpm.features.online.FeatureVector` and persistable beside the alert so
  a later what-if recomputes against the row that actually fired;
* :meth:`~xpm.explain.explainer.Explainer.explain` — a contract
  :class:`~xpm.contracts.rest.Explanation`;
* :func:`~xpm.explain.whatif.whatif` — a contract
  :class:`~xpm.contracts.rest.WhatIfResponse`, raising
  :class:`~xpm.explain.whatif.WhatIfError` for an override the panel never
  offered (the API answers 422);
* :func:`~xpm.explain.compare.compare_alert` — a contract
  :class:`~xpm.contracts.rest.ModelComparison`;
* :func:`~xpm.explain.narrative.headline` — ``Alert.headline`` for the rail.

There is **no calibrator** in this package and nothing here imports
``sklearn.calibration``: the served model's own probability is the number every
bar sums to (R16, ADR-016).
"""

from __future__ import annotations

from xpm.explain.compare import compare, compare_alert
from xpm.explain.explainer import (
    ADDITIVITY_ATOL,
    FULL_VECTOR_ADDITIVITY_ATOL,
    Explainer,
    FeatureSnapshot,
    QuantileFn,
    ShapRow,
    bands_for,
    clear_explainer_cache,
    explanation_id_for,
    get_explainer,
)
from xpm.explain.framing import ClauseFacts, resolve_clause
from xpm.explain.narrative import compose, contribution, headline
from xpm.explain.templates import TEMPLATES
from xpm.explain.whatif import WhatIfError, gradients, overridable_features, whatif

__all__ = [
    "ADDITIVITY_ATOL",
    "FULL_VECTOR_ADDITIVITY_ATOL",
    "TEMPLATES",
    "ClauseFacts",
    "Explainer",
    "FeatureSnapshot",
    "QuantileFn",
    "ShapRow",
    "WhatIfError",
    "bands_for",
    "clear_explainer_cache",
    "compare",
    "compare_alert",
    "compose",
    "contribution",
    "explanation_id_for",
    "get_explainer",
    "gradients",
    "headline",
    "overridable_features",
    "resolve_clause",
    "whatif",
]
