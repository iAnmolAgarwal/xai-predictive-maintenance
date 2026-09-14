"""The N = 24 h failure-imminent horizon (ADR-023) and its boundary rows."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pytest import MonkeyPatch

from xpm.data import ims, loader
from xpm.data.download import (
    CACHE_ENV_VAR,
    IMS_CACHE_EXTRACTED,
    IMS_CACHE_FILENAME,
    IMS_SHA256,
    IMS_URL,
    sha256_file,
)
from xpm.data.schema import (
    IMS_BEARING_COUNT,
    IMS_CHANNELS,
    IMS_FAILING_BEARINGS,
    IMS_LABEL,
    IMS_LABEL_HORIZON_HOURS,
    IMS_SCHEMA,
    IMS_SNAPSHOT_MINUTES,
    SchemaError,
    machine_id,
    validate,
)

SNAPSHOTS = 300
EXPECTED_POSITIVES = int(IMS_LABEL_HORIZON_HOURS * 60 / IMS_SNAPSHOT_MINUTES)


def _synthetic_frame(snapshots: int = SNAPSHOTS) -> pd.DataFrame:
    start = pd.Timestamp("2004-02-12T10:32:39Z")
    rows = []
    for index in range(snapshots):
        timestamp = start + pd.Timedelta(minutes=IMS_SNAPSHOT_MINUTES * index)
        for bearing in range(1, IMS_BEARING_COUNT + 1):
            rows.append(
                {
                    "machine_id": machine_id("ims", bearing),
                    "dataset_ts": timestamp,
                    **dict.fromkeys(IMS_CHANNELS, float(bearing)),
                    "bearing": bearing,
                    "source_file": timestamp.strftime("%Y.%m.%d.%H.%M.%S"),
                }
            )
    return pd.DataFrame.from_records(rows)


def test_exactly_the_last_24_hours_of_the_failing_bearing_are_positive() -> None:
    labelled = ims.label_failure_imminent(_synthetic_frame())
    failing = labelled[labelled["bearing"] == IMS_FAILING_BEARINGS[0]]
    assert int(failing[IMS_LABEL].sum()) == EXPECTED_POSITIVES == 144


def test_the_boundary_is_half_open_end_minus_n_exclusive_end_inclusive() -> None:
    labelled = ims.label_failure_imminent(_synthetic_frame())
    failing = labelled[labelled["bearing"] == IMS_FAILING_BEARINGS[0]].reset_index(drop=True)
    end = failing["dataset_ts"].max()
    horizon = pd.Timedelta(hours=IMS_LABEL_HORIZON_HOURS)

    at_boundary = failing.loc[failing["dataset_ts"] == end - horizon, IMS_LABEL]
    just_after = failing.loc[
        failing["dataset_ts"] == end - horizon + pd.Timedelta(minutes=IMS_SNAPSHOT_MINUTES),
        IMS_LABEL,
    ]
    at_end = failing.loc[failing["dataset_ts"] == end, IMS_LABEL]

    assert int(at_boundary.iloc[0]) == 0
    assert int(just_after.iloc[0]) == 1
    assert int(at_end.iloc[0]) == 1


def test_healthy_bearings_are_all_negative() -> None:
    labelled = ims.label_failure_imminent(_synthetic_frame())
    healthy = labelled[~labelled["bearing"].isin(IMS_FAILING_BEARINGS)]
    assert int(healthy[IMS_LABEL].sum()) == 0
    assert labelled[IMS_LABEL].dtype == np.int8


def test_a_shorter_horizon_labels_proportionally_fewer_rows() -> None:
    labelled = ims.label_failure_imminent(_synthetic_frame(), horizon=pd.Timedelta(hours=6))
    failing = labelled[labelled["bearing"] == IMS_FAILING_BEARINGS[0]]
    assert int(failing[IMS_LABEL].sum()) == 36


def test_a_bearing_absent_from_the_frame_is_skipped() -> None:
    frame = _synthetic_frame(snapshots=5)
    labelled = ims.label_failure_imminent(frame, failing_bearings=(9,))
    assert int(labelled[IMS_LABEL].sum()) == 0


def test_committed_parquet_carries_exactly_one_failing_machine() -> None:
    frame = loader.load_ims()
    counts = frame.groupby("machine_id")[IMS_LABEL].sum().to_dict()
    assert counts[machine_id("ims", IMS_FAILING_BEARINGS[0])] == EXPECTED_POSITIVES
    assert sum(counts.values()) == EXPECTED_POSITIVES


def test_snapshot_timestamps_are_parsed_from_the_filename() -> None:
    parsed = ims.parse_snapshot_timestamp("2004.02.16.03.20.39")
    assert parsed == pd.Timestamp(dt.datetime(2004, 2, 16, 3, 20, 39, tzinfo=dt.UTC))
    with pytest.raises(ValueError, match="does not match format"):
        ims.parse_snapshot_timestamp("not-a-snapshot")


def test_snapshot_discovery_orders_by_timestamp_and_ignores_other_files(tmp_path: Path) -> None:
    for name in ("2004.02.12.10.42.39", "2004.02.12.10.32.39", "README.txt"):
        (tmp_path / name).write_text("0\t0\t0\t0\n")
    found = ims.snapshot_files(tmp_path)
    assert [path.name for path in found] == ["2004.02.12.10.32.39", "2004.02.12.10.42.39"]


# --- the snapshot -> frame pipeline -----------------------------------------


def _write_snapshot(directory: Path, name: str, rows: int = 4096) -> None:
    rng = np.random.default_rng(abs(hash(name)) % (2**32))
    matrix = rng.normal(scale=0.08, size=(rows, IMS_BEARING_COUNT))
    directory.mkdir(parents=True, exist_ok=True)
    np.savetxt(directory / name, matrix, delimiter="\t", fmt="%.3f")


def test_build_frame_reads_snapshots_and_matches_the_schema(tmp_path: Path) -> None:
    names = ["2004.02.12.10.32.39", "2004.02.12.10.42.39"]
    for name in names:
        _write_snapshot(tmp_path, name)
    frame = ims.build_frame(ims.snapshot_files(tmp_path))
    assert list(frame.columns) == list(IMS_SCHEMA.names)
    assert len(frame) == len(names) * IMS_BEARING_COUNT
    assert set(frame["machine_id"]) == {machine_id("ims", b) for b in range(1, 5)}
    validate(frame, IMS_SCHEMA)


def test_read_snapshot_rejects_a_wrong_column_count(tmp_path: Path) -> None:
    path = tmp_path / "2004.02.12.10.32.39"
    path.write_text("0.1\t0.2\n0.3\t0.4\n")
    with pytest.raises(SchemaError, match="expected 4 columns"):
        ims.read_snapshot(path)


def test_snapshot_discovery_requires_at_least_one_file(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="no IMS snapshot files"):
        ims.snapshot_files(tmp_path)


def test_process_refuses_a_truncated_test_set(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _write_snapshot(tmp_path, "2004.02.12.10.32.39")
    monkeypatch.setattr(ims, "resolve_test_dir", lambda: (tmp_path, "file://local", "0" * 64))
    with pytest.raises(SchemaError, match="expected 984 snapshots, got 1"):
        ims.process()


def test_process_writes_the_parquet_and_manifest(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    source = tmp_path / "2nd_test"
    for name in ("2004.02.12.10.32.39", "2004.02.12.10.42.39"):
        _write_snapshot(source, name)
    monkeypatch.setattr(ims, "EXPECTED_SNAPSHOTS", 2)
    monkeypatch.setattr(ims, "resolve_test_dir", lambda: (source, "file://local", "0" * 64))
    monkeypatch.setenv(loader.DATA_ROOT_ENV_VAR, str(tmp_path / "data"))

    manifest = ims.process()

    assert manifest.rows == 8
    assert manifest.machines == [machine_id("ims", b) for b in range(1, 5)]
    assert loader.processed_parquet("ims").is_file()
    assert loader.load_manifest("ims")["parquet_sha256"] == manifest.parquet_sha256
    assert manifest.parameters["label_horizon_hours"] == IMS_LABEL_HORIZON_HOURS


def test_resolve_test_dir_prefers_the_cached_tree(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    tree = cache / IMS_CACHE_EXTRACTED
    tree.mkdir(parents=True)
    (cache / IMS_CACHE_FILENAME).write_bytes(b"archive bytes")
    monkeypatch.setenv(CACHE_ENV_VAR, str(cache))

    resolved, url, checksum = ims.resolve_test_dir()

    assert resolved == tree
    assert url == IMS_URL
    assert checksum == sha256_file(cache / IMS_CACHE_FILENAME)


def test_resolve_test_dir_falls_back_to_the_pinned_checksum(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    (cache / IMS_CACHE_EXTRACTED).mkdir(parents=True)
    monkeypatch.setenv(CACHE_ENV_VAR, str(cache))
    assert ims.resolve_test_dir()[2] == IMS_SHA256


def test_resolve_test_dir_downloads_and_extracts_when_the_cache_is_empty(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_ENV_VAR, str(tmp_path / "empty"))
    monkeypatch.setenv(loader.DATA_ROOT_ENV_VAR, str(tmp_path / "data"))
    archive_path = tmp_path / "bearings.zip"
    archive_path.write_bytes(b"archive bytes")
    extracted = tmp_path / "data" / "raw" / "IMS" / "2nd_test"

    def fake_acquire(raw_dir: Path) -> Path:
        return archive_path

    def fake_extract(archive: Path, work_dir: Path) -> Path:
        extracted.mkdir(parents=True, exist_ok=True)
        return extracted

    monkeypatch.setattr(ims, "acquire_ims_archive", fake_acquire)
    monkeypatch.setattr(ims, "extract_ims_test2", fake_extract)

    resolved, _, checksum = ims.resolve_test_dir()
    assert resolved == extracted
    assert checksum == sha256_file(archive_path)
