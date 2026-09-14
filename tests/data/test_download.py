"""Resumable download, checksum verification, cache short-circuit, extraction.

The real HTTP layer is exercised through ``httpx.MockTransport``; nothing here
opens a socket.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from xpm.data import archive, download

URL = "https://example.invalid/bearings.zip"
BODY = b"".join(bytes([i % 251]) for i in range(4096))
BODY_SHA = hashlib.sha256(BODY).hexdigest()


def _factory(transport: httpx.MockTransport) -> Callable[[], httpx.Client]:
    def build() -> httpx.Client:
        return httpx.Client(transport=transport)

    return build


def test_backoff_schedule_is_1_2_4_8_16() -> None:
    assert download.backoff_delays() == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_fresh_download_writes_verified_file(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=BODY)

    dest = tmp_path / "bearings.zip"
    result = download.download(
        URL,
        dest,
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert result == dest
    assert dest.read_bytes() == BODY
    assert not dest.with_name(dest.name + ".part").exists()
    assert len(calls) == 1
    assert "Range" not in calls[0].headers


def test_existing_verified_file_is_not_refetched(tmp_path: Path) -> None:
    dest = tmp_path / "bearings.zip"
    dest.write_bytes(BODY)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("transport must not be called for a verified file")

    download.download(
        URL,
        dest,
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert dest.read_bytes() == BODY


def test_partial_file_is_resumed_with_a_range_request(tmp_path: Path) -> None:
    dest = tmp_path / "bearings.zip"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(BODY[:1000])
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Range"])
        return httpx.Response(206, content=BODY[1000:])

    download.download(
        URL,
        dest,
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert seen == ["bytes=1000-"]
    assert dest.read_bytes() == BODY


def test_server_ignoring_range_restarts_the_part_file(tmp_path: Path) -> None:
    dest = tmp_path / "bearings.zip"
    dest.with_name(dest.name + ".part").write_bytes(b"stale prefix")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    download.download(
        URL,
        dest,
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert dest.read_bytes() == BODY


def test_range_not_satisfiable_means_the_part_is_already_complete(tmp_path: Path) -> None:
    dest = tmp_path / "bearings.zip"
    dest.with_name(dest.name + ".part").write_bytes(BODY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(416)

    download.download(
        URL,
        dest,
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert dest.read_bytes() == BODY


def test_transport_failures_retry_with_exponential_backoff(tmp_path: Path) -> None:
    attempts = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=BODY)

    download.download(
        URL,
        tmp_path / "bearings.zip",
        expected_sha256=BODY_SHA,
        client_factory=_factory(httpx.MockTransport(handler)),
        sleep=slept.append,
    )
    assert attempts["n"] == 3
    assert slept == [1.0, 2.0]


def test_exhausted_retries_raise_download_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("always down", request=request)

    with pytest.raises(download.DownloadError, match="after 3 attempts") as excinfo:
        download.download(
            URL,
            tmp_path / "bearings.zip",
            expected_sha256=BODY_SHA,
            client_factory=_factory(httpx.MockTransport(handler)),
            attempts=3,
            sleep=lambda _: None,
        )
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


def test_download_without_an_expected_checksum_skips_verification(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"unverified payload")

    dest = tmp_path / "ai4i2020.zip"
    result = download.download(
        URL,
        dest,
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert result.read_bytes() == b"unverified payload"


def test_checksum_mismatch_deletes_the_file_and_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"corrupt")

    dest = tmp_path / "bearings.zip"
    with pytest.raises(download.ChecksumMismatch, match="partial file deleted"):
        download.download(
            URL,
            dest,
            expected_sha256=BODY_SHA,
            client_factory=_factory(httpx.MockTransport(handler)),
        )
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def _never_called(request: httpx.Request) -> httpx.Response:  # pragma: no cover - guard
    raise AssertionError("the cache short-circuit must not hit the network")


def test_cache_hit_on_zip_skips_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    cached = cache / download.IMS_CACHE_FILENAME
    cached.write_bytes(BODY)
    monkeypatch.setenv(download.CACHE_ENV_VAR, str(cache))

    result = download.acquire_ims_archive(
        tmp_path / "raw",
        client_factory=_factory(httpx.MockTransport(_never_called)),
    )
    assert result == cached
    assert not (tmp_path / "raw").exists()


def test_cache_miss_falls_through_to_the_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(download.CACHE_ENV_VAR, str(tmp_path / "empty-cache"))
    monkeypatch.setattr(download, "IMS_SHA256", BODY_SHA)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    result = download.acquire_ims_archive(
        tmp_path / "raw",
        client_factory=_factory(httpx.MockTransport(handler)),
    )
    assert result.read_bytes() == BODY


def test_cache_helpers_return_none_without_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(download.CACHE_ENV_VAR, raising=False)
    assert download.cache_dir() is None
    assert download.cached_file("bearings.zip") is None
    assert download.cached_tree(download.IMS_CACHE_EXTRACTED) is None


def test_cached_tree_finds_a_pre_extracted_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / download.IMS_CACHE_EXTRACTED
    tree.mkdir(parents=True)
    monkeypatch.setenv(download.CACHE_ENV_VAR, str(tmp_path))
    assert download.cached_tree(download.IMS_CACHE_EXTRACTED) == tree
    assert download.cached_file("absent.zip") is None


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "blob"
    path.write_bytes(BODY)
    assert download.sha256_file(path, chunk_bytes=64) == BODY_SHA


# --- archive dispatch --------------------------------------------------------


def test_missing_unar_names_the_tool_and_the_install_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(archive.MissingToolError) as excinfo:
        archive.extract_rar(tmp_path / "2nd_test.rar", tmp_path / "out")
    message = str(excinfo.value)
    assert "unar" in message
    assert "brew install unar" in message
    assert "apt-get install -y unar" in message


def test_missing_7z_names_p7zip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(archive.MissingToolError, match="p7zip"):
        archive.extract_7z(tmp_path / "IMS.7z", tmp_path / "out")


def test_zip_member_extraction_uses_the_stdlib(tmp_path: Path) -> None:
    zip_path = tmp_path / "bearings.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(archive.IMS_7Z_MEMBER, b"seven-zip-bytes")
    extracted = archive.extract_zip_member(zip_path, archive.IMS_7Z_MEMBER, tmp_path / "work")
    assert extracted.read_bytes() == b"seven-zip-bytes"


def test_zip_member_extraction_reports_a_missing_member(tmp_path: Path) -> None:
    zip_path = tmp_path / "bearings.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("other.bin", b"x")
    with pytest.raises(KeyError):
        archive.extract_zip_member(zip_path, archive.IMS_7Z_MEMBER, tmp_path / "work")


class _FakeRun:
    """Records the argv of each external tool call and fakes its side effect."""

    def __init__(self, work: Path, *, returncode: int = 0) -> None:
        self.work = work
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if self.returncode == 0:
            if argv[0].endswith("7z"):
                (self.work / archive.IMS_RAR_MEMBER).write_bytes(b"rar-bytes")
            else:
                target = self.work / archive.IMS_TEST_DIR
                target.mkdir(parents=True, exist_ok=True)
                (target / "2004.02.12.10.32.39").write_text("0\t0\t0\t0\n")
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr="nope")


def test_extraction_dispatches_zip_then_7z_then_unar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    zip_path = tmp_path / "bearings.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(archive.IMS_7Z_MEMBER, b"seven-zip-bytes")
    fake = _FakeRun(work)
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    test_dir = archive.extract_ims_test2(zip_path, work)

    assert test_dir == work / archive.IMS_TEST_DIR
    assert [call[0] for call in fake.calls] == ["/usr/bin/7z", "/usr/bin/unar"]
    assert fake.calls[1][:2] == ["/usr/bin/unar", "-q"]
    # A second call short-circuits on the populated tree.
    archive.extract_ims_test2(zip_path, work)
    assert len(fake.calls) == 2


def test_failing_tool_raises_extraction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", _FakeRun(tmp_path, returncode=2))
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(archive.ExtractionError, match="exited 2: nope"):
        archive.extract_rar(tmp_path / "2nd_test.rar", tmp_path / "out")


def test_missing_rar_after_7z_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    zip_path = tmp_path / "bearings.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(archive.IMS_7Z_MEMBER, b"seven-zip-bytes")

    def silent_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", silent_run)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(archive.ExtractionError, match=re.escape("2nd_test.rar was not extracted")):
        archive.extract_ims_test2(zip_path, work)
