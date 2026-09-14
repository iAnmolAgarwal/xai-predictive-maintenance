"""The batch feature path: the committed parquet in, a training matrix out.

``T-MODEL`` builds its windowed training matrix from
:func:`build_feature_frame`, so this module decides what the model is fitted on
and therefore what every SHAP value in the dashboard is attributed to. It shares
:class:`~xpm.features.online.MachineFeatureState` with the streaming path
verbatim — this module only decides the *order rows are fed in* — which is why
``tests/features/test_online_offline_parity.py`` can assert bit equality rather
than a tolerance, and why a model trained here cannot drift from the vectors it
is served.

Rows are grouped by ``machine_id`` and replayed in dataset-time order, exactly
as the replay publisher emits them (§3.2), so each machine's windows,
percentiles and streaks see the same history in the same order in both paths.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from xpm.contracts.common import PlantId
from xpm.contracts.settings import Settings
from xpm.data import loader
from xpm.data.schema import schema_for
from xpm.features.online import FeatureVector, OnlineFeatureEngine
from xpm.features.registry import feature_names

__all__ = ["build_feature_frame", "build_vectors", "label_columns"]


def label_columns(plant_id: PlantId) -> tuple[str, ...]:
    """The processed-parquet columns that are labels or provenance, not channels.

    Everything a training script needs to carry alongside the feature matrix:
    ``machine_failure`` and its five failure modes for ``ai4i``,
    ``failure_imminent`` for ``ims``, plus the per-row provenance columns.
    """
    schema = schema_for(plant_id)
    channels = set(schema.channel_names)
    return tuple(
        name
        for name in schema.names
        if name not in channels and name not in {"machine_id", "dataset_ts"}
    )


def _machine_frames(
    frame: pd.DataFrame, machines: Sequence[str] | None
) -> Iterable[tuple[str, pd.DataFrame]]:
    selected = frame if machines is None else frame[frame["machine_id"].isin(list(machines))]
    for machine_id, group in selected.groupby("machine_id", sort=True):
        yield str(machine_id), group.sort_values("dataset_ts", kind="stable")


def build_vectors(
    plant_id: PlantId,
    machine_id: str,
    *,
    frame: pd.DataFrame | None = None,
    settings: Settings | None = None,
) -> list[FeatureVector]:
    """Every feature vector of one machine's history, oldest first.

    The golden fixtures and the parity test are generated from this; it returns
    the percentile and streak metadata that :func:`build_feature_frame` drops.
    """
    source = loader.load_plant(plant_id) if frame is None else frame
    engine = OnlineFeatureEngine(plant_id, settings)
    channels = list(schema_for(plant_id).channel_names)
    vectors: list[FeatureVector] = []
    for _, group in _machine_frames(source, [machine_id]):
        timestamps = group["dataset_ts"].to_list()
        block = group.loc[:, channels].to_numpy(dtype=np.float64)
        for position, moment in enumerate(timestamps):
            vectors.append(
                engine.update_row(
                    machine_id,
                    moment.to_pydatetime(),
                    dict(zip(channels, block[position].tolist(), strict=True)),
                )
            )
    if not vectors:
        raise KeyError(f"{plant_id}: no rows for machine {machine_id!r}")
    return vectors


def build_feature_frame(
    plant_id: PlantId,
    *,
    frame: pd.DataFrame | None = None,
    machines: Sequence[str] | None = None,
    with_labels: bool = True,
    settings: Settings | None = None,
) -> pd.DataFrame:
    """The windowed training matrix for ``plant_id``.

    Columns are ``machine_id``, ``dataset_ts``, then
    :func:`~xpm.features.registry.feature_names` in registry order — identical
    to the vector :class:`~xpm.features.online.OnlineFeatureEngine` emits — then,
    when ``with_labels`` is set, the label and provenance columns of the
    processed parquet. A feature that is not yet computable is ``NaN``, which is
    LightGBM's native missing value and pandas' ``null``.
    """
    source = loader.load_plant(plant_id) if frame is None else frame
    names = feature_names(plant_id)
    channels = list(schema_for(plant_id).channel_names)
    labels = label_columns(plant_id) if with_labels else ()

    machine_column: list[str] = []
    timestamp_column: list[pd.Timestamp] = []
    rows: list[np.ndarray[tuple[int, ...], np.dtype[np.float64]]] = []
    label_rows: list[pd.DataFrame] = []

    for machine_id, group in _machine_frames(source, machines):
        engine = OnlineFeatureEngine(plant_id, settings)
        timestamps = group["dataset_ts"].to_list()
        block = group.loc[:, channels].to_numpy(dtype=np.float64)
        for position, moment in enumerate(timestamps):
            vector = engine.update_row(
                machine_id,
                moment.to_pydatetime(),
                dict(zip(channels, block[position].tolist(), strict=True)),
            )
            machine_column.append(machine_id)
            timestamp_column.append(moment)
            rows.append(vector.values)
        if labels:
            label_rows.append(group.loc[:, list(labels)].reset_index(drop=True))

    if not rows:
        raise KeyError(f"{plant_id}: no rows for machines {machines!r}")

    matrix = np.vstack(rows)
    built = pd.DataFrame(matrix, columns=list(names))
    built.insert(0, "dataset_ts", pd.to_datetime(pd.Series(timestamp_column), utc=True))
    built.insert(0, "machine_id", pd.Series(machine_column, dtype="string"))
    if labels:
        built = pd.concat([built, pd.concat(label_rows, ignore_index=True)], axis=1)
    return built
