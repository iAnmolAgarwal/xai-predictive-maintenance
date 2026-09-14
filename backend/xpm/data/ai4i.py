"""AI4I 2020 acquisition and the 12-machine simulation mapping (§3.2.1).

The 10 000 i.i.d. product records are ordered by ``UDI`` and dealt round-robin
into 12 virtual machines, then replayed as a 5-minute-per-row series. That is a
simulation convenience and is recorded as such (ADR-024); round-robin rather
than contiguous blocks is what gives every machine a similar failure
prevalence, so all 12 tiles are live during a demo.
"""

from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from xpm.data.download import AI4I_CACHE_FILENAME, AI4I_URL, cached_file, download, sha256_file
from xpm.data.loader import Manifest, raw_dir, write_processed
from xpm.data.schema import (
    AI4I_CHANNELS,
    AI4I_DATASET_START,
    AI4I_FAILURE_MODES,
    AI4I_LABEL,
    AI4I_MACHINE_COUNT,
    AI4I_ROW_MINUTES,
    AI4I_SCHEMA,
    SchemaError,
    machine_id,
    order_columns,
)

UCI_REPO_ID: Final[int] = 601
UCIML_SOURCE: Final[str] = f"ucimlrepo:{UCI_REPO_ID}"
RAW_CSV_NAME: Final[str] = "ai4i2020.csv"
RAW_PARQUET_NAME: Final[str] = "ai4i2020.parquet"
EXPECTED_ROWS: Final[int] = 10_000

COLUMN_RENAMES: Final[dict[str, str]] = {
    # ``ucimlrepo`` spells the index column ``UID``; the UCI zip spells it ``UDI``.
    "udi": "udi",
    "uid": "udi",
    "product id": "product_id",
    "type": "variant",
    "air temperature": "air_temp",
    "process temperature": "process_temp",
    "rotational speed": "rot_speed",
    "torque": "torque",
    "tool wear": "tool_wear",
    "machine failure": AI4I_LABEL,
    "twf": "twf",
    "hdf": "hdf",
    "pwf": "pwf",
    "osf": "osf",
    "rnf": "rnf",
}

RAW_CHANNELS: Final[tuple[str, ...]] = (
    "air_temp",
    "process_temp",
    "rot_speed",
    "torque",
    "tool_wear",
)


def _canonical_key(column: str) -> str:
    """Strip the ``[K]``/``[rpm]`` unit suffix and normalise case and spacing."""
    head = column.split("[", 1)[0]
    return " ".join(head.replace("_", " ").lower().split())


def normalise_columns(raw: pd.DataFrame) -> pd.DataFrame:
    """Rename UCI's decorated headers to the canonical channel names."""
    mapping: dict[str, str] = {}
    for column in raw.columns:
        key = _canonical_key(str(column))
        if key in COLUMN_RENAMES:
            mapping[str(column)] = COLUMN_RENAMES[key]
    renamed = raw.rename(columns=mapping)
    required = (*RAW_CHANNELS, AI4I_LABEL, *AI4I_FAILURE_MODES, "variant", "udi")
    missing = [name for name in required if name not in renamed.columns]
    if missing:
        raise SchemaError(f"ai4i: source is missing columns {missing}")
    return renamed.loc[:, list(required)]


