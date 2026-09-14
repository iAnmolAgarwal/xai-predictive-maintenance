"""Canonical channel definitions and processed-parquet schemas.

The channel names, units and band edges here are transcribed verbatim from
``docs/plan/backend.md`` §3.1 (channel tables) and §3.2.3 (band edges, Welch
parameters, labelling horizon). ``xpm.contracts.channels`` is the user-facing
source of the same table for the API layer; this module is the dataset-side
copy that the preprocessing pipeline is built on, and a test in the feature
task reconciles the two.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

import pandas as pd

PlantId = Literal["ai4i", "ims"]

PLANT_IDS: Final[tuple[PlantId, ...]] = ("ai4i", "ims")

# --- AI4I (§3.1, 7 channels, canonical order) --------------------------------

AI4I_CHANNELS: Final[tuple[str, ...]] = (
    "air_temp",
    "process_temp",
    "temp_diff",
    "rot_speed",
    "torque",
    "power",
    "tool_wear",
)

AI4I_CHANNEL_UNITS: Final[Mapping[str, str]] = {
    "air_temp": "K",
    "process_temp": "K",
    "temp_diff": "K",
    "rot_speed": "rpm",
    "torque": "N·m",
    "power": "W",
    "tool_wear": "min",
}

AI4I_FAILURE_MODES: Final[tuple[str, ...]] = ("twf", "hdf", "pwf", "osf", "rnf")
"""Tool wear, heat dissipation, power, overstrain and random failure flags."""

AI4I_LABEL: Final[str] = "machine_failure"
AI4I_MACHINE_COUNT: Final[int] = 12
AI4I_ROW_MINUTES: Final[int] = 5
AI4I_DATASET_START: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")

# --- IMS (§3.1, 9 channels, canonical order) ---------------------------------

IMS_BAND_CHANNELS: Final[tuple[str, ...]] = (
    "vibration_0k5khz",
    "vibration_1khz",
    "vibration_2khz",
    "vibration_3khz",
    "vibration_5khz",
    "vibration_8khz",
)

IMS_SCALAR_CHANNELS: Final[tuple[str, ...]] = (
    "vibration_rms",
    "vibration_kurtosis",
    "vibration_crest",
)

IMS_CHANNELS: Final[tuple[str, ...]] = IMS_BAND_CHANNELS + IMS_SCALAR_CHANNELS

IMS_CHANNEL_UNITS: Final[Mapping[str, str]] = {
    **{name: "g²/Hz" for name in IMS_BAND_CHANNELS},
    "vibration_rms": "g",
    "vibration_kurtosis": "",
    "vibration_crest": "",
}

IMS_BANDS_HZ: Final[Mapping[str, tuple[float, float]]] = {
    "vibration_0k5khz": (0.0, 500.0),
    "vibration_1khz": (500.0, 1500.0),
    "vibration_2khz": (1500.0, 2500.0),
    "vibration_3khz": (2500.0, 3500.0),
    "vibration_5khz": (3500.0, 6000.0),
    "vibration_8khz": (6000.0, 10000.0),
}

IMS_LABEL: Final[str] = "failure_imminent"
IMS_BEARING_COUNT: Final[int] = 4
IMS_FAILING_BEARINGS: Final[tuple[int, ...]] = (1,)
"""Bearings that actually fail in test set 2 (§3.2.2)."""

IMS_LABEL_HORIZON_HOURS: Final[float] = 24.0
"""N from §3.2.3 / ADR-023: the last N hours before end-of-record are positive."""

IMS_SAMPLE_RATE_HZ: Final[float] = 20000.0
IMS_NPERSEG: Final[int] = 4096
IMS_OVERLAP: Final[float] = 0.5
IMS_WINDOW: Final[str] = "hann"
IMS_SNAPSHOT_ROWS: Final[int] = 20480
IMS_SNAPSHOT_MINUTES: Final[int] = 10
IMS_FILENAME_FORMAT: Final[str] = "%Y.%m.%d.%H.%M.%S"


def channels_for(plant: PlantId) -> tuple[str, ...]:
    """Canonical, ordered channel names for ``plant``."""
    return AI4I_CHANNELS if plant == "ai4i" else IMS_CHANNELS


def units_for(plant: PlantId) -> Mapping[str, str]:
    """Exact user-visible unit strings for ``plant``'s channels."""
    return AI4I_CHANNEL_UNITS if plant == "ai4i" else IMS_CHANNEL_UNITS


