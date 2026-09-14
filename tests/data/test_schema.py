"""The processed-parquet schema, its validator and the channel tables."""

from __future__ import annotations

from itertools import pairwise
from typing import cast

import numpy as np
import pandas as pd
import pytest

from xpm.data import schema


def _valid_ai4i_frame() -> pd.DataFrame:
    rows = []
    for tick in range(3):
        for machine in range(1, 3):
            rows.append(
                {
                    "machine_id": schema.machine_id("ai4i", machine),
                    "dataset_ts": schema.AI4I_DATASET_START
                    + pd.Timedelta(minutes=schema.AI4I_ROW_MINUTES * tick),
                    **dict.fromkeys(schema.AI4I_CHANNELS, 1.0),
                    schema.AI4I_LABEL: 0,
                    **dict.fromkeys(schema.AI4I_FAILURE_MODES, 0),
                    "variant": "M",
                    "source_row": tick * 2 + machine,
                }
            )
    return schema.order_columns(pd.DataFrame.from_records(rows), schema.AI4I_SCHEMA)


def test_channel_tables_match_backend_md_section_3_1() -> None:
    assert schema.AI4I_CHANNELS == (
        "air_temp",
        "process_temp",
        "temp_diff",
        "rot_speed",
        "torque",
        "power",
        "tool_wear",
    )
    assert schema.IMS_CHANNELS == (
        "vibration_0k5khz",
        "vibration_1khz",
        "vibration_2khz",
        "vibration_3khz",
        "vibration_5khz",
        "vibration_8khz",
        "vibration_rms",
        "vibration_kurtosis",
        "vibration_crest",
    )
    assert schema.AI4I_CHANNEL_UNITS["torque"] == "N·m"
    for band in schema.IMS_BAND_CHANNELS:
        assert schema.IMS_CHANNEL_UNITS[band] == "g²/Hz"
    assert schema.IMS_CHANNEL_UNITS["vibration_rms"] == "g"
    assert schema.IMS_CHANNEL_UNITS["vibration_kurtosis"] == ""
    assert schema.IMS_CHANNEL_UNITS["vibration_crest"] == ""


def test_band_edges_are_contiguous_and_centre_3khz_on_the_assignment_band() -> None:
    edges = list(schema.IMS_BANDS_HZ.values())
    assert edges[0][0] == 0.0
    assert edges[-1][1] == 10000.0
    for (_, high), (low, _) in pairwise(edges):
        assert high == low
    assert schema.IMS_BANDS_HZ["vibration_3khz"] == (2500.0, 3500.0)


def test_channels_and_units_resolve_per_plant() -> None:
    assert schema.channels_for("ai4i") == schema.AI4I_CHANNELS
    assert schema.channels_for("ims") == schema.IMS_CHANNELS
    assert schema.units_for("ai4i")["air_temp"] == "K"
    assert schema.units_for("ims")["vibration_rms"] == "g"


def test_machine_ids_are_zero_padded_and_one_based() -> None:
    assert schema.machine_id("ai4i", 3) == "ai4i-03"
    assert schema.machine_id("ims", 12) == "ims-12"
    with pytest.raises(ValueError, match="1-based"):
        schema.machine_id("ims", 0)


def test_schema_exposes_names_channels_and_dtypes() -> None:
    table = schema.schema_for("ims")
    assert table.channel_names == schema.IMS_CHANNELS
    assert table.names[:2] == ("machine_id", "dataset_ts")
    assert table.dtypes["dataset_ts"] == "datetime64[ns, UTC]"
    assert table.names[-2:] == ("bearing", "source_file")


def test_a_valid_frame_passes() -> None:
    frame = _valid_ai4i_frame()
    assert schema.validate(frame, schema.AI4I_SCHEMA) is frame


def test_a_missing_channel_is_rejected() -> None:
    frame = _valid_ai4i_frame().drop(columns=["torque"])
    with pytest.raises(schema.SchemaError, match="missing columns"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_an_unexpected_column_is_rejected() -> None:
    frame = _valid_ai4i_frame()
    frame["surprise"] = 1.0
    with pytest.raises(schema.SchemaError, match="unexpected columns"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_a_reordered_frame_is_rejected() -> None:
    frame = _valid_ai4i_frame()
    reordered = frame.loc[:, list(reversed(frame.columns))]
    with pytest.raises(schema.SchemaError, match="column order"):
        schema.validate(reordered, schema.AI4I_SCHEMA)


def test_a_wrong_dtype_is_rejected() -> None:
    frame = _valid_ai4i_frame()
    frame["torque"] = frame["torque"].astype("float32")
    with pytest.raises(schema.SchemaError, match="dtype 'float32'"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_a_nan_in_a_channel_is_rejected() -> None:
    frame = _valid_ai4i_frame()
    frame.loc[0, "torque"] = np.nan
    with pytest.raises(schema.SchemaError, match="contains NaN"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_non_monotonic_dataset_time_is_rejected() -> None:
    frame = _valid_ai4i_frame()
    frame = frame.sort_values(["machine_id", "dataset_ts"]).reset_index(drop=True)
    third = cast(pd.Timestamp, frame.loc[2, "dataset_ts"])
    frame.loc[0, "dataset_ts"] = third + pd.Timedelta(minutes=5)
    with pytest.raises(schema.SchemaError, match="not strictly increasing"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_duplicate_dataset_time_is_rejected() -> None:
    frame = _valid_ai4i_frame().sort_values(["machine_id", "dataset_ts"]).reset_index(drop=True)
    frame.loc[1, "dataset_ts"] = frame.loc[0, "dataset_ts"]
    with pytest.raises(schema.SchemaError, match="not strictly increasing"):
        schema.validate(frame, schema.AI4I_SCHEMA)


def test_order_columns_requires_every_column() -> None:
    frame = _valid_ai4i_frame().drop(columns=["variant"])
    with pytest.raises(schema.SchemaError, match="missing columns"):
        schema.order_columns(frame, schema.AI4I_SCHEMA)


def test_channel_frame_selects_the_ordered_channels() -> None:
    channels = schema.channel_frame(_valid_ai4i_frame(), "ai4i")
    assert list(channels.columns) == list(schema.AI4I_CHANNELS)
