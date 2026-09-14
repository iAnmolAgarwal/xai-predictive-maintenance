"""Resumable HTTP download, checksum verification and the cache short-circuit.

The IMS archive is 1,075,597,174 bytes (§3.2.2), so every acquisition path in
this module is idempotent and re-entrant: a verified file is never fetched
again, a partial file is continued with a ``Range`` request rather than
restarted, and ``XPM_DATA_CACHE`` lets CI and a developer with a local copy
skip the network entirely.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

import httpx

IMS_URL: Final[str] = "https://phm-datasets.s3.amazonaws.com/NASA/4.+Bearings.zip"
IMS_SHA256: Final[str] = "21001ac266c465f5d345ec42d7b508c6a6328487fd9d4d7774422dd5ea10ad83"
IMS_BYTES: Final[int] = 1_075_597_174
IMS_CACHE_FILENAME: Final[str] = "bearings.zip"
IMS_CACHE_EXTRACTED: Final[str] = "IMS/2nd_test"

AI4I_URL: Final[str] = (
    "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
)
AI4I_CACHE_FILENAME: Final[str] = "ai4i2020.zip"

CACHE_ENV_VAR: Final[str] = "XPM_DATA_CACHE"
MAX_ATTEMPTS: Final[int] = 5
BASE_DELAY_SECONDS: Final[float] = 1.0
CHUNK_BYTES: Final[int] = 1 << 20
HTTP_TIMEOUT_SECONDS: Final[float] = 60.0


class DownloadError(RuntimeError):
    """A download failed after exhausting every retry."""


class ChecksumMismatch(RuntimeError):  # noqa: N818 - name pinned by backend.md §4
    """A downloaded file did not match its expected SHA-256."""


def cache_dir() -> Path | None:
    """The directory named by ``XPM_DATA_CACHE``, if it is set and exists."""
    raw = os.environ.get(CACHE_ENV_VAR)
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def cached_file(name: str) -> Path | None:
    """A file inside the data cache, or ``None`` when there is no cache hit."""
    root = cache_dir()
    if root is None:
        return None
    candidate = root / name
    return candidate if candidate.is_file() else None


def cached_tree(relative: str) -> Path | None:
    """A pre-extracted directory inside the data cache, or ``None``."""
    root = cache_dir()
    if root is None:
        return None
    candidate = root / relative
    return candidate if candidate.is_dir() else None


def sha256_file(path: Path, *, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Streaming SHA-256 of ``path`` as a lowercase hex digest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def backoff_delays(attempts: int = MAX_ATTEMPTS, base: float = BASE_DELAY_SECONDS) -> list[float]:
    """Exponential backoff schedule: 1 s, 2 s, 4 s, 8 s, 16 s (§3.2.2)."""
    return [base * (2.0**index) for index in range(attempts)]


def download(
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    client_factory: Callable[[], httpx.Client] | None = None,
    attempts: int = MAX_ATTEMPTS,
    base_delay: float = BASE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    chunk_bytes: int = CHUNK_BYTES,
) -> Path:
    """Download ``url`` to ``dest``, resuming a partial ``.part`` file.

    An existing ``dest`` whose checksum already matches is returned untouched.
    A completed download whose checksum does not match is deleted and
    :class:`ChecksumMismatch` is raised, so a corrupt archive never reaches the
    extraction step.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (expected_sha256 is None or sha256_file(dest) == expected_sha256):
        return dest

    part = dest.with_name(dest.name + ".part")
    factory = client_factory or (lambda: httpx.Client(timeout=HTTP_TIMEOUT_SECONDS))
    _fetch_with_retries(
        url,
        part,
        factory,
        chunk_bytes,
        attempts=attempts,
        delays=backoff_delays(attempts, base_delay),
        sleep=sleep,
    )

    if expected_sha256 is not None:
        actual = sha256_file(part)
        if actual != expected_sha256:
            part.unlink()
            raise ChecksumMismatch(
                f"{url} sha256 {actual} != expected {expected_sha256}; partial file deleted"
            )

    part.replace(dest)
    return dest


def _fetch_with_retries(
    url: str,
    part: Path,
    client_factory: Callable[[], httpx.Client],
    chunk_bytes: int,
    *,
    attempts: int,
    delays: list[float],
    sleep: Callable[[float], None],
) -> None:
    """Retry :func:`_fetch_once` on transport errors, sleeping between attempts.

    The last failure is re-raised as :class:`DownloadError` with the original
    transport error attached, so the caller sees why the archive never landed.
    """
    last_error: Exception | None = None
    for index in range(attempts):
        try:
            _fetch_once(url, part, client_factory, chunk_bytes)
            return
        except (httpx.HTTPError, OSError) as exc:  # network/transport level only
            last_error = exc
            if index < attempts - 1:
                sleep(delays[index])
    raise DownloadError(f"giving up on {url} after {attempts} attempts") from last_error


def _fetch_once(
    url: str,
    part: Path,
    client_factory: Callable[[], httpx.Client],
    chunk_bytes: int,
) -> None:
    """One streaming attempt, continuing from whatever ``part`` already holds."""
    offset = part.stat().st_size if part.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with (
        client_factory() as client,
        client.stream("GET", url, headers=headers, follow_redirects=True) as response,
    ):
        if offset and response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
            return
        response.raise_for_status()
        # A server that ignores the Range header replies 200 with the whole
        # body; restarting is the only correct response.
        mode = "ab" if offset and response.status_code == httpx.codes.PARTIAL_CONTENT else "wb"
        with part.open(mode) as handle:
            for block in response.iter_bytes(chunk_bytes):
                handle.write(block)


def acquire_ims_archive(
    raw_dir: Path,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Return a verified ``bearings.zip``, preferring the cache over the network."""
    hit = cached_file(IMS_CACHE_FILENAME)
    if hit is not None:
        return hit
    return download(
        IMS_URL,
        raw_dir / IMS_CACHE_FILENAME,
        expected_sha256=IMS_SHA256,
        client_factory=client_factory,
        sleep=sleep,
    )