def machine_id(plant: PlantId, index: int) -> str:
    """``ims-01``-style identifier for a 1-based machine index (§3.1)."""
    if index < 1:
        raise ValueError(f"machine index is 1-based, got {index}")
    return f"{plant}-{index:02d}"


# --- Processed parquet schema ------------------------------------------------


class SchemaError(ValueError):
    """A DataFrame does not satisfy the processed-parquet schema."""


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column of a processed parquet file."""

    name: str
    dtype: str
    is_channel: bool = False


@dataclass(frozen=True, slots=True)
class TableSchema:
    """The full ordered column list of a processed parquet file."""

    plant: PlantId
    columns: tuple[ColumnSpec, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns if c.is_channel)

    @property
    def dtypes(self) -> Mapping[str, str]:
        return {c.name: c.dtype for c in self.columns}


_KEY_COLUMNS: Final[tuple[ColumnSpec, ...]] = (
    ColumnSpec("machine_id", "string"),
    ColumnSpec("dataset_ts", "datetime64[ns, UTC]"),
)

AI4I_SCHEMA: Final[TableSchema] = TableSchema(
    plant="ai4i",
    columns=(
        *_KEY_COLUMNS,
        *(ColumnSpec(name, "float64", is_channel=True) for name in AI4I_CHANNELS),
        ColumnSpec(AI4I_LABEL, "int8"),
        *(ColumnSpec(name, "int8") for name in AI4I_FAILURE_MODES),
        ColumnSpec("variant", "string"),
        ColumnSpec("source_row", "int32"),
    ),
)

IMS_SCHEMA: Final[TableSchema] = TableSchema(
    plant="ims",
    columns=(
        *_KEY_COLUMNS,
        *(ColumnSpec(name, "float64", is_channel=True) for name in IMS_CHANNELS),
        ColumnSpec(IMS_LABEL, "int8"),
        ColumnSpec("bearing", "int8"),
        ColumnSpec("source_file", "string"),
    ),
)

SCHEMAS: Final[Mapping[PlantId, TableSchema]] = {"ai4i": AI4I_SCHEMA, "ims": IMS_SCHEMA}


def schema_for(plant: PlantId) -> TableSchema:
    """The processed-parquet schema for ``plant``."""
    return SCHEMAS[plant]


def validate(frame: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Validate ``frame`` against ``schema`` and return it unchanged.

    Raises :class:`SchemaError` on a missing or extra column, a wrong dtype, a
    NaN in a channel column, or a ``dataset_ts`` series that is not strictly
    increasing within a machine.
    """
    expected = schema.names
    actual = tuple(frame.columns)
    missing = [name for name in expected if name not in actual]
    if missing:
        raise SchemaError(f"{schema.plant}: missing columns {missing}")
    extra = [name for name in actual if name not in expected]
    if extra:
        raise SchemaError(f"{schema.plant}: unexpected columns {extra}")
    if actual != expected:
        raise SchemaError(f"{schema.plant}: column order {list(actual)} != {list(expected)}")

    for spec in schema.columns:
        got = str(frame[spec.name].dtype)
        if got != spec.dtype:
            raise SchemaError(
                f"{schema.plant}.{spec.name}: dtype {got!r} != expected {spec.dtype!r}"
            )
        if spec.is_channel and bool(frame[spec.name].isna().any()):
            raise SchemaError(f"{schema.plant}.{spec.name}: contains NaN")

    _check_monotonic(frame, schema)
    return frame


def _check_monotonic(frame: pd.DataFrame, schema: TableSchema) -> None:
    for machine, group in frame.groupby("machine_id", sort=True):
        ts = group["dataset_ts"]
        if not bool(ts.is_monotonic_increasing) or bool(ts.duplicated().any()):
            raise SchemaError(f"{schema.plant}.{machine}: dataset_ts is not strictly increasing")


def order_columns(frame: pd.DataFrame, schema: TableSchema) -> pd.DataFrame:
    """Return ``frame`` with ``schema``'s columns in canonical order and dtype."""
    missing = [name for name in schema.names if name not in frame.columns]
    if missing:
        raise SchemaError(f"{schema.plant}: missing columns {missing}")
    ordered = frame.loc[:, list(schema.names)].copy()
    typed: pd.DataFrame = ordered.astype(dict(schema.dtypes))
    return typed


def channel_frame(frame: pd.DataFrame, plant: PlantId) -> pd.DataFrame:
    """Just the ordered channel columns of a processed frame."""
    names: Sequence[str] = schema_for(plant).channel_names
    return frame.loc[:, list(names)]