def derive_channels(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ``temp_diff`` (K) and ``power`` (W) exactly as §3.2.1 defines them."""
    out = frame.copy()
    for name in RAW_CHANNELS:
        out[name] = out[name].astype("float64")
    out["temp_diff"] = out["process_temp"] - out["air_temp"]
    out["power"] = out["torque"] * out["rot_speed"] * (2.0 * math.pi / 60.0)
    return out


def assign_machines(frame: pd.DataFrame) -> pd.DataFrame:
    """Deal rows round-robin into 12 machines and stamp per-machine dataset time."""
    out = frame.sort_values("udi", kind="stable").reset_index(drop=True)
    index = np.arange(len(out), dtype=np.int64)
    out["machine_id"] = [machine_id("ai4i", int(i % AI4I_MACHINE_COUNT) + 1) for i in index]
    tick = index // AI4I_MACHINE_COUNT
    out["dataset_ts"] = AI4I_DATASET_START + pd.to_timedelta(tick * AI4I_ROW_MINUTES, unit="m")
    out["source_row"] = out["udi"].astype("int32")
    return out


def build_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Full raw-to-processed transform: rename, derive, map, order, sort."""
    frame = assign_machines(derive_channels(normalise_columns(raw)))
    for label in (AI4I_LABEL, *AI4I_FAILURE_MODES):
        frame[label] = frame[label].astype("int8")
    frame["variant"] = frame["variant"].astype("string")
    frame["machine_id"] = frame["machine_id"].astype("string")
    ordered = order_columns(frame, AI4I_SCHEMA)
    return ordered.sort_values(["machine_id", "dataset_ts"], kind="stable").reset_index(drop=True)


def _read_csv_from_zip(archive: Path) -> pd.DataFrame:
    with zipfile.ZipFile(archive) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if not names:
            raise SchemaError(f"{archive}: no CSV member found")
        with zf.open(names[0]) as handle:
            frame: pd.DataFrame = pd.read_csv(io.BytesIO(handle.read()))
    return frame


def _fetch_via_ucimlrepo() -> pd.DataFrame:
    from ucimlrepo import fetch_ucirepo

    dataset: Any = fetch_ucirepo(id=UCI_REPO_ID)
    parts = [
        part
        for part in (dataset.data.ids, dataset.data.features, dataset.data.targets)
        if part is not None
    ]
    combined: pd.DataFrame = pd.concat(parts, axis=1)
    return combined


def fetch_raw(destination: Path | None = None) -> tuple[pd.DataFrame, str, str]:
    """Fetch AI4I, cache the raw CSV, and return ``(frame, source_url, sha256)``.

    ``ucimlrepo`` is the documented path; the direct UCI zip is the fallback so
    the step still works when the API wrapper is unavailable.
    """
    target_dir = destination if destination is not None else raw_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    csv_path = target_dir / RAW_CSV_NAME

    source_url = UCIML_SOURCE
    try:
        frame = _fetch_via_ucimlrepo()
    except Exception:  # any wrapper failure falls back to the direct zip
        source_url = AI4I_URL
        archive = cached_file(AI4I_CACHE_FILENAME)
        if archive is None:
            archive = download(AI4I_URL, target_dir / AI4I_CACHE_FILENAME)
        frame = _read_csv_from_zip(archive)

    frame.to_csv(csv_path, index=False)
    frame.to_parquet(target_dir / RAW_PARQUET_NAME, engine="pyarrow", index=False)
    return frame, source_url, sha256_file(csv_path)


def generation_parameters() -> dict[str, Any]:
    """The knobs that determine the processed AI4I frame."""
    return {
        "machine_count": AI4I_MACHINE_COUNT,
        "row_minutes": AI4I_ROW_MINUTES,
        "dataset_start": AI4I_DATASET_START.isoformat(),
        "mapping": "round_robin_by_udi",
        "channels": list(AI4I_CHANNELS),
        "derived": {
            "temp_diff": "process_temp - air_temp",
            "power": "torque * rot_speed * 2*pi/60",
        },
        "failure_modes": list(AI4I_FAILURE_MODES),
    }


def process(destination: Path | None = None) -> Manifest:
    """Fetch, transform and write ``data/processed/ai4i/``."""
    raw, source_url, source_sha256 = fetch_raw(destination)
    frame = build_frame(raw)
    if len(frame) != EXPECTED_ROWS:
        raise SchemaError(f"ai4i: expected {EXPECTED_ROWS} rows, got {len(frame)}")
    return write_processed(
        frame,
        "ai4i",
        Manifest(
            plant="ai4i",
            source_url=source_url,
            source_sha256=source_sha256,
            rows=len(frame),
            columns=list(AI4I_SCHEMA.names),
            parameters=generation_parameters(),
        ),
    )
