"""NASA IMS bearing test set 2: acquisition, band features and labelling.

984 snapshots at a 10-minute cadence, each 20 480 samples x 4 bearings at
20 kHz (§3.2.2). Bearing *b* becomes machine ``ims-0b``; every snapshot becomes
one row of nine channels (§3.2.3). The last N = 24 h before end-of-record on a
bearing that actually fails is labelled ``failure_imminent = 1`` (ADR-023).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from xpm.data.archive import IMS_TEST_DIR, extract_ims_test2
from xpm.data.bands import Float64Array, snapshot_matrix_channels
from xpm.data.download import (
    IMS_CACHE_EXTRACTED,
    IMS_CACHE_FILENAME,
    IMS_SHA256,
    IMS_URL,
    acquire_ims_archive,
    cached_file,
    cached_tree,
    sha256_file,
)
from xpm.data.loader import Manifest, raw_dir, write_processed
from xpm.data.schema import (
    IMS_BANDS_HZ,
    IMS_BEARING_COUNT,
    IMS_CHANNELS,
    IMS_FAILING_BEARINGS,
    IMS_FILENAME_FORMAT,
    IMS_LABEL,
    IMS_LABEL_HORIZON_HOURS,
    IMS_NPERSEG,
    IMS_OVERLAP,
    IMS_SAMPLE_RATE_HZ,
    IMS_SCHEMA,
    IMS_SNAPSHOT_ROWS,
    IMS_WINDOW,
    SchemaError,
    machine_id,
    order_columns,
)

EXPECTED_SNAPSHOTS: Final[int] = 984
LABEL_HORIZON: Final[pd.Timedelta] = pd.Timedelta(hours=IMS_LABEL_HORIZON_HOURS)


def parse_snapshot_timestamp(name: str) -> pd.Timestamp:
    """``2004.02.16.03.20.39`` -> a UTC timestamp."""
    parsed = dt.datetime.strptime(name, IMS_FILENAME_FORMAT).replace(tzinfo=dt.UTC)
    return pd.Timestamp(parsed)


def snapshot_files(test_dir: Path) -> list[Path]:
    """Every snapshot file in ``test_dir``, ordered by its embedded timestamp."""
    files = [path for path in test_dir.iterdir() if path.is_file() and _is_snapshot(path.name)]
    if not files:
        raise SchemaError(f"{test_dir}: no IMS snapshot files found")
    return sorted(files, key=lambda path: parse_snapshot_timestamp(path.name))


def _is_snapshot(name: str) -> bool:
    try:
        parse_snapshot_timestamp(name)
    except ValueError:
        return False
    return True


def read_snapshot(path: Path) -> Float64Array:
    """Load one tab-separated snapshot as a ``(samples, bearings)`` array in g."""
    frame = pd.read_csv(path, sep="\t", header=None, dtype="float64")
    matrix = frame.to_numpy(dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != IMS_BEARING_COUNT:
        raise SchemaError(f"{path}: expected {IMS_BEARING_COUNT} columns, got {matrix.shape}")
    return matrix


def snapshot_rows(path: Path) -> list[dict[str, Any]]:
    """One row per bearing for a single snapshot file."""
    matrix = read_snapshot(path)
    timestamp = parse_snapshot_timestamp(path.name)
    rows: list[dict[str, Any]] = []
    for index, channels in enumerate(snapshot_matrix_channels(matrix), start=1):
        rows.append(
            {
                "machine_id": machine_id("ims", index),
                "dataset_ts": timestamp,
                **channels,
                "bearing": index,
                "source_file": path.name,
            }
        )
    return rows


def build_frame(paths: Sequence[Path]) -> pd.DataFrame:
    """Compute channels for every snapshot, then label and order the frame."""
    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(snapshot_rows(path))
    frame = pd.DataFrame.from_records(records)
    frame = label_failure_imminent(frame)
    frame["machine_id"] = frame["machine_id"].astype("string")
    frame["source_file"] = frame["source_file"].astype("string")
    frame["bearing"] = frame["bearing"].astype("int8")
    for channel in IMS_CHANNELS:
        frame[channel] = frame[channel].astype("float64")
    ordered = order_columns(frame, IMS_SCHEMA)
    return ordered.sort_values(["machine_id", "dataset_ts"], kind="stable").reset_index(drop=True)


def label_failure_imminent(
    frame: pd.DataFrame,
    *,
    horizon: pd.Timedelta = LABEL_HORIZON,
    failing_bearings: Iterable[int] = IMS_FAILING_BEARINGS,
) -> pd.DataFrame:
    """Label the last ``horizon`` of every failing bearing as imminent failure.

    The window is half-open ``(end - horizon, end]``: a row exactly ``horizon``
    before end-of-record is negative, the final row is positive. That matches
    the half-open window convention used everywhere else in dataset time and
    yields exactly 144 positives per failing bearing at the 10-minute cadence.
    """
    out = frame.copy()
    labels = np.zeros(len(out), dtype=np.int8)
    failing = set(failing_bearings)
    for bearing in failing:
        mask = out["bearing"].to_numpy() == bearing
        if not bool(mask.any()):
            continue
        timestamps = pd.to_datetime(out.loc[mask, "dataset_ts"])
        end = timestamps.max()
        positive = (timestamps > end - horizon) & (timestamps <= end)
        labels[np.flatnonzero(mask)] = positive.to_numpy().astype(np.int8)
    out[IMS_LABEL] = labels
    return out


def resolve_test_dir() -> tuple[Path, str, str]:
    """Locate ``2nd_test``, returning ``(dir, source_url, source_sha256)``.

    A pre-extracted tree in ``XPM_DATA_CACHE`` short-circuits the 1 GB download
    and the whole unpacking chain; the archive's checksum is still reported,
    computed from the cached zip when one is present and otherwise taken from
    the pinned, verified constant in :mod:`xpm.data.download`.
    """
    archive = cached_file(IMS_CACHE_FILENAME)
    tree = cached_tree(IMS_CACHE_EXTRACTED)
    if tree is None:
        if archive is None:
            archive = acquire_ims_archive(raw_dir())
        tree = extract_ims_test2(archive, raw_dir() / "IMS")
    checksum = sha256_file(archive) if archive is not None else IMS_SHA256
    return tree, IMS_URL, checksum


def generation_parameters() -> dict[str, Any]:
    """The knobs that determine the processed IMS frame."""
    return {
        "test_set": IMS_TEST_DIR,
        "sample_rate_hz": IMS_SAMPLE_RATE_HZ,
        "samples_per_snapshot": IMS_SNAPSHOT_ROWS,
        "welch": {"window": IMS_WINDOW, "nperseg": IMS_NPERSEG, "overlap": IMS_OVERLAP},
        "band_edges_hz": {name: list(edges) for name, edges in IMS_BANDS_HZ.items()},
        "band_value": "band-mean PSD in g^2/Hz (integral over band / band width)",
        "label_horizon_hours": IMS_LABEL_HORIZON_HOURS,
        "label_window": "half-open (end - N, end]",
        "failing_bearings": list(IMS_FAILING_BEARINGS),
        "channels": list(IMS_CHANNELS),
    }


def process() -> Manifest:
    """Acquire, transform and write ``data/processed/ims/``."""
    test_dir, source_url, source_sha256 = resolve_test_dir()
    paths = snapshot_files(test_dir)
    if len(paths) != EXPECTED_SNAPSHOTS:
        raise SchemaError(f"ims: expected {EXPECTED_SNAPSHOTS} snapshots, got {len(paths)}")
    frame = build_frame(paths)
    return write_processed(
        frame,
        "ims",
        Manifest(
            plant="ims",
            source_url=source_url,
            source_sha256=source_sha256,
            rows=len(frame),
            columns=list(IMS_SCHEMA.names),
            parameters=generation_parameters(),
        ),
    )
