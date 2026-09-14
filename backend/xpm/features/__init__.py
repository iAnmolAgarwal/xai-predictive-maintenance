"""The rolling-window feature engine (backend.md §1, §3.1).

One implementation, two entry points:

* :class:`~xpm.features.online.OnlineFeatureEngine` consumes
  :class:`~xpm.contracts.mqtt.TelemetryMessage` objects one at a time and is
  what the live pipeline scores;
* :func:`~xpm.features.offline.build_feature_frame` replays the committed
  processed parquet and is what ``T-MODEL`` trains on.

Both drive the same per-machine state, so the training matrix and the served
vector agree bit for bit.

:mod:`~xpm.features.registry` owns the ordered feature names
(``<channel>_<stat>_<window>``) and the per-feature metadata the explanation
templater needs.
"""

from __future__ import annotations

from xpm.features.offline import build_feature_frame, build_vectors
from xpm.features.online import FeatureVector, MachineFeatureState, OnlineFeatureEngine
from xpm.features.percentiles import PercentileBank
from xpm.features.registry import (
    FeatureMeta,
    Framing,
    feature_index,
    feature_meta,
    feature_meta_payload,
    feature_names,
    n_features,
)
from xpm.features.streak import StreakBank
from xpm.features.windows import RollingWindowBuffer, WindowSpec, window_specs

__all__ = [
    "FeatureMeta",
    "FeatureVector",
    "Framing",
    "MachineFeatureState",
    "OnlineFeatureEngine",
    "PercentileBank",
    "RollingWindowBuffer",
    "StreakBank",
    "WindowSpec",
    "build_feature_frame",
    "build_vectors",
    "feature_index",
    "feature_meta",
    "feature_meta_payload",
    "feature_names",
    "n_features",
    "window_specs",
]
