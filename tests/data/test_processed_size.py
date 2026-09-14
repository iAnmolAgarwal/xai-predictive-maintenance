"""The committed processed tree: size budget (R2), manifests and loaders."""

from __future__ import annotations

import re

import pytest

from xpm.data import loader
from xpm.data.download import IMS_SHA256, IMS_URL, sha256_file
from xpm.data.schema import (
    AI4I_MACHINE_COUNT,
    IMS_BEARING_COUNT,
    PLANT_IDS,
    PlantId,
    schema_for,
)

SIZE_BUDGET_BYTES = 5 * 1024 * 1024


def test_committed_parquet_stays_inside_the_five_megabyte_budget() -> None:
    total = sum(loader.processed_parquet(plant).stat().st_size for plant in PLANT_IDS)
    assert total < SIZE_BUDGET_BYTES, f"processed parquet is {total} bytes"


@pytest.mark.parametrize("plant", PLANT_IDS)
def test_manifest_describes_the_committed_parquet(plant: PlantId) -> None:
    manifest = loader.load_manifest(plant)
    parquet = loader.processed_parquet(plant)
    assert manifest["plant"] == plant
    assert manifest["parquet_file"] == parquet.name
    assert manifest["parquet_sha256"] == sha256_file(parquet)
    assert manifest["parquet_bytes"] == parquet.stat().st_size
    assert manifest["columns"] == list(schema_for(plant).names)
    assert manifest["rows"] == len(loader.load_plant(plant))
    assert manifest["source_sha256"]
    assert manifest["source_url"]


def test_ims_manifest_pins_the_verified_mirror_and_parameters() -> None:
    manifest = loader.load_manifest("ims")
    assert manifest["source_url"] == IMS_URL
    assert manifest["source_sha256"] == IMS_SHA256
    parameters = manifest["parameters"]
    assert parameters["label_horizon_hours"] == 24.0
    assert parameters["band_edges_hz"]["vibration_3khz"] == [2500.0, 3500.0]
    assert parameters["welch"] == {"window": "hann", "nperseg": 4096, "overlap": 0.5}


def test_ai4i_manifest_records_the_simulation_mapping() -> None:
    parameters = loader.load_manifest("ai4i")["parameters"]
    assert parameters["machine_count"] == AI4I_MACHINE_COUNT
    assert parameters["row_minutes"] == 5
    assert parameters["mapping"] == "round_robin_by_udi"


def test_loaders_return_validated_frames_for_both_plants() -> None:
    ai4i_frame = loader.load_ai4i()
    ims_frame = loader.load_ims()
    assert len(ai4i_frame) == 10_000
    assert len(ims_frame) == 984 * IMS_BEARING_COUNT
    assert list(ai4i_frame.columns) == list(schema_for("ai4i").names)
    assert list(ims_frame.columns) == list(schema_for("ims").names)


def test_list_machines_matches_the_manifest() -> None:
    for plant in PLANT_IDS:
        assert loader.list_machines(plant) == loader.load_manifest(plant)["machines"]
    assert len(loader.list_machines("ai4i")) == AI4I_MACHINE_COUNT
    assert len(loader.list_machines("ims")) == IMS_BEARING_COUNT


def test_absent_processed_files_raise_an_actionable_error(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(loader.DATA_ROOT_ENV_VAR, str(tmp_path))
    with pytest.raises(FileNotFoundError, match=re.escape("scripts/fetch_data.py")):
        loader.load_plant("ai4i")
    with pytest.raises(FileNotFoundError, match=re.escape("scripts/fetch_data.py")):
        loader.load_manifest("ims")


def test_repo_root_contains_the_backend_package() -> None:
    assert (loader.repo_root() / "backend" / "xpm" / "data").is_dir()
    assert loader.raw_dir().name == "raw"
