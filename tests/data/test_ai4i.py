"""AI4I normalisation, derived channels and the 12-machine round-robin mapping."""

from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from pytest import MonkeyPatch

from xpm.data import ai4i, loader
from xpm.data.schema import (
    AI4I_CHANNELS,
    AI4I_DATASET_START,
    AI4I_FAILURE_MODES,
    AI4I_LABEL,
    AI4I_MACHINE_COUNT,
    AI4I_ROW_MINUTES,
    AI4I_SCHEMA,
    SchemaError,
    validate,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "data"


@pytest.fixture(scope="module")
def raw_head() -> pd.DataFrame:
    """The first 200 source rows, exactly as ``ucimlrepo`` delivers them."""
    return pd.read_parquet(FIXTURES / "ai4i_head_200.parquet", engine="pyarrow")


@pytest.fixture(scope="module")
def processed(raw_head: pd.DataFrame) -> pd.DataFrame:
    return ai4i.build_frame(raw_head)


def test_columns_are_the_canonical_schema(processed: pd.DataFrame) -> None:
    assert list(processed.columns) == list(AI4I_SCHEMA.names)
    validate(processed, AI4I_SCHEMA)


def test_rows_are_dealt_round_robin_into_twelve_machines(processed: pd.DataFrame) -> None:
    assert len(processed) == 200
    assert processed["machine_id"].nunique() == AI4I_MACHINE_COUNT
    for source_row, machine in zip(processed["source_row"], processed["machine_id"], strict=True):
        expected = f"ai4i-{((int(source_row) - 1) % AI4I_MACHINE_COUNT) + 1:02d}"
        assert machine == expected


def test_dataset_time_advances_five_minutes_per_row_per_machine(
    processed: pd.DataFrame,
) -> None:
    step = pd.Timedelta(minutes=AI4I_ROW_MINUTES)
    for _, group in processed.groupby("machine_id"):
        series = group["dataset_ts"].reset_index(drop=True)
        assert series.iloc[0] == AI4I_DATASET_START
        assert bool((series.diff().dropna() == step).all())


def test_derived_channels_match_hand_computed_rows(
    raw_head: pd.DataFrame, processed: pd.DataFrame
) -> None:
    source = ai4i.normalise_columns(raw_head).set_index("udi")
    by_row = processed.set_index("source_row")
    for udi in (1, 2, 50, 137, 200):
        row = source.loc[udi]
        got = by_row.loc[udi]
        assert got["temp_diff"] == pytest.approx(
            float(row["process_temp"]) - float(row["air_temp"])
        )
        assert got["power"] == pytest.approx(
            float(row["torque"]) * float(row["rot_speed"]) * 2.0 * math.pi / 60.0
        )


def test_labels_pass_through_unchanged(raw_head: pd.DataFrame, processed: pd.DataFrame) -> None:
    source = ai4i.normalise_columns(raw_head).set_index("udi")
    by_row = processed.set_index("source_row")
    for label in (AI4I_LABEL, *AI4I_FAILURE_MODES):
        assert set(processed[label].unique()) <= {0, 1}
        for udi in source.index:
            assert int(by_row.loc[udi, label]) == int(source.loc[udi, label])


def test_variant_travels_with_the_row(processed: pd.DataFrame) -> None:
    assert set(processed["variant"].unique()) <= {"L", "M", "H"}


def test_unit_decorated_headers_are_normalised() -> None:
    decorated = pd.DataFrame(
        {
            "UDI": [1],
            "Product ID": ["M14860"],
            "Type": ["M"],
            "Air temperature [K]": [298.1],
            "Process temperature [K]": [308.6],
            "Rotational speed [rpm]": [1551],
            "Torque [Nm]": [42.8],
            "Tool wear [min]": [0],
            "Machine failure": [0],
            "TWF": [0],
            "HDF": [0],
            "PWF": [0],
            "OSF": [0],
            "RNF": [0],
        }
    )
    normalised = ai4i.normalise_columns(decorated)
    assert set(AI4I_CHANNELS) - {"temp_diff", "power"} <= set(normalised.columns)


def test_a_source_missing_a_column_is_rejected(raw_head: pd.DataFrame) -> None:
    with pytest.raises(SchemaError, match="missing columns"):
        ai4i.normalise_columns(raw_head.drop(columns=["Torque"]))


def test_process_falls_back_to_the_uci_zip(
    raw_head: pd.DataFrame, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    buffer = io.BytesIO()
    raw_head.to_csv(buffer, index=False)
    with zipfile.ZipFile(cache / "ai4i2020.zip", "w") as zf:
        zf.writestr("ai4i2020.csv", buffer.getvalue())
    monkeypatch.setenv("XPM_DATA_CACHE", str(cache))
    monkeypatch.setenv(loader.DATA_ROOT_ENV_VAR, str(tmp_path / "data"))
    monkeypatch.setattr(
        ai4i, "_fetch_via_ucimlrepo", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    monkeypatch.setattr(ai4i, "EXPECTED_ROWS", 200)

    manifest = ai4i.process()

    assert manifest.source_url == ai4i.AI4I_URL
    assert manifest.rows == 200
    assert loader.load_manifest("ai4i")["parquet_sha256"] == manifest.parquet_sha256
    assert (tmp_path / "data" / "raw" / ai4i.RAW_PARQUET_NAME).is_file()


def test_process_refuses_a_truncated_source(
    raw_head: pd.DataFrame, tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(ai4i, "_fetch_via_ucimlrepo", lambda: raw_head)
    monkeypatch.setenv(loader.DATA_ROOT_ENV_VAR, str(tmp_path / "data"))
    with pytest.raises(SchemaError, match="expected 10000 rows, got 200"):
        ai4i.process()


def test_zip_without_a_csv_member_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "ai4i2020.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "no data here")
    with pytest.raises(SchemaError, match="no CSV member"):
        ai4i._read_csv_from_zip(archive)
