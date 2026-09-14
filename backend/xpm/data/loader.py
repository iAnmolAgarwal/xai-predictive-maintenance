"""Paths, manifests and typed loaders for the committed processed datasets.

Nothing downstream of this module ever touches a raw dataset path. The two
processed parquet files are committed build outputs (R2/ADR-002), so a fresh
clone can stream both plants with no download at all.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd

from xpm.data.download import sha256_file
from xpm.data.schema import PlantId, TableSchema, schema_for, validate

DATA_ROOT_ENV_VAR: Final[str] = "XPM_DATA_ROOT"
PARQUET_COMPRESSION: Final[Literal["zstd"]] = "zstd"
MANIFEST_FILENAME: Final[str] = "manifest.json"

_PARQUET_NAMES: Final[dict[str, str]] = {"ai4i": "ai4i.parquet", "ims": "test2.parquet"}


def repo_root() -> Path:
    """The repository root, inferred from this file's location."""
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    """The ``data/`` tree, overridable with ``XPM_DATA_ROOT`` for tests."""
    override = os.environ.get(DATA_ROOT_ENV_VAR)
    return Path(override).expanduser() if override else repo_root() / "data"


def raw_dir() -> Path:
    """Where downloaded archives land; never committed."""
    return data_root() / "raw"


def processed_dir(plant: PlantId) -> Path:
    """Directory holding ``plant``'s committed parquet and manifest."""
    return data_root() / "processed" / plant


def processed_parquet(plant: PlantId) -> Path:
    """Path of ``plant``'s committed processed parquet."""
    return processed_dir(plant) / _PARQUET_NAMES[plant]


def manifest_path(plant: PlantId) -> Path:
    """Path of ``plant``'s committed manifest."""
    return processed_dir(plant) / MANIFEST_FILENAME


@dataclass(frozen=True, slots=True)
class Manifest:
    """Provenance of one processed parquet file.

    Deliberately carries no wall-clock timestamp: the manifest is a pure
    function of the input archive and the generation parameters, so a
    regeneration on another machine reproduces it byte for byte.
    """

    plant: str
    source_url: str
    source_sha256: str
    rows: int
    columns: list[str]
    parameters: dict[str, Any]
    parquet_file: str = ""
    parquet_sha256: str = ""
    parquet_bytes: int = 0
    machines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_processed(frame: pd.DataFrame, plant: PlantId, manifest: Manifest) -> Manifest:
    """Validate, write ``plant``'s parquet, then write its completed manifest."""
    schema: TableSchema = schema_for(plant)
    validate(frame, schema)
    target = processed_parquet(plant)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(target, engine="pyarrow", compression=PARQUET_COMPRESSION, index=False)

    machines = sorted(str(value) for value in frame["machine_id"].unique())
    complete = Manifest(
        plant=plant,
        source_url=manifest.source_url,
        source_sha256=manifest.source_sha256,
        rows=len(frame),
        columns=list(schema.names),
        parameters=manifest.parameters,
        parquet_file=target.name,
        parquet_sha256=sha256_file(target),
        parquet_bytes=target.stat().st_size,
        machines=machines,
    )
    manifest_path(plant).write_text(
        json.dumps(complete.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return complete


def load_manifest(plant: PlantId) -> dict[str, Any]:
    """The manifest of ``plant``'s processed parquet as a plain dict."""
    path = manifest_path(plant)
    if not path.is_file():
        raise FileNotFoundError(f"{plant}: {path} is missing; run scripts/fetch_data.py")
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def load_plant(plant: PlantId) -> pd.DataFrame:
    """Load and validate ``plant``'s processed frame, sorted by machine and time."""
    path = processed_parquet(plant)
    if not path.is_file():
        raise FileNotFoundError(f"{plant}: {path} is missing; run scripts/fetch_data.py")
    frame = pd.read_parquet(path, engine="pyarrow")
    frame = frame.sort_values(["machine_id", "dataset_ts"], kind="stable").reset_index(drop=True)
    return validate(frame, schema_for(plant))


def load_ai4i() -> pd.DataFrame:
    """The 10 000 AI4I rows mapped onto 12 virtual machines."""
    return load_plant("ai4i")


def load_ims() -> pd.DataFrame:
    """The 984 IMS test-2 snapshots x 4 bearings."""
    return load_plant("ims")


def list_machines(plant: PlantId) -> list[str]:
    """Machine ids present in ``plant``'s processed parquet, in canonical order."""
    return sorted(str(value) for value in load_plant(plant)["machine_id"].unique())
