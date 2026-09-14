"""Unpacking the nested IMS archive: zip -> 7z -> rar -> 984 ASCII files.

The trap documented in ``docs/plan/backend.md`` §3.2.2 is that 7-Zip cannot
read the ``.rar`` members -- it fails with ``Unsupported Method`` because they
use an old RAR compression method -- while ``unar`` reads them correctly. This
module therefore dispatches per archive type and fails with an actionable,
platform-specific message when a required tool is absent from ``PATH``.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Final

IMS_7Z_MEMBER: Final[str] = "4. Bearings/IMS.7z"
IMS_RAR_MEMBER: Final[str] = "2nd_test.rar"
IMS_TEST_DIR: Final[str] = "2nd_test"

SEVENZIP_CANDIDATES: Final[tuple[str, ...]] = ("7z", "7zz", "7za")
UNAR_CANDIDATES: Final[tuple[str, ...]] = ("unar",)

_INSTALL_HINTS: Final[dict[str, str]] = {
    "unar": "macOS: `brew install unar`   Debian/Ubuntu: `apt-get install -y unar`",
    "7z": "macOS: `brew install p7zip`    Debian/Ubuntu: `apt-get install -y p7zip-full`",
}


class MissingToolError(RuntimeError):
    """A required external unpacking tool is not on ``PATH``."""


class ExtractionError(RuntimeError):
    """An external unpacking tool ran but failed."""


def find_tool(candidates: tuple[str, ...], hint_key: str) -> str:
    """Absolute path of the first available binary in ``candidates``."""
    for name in candidates:
        found = shutil.which(name)
        if found is not None:
            return found
    names = " / ".join(candidates)
    raise MissingToolError(
        f"required tool {names} not found on PATH. Install it: {_INSTALL_HINTS[hint_key]}"
    )


def _run(argv: list[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ExtractionError(f"{argv[0]} exited {result.returncode}: {detail}")


def extract_zip_member(archive: Path, member: str, dest_dir: Path) -> Path:
    """Extract one member of a zip with the stdlib and return its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extract(member, path=dest_dir)
    extracted = dest_dir / member
    if not extracted.is_file():
        raise ExtractionError(f"{archive}: member {member!r} did not materialise")
    return extracted


def extract_7z(archive: Path, dest_dir: Path, member: str | None = None) -> Path:
    """Extract ``archive`` (or one member of it) with 7-Zip."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    tool = find_tool(SEVENZIP_CANDIDATES, "7z")
    argv = [tool, "x", "-y", f"-o{dest_dir}", str(archive)]
    if member is not None:
        argv.append(member)
    _run(argv)
    return dest_dir


def extract_rar(archive: Path, dest_dir: Path) -> Path:
    """Extract ``archive`` with ``unar`` (7-Zip cannot read these members)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    tool = find_tool(UNAR_CANDIDATES, "unar")
    _run([tool, "-q", "-f", "-o", str(dest_dir), str(archive)])
    return dest_dir


def extract_ims_test2(archive: Path, work_dir: Path) -> Path:
    """Unpack ``bearings.zip`` down to the ``2nd_test`` directory of raw files.

    Every step is skipped when its output already exists, so re-running is
    cheap on a warm tree.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    test_dir = work_dir / IMS_TEST_DIR
    if _is_populated(test_dir):
        return test_dir

    seven_zip = work_dir / IMS_7Z_MEMBER
    if not seven_zip.is_file():
        seven_zip = extract_zip_member(archive, IMS_7Z_MEMBER, work_dir)

    rar = work_dir / IMS_RAR_MEMBER
    if not rar.is_file():
        extract_7z(seven_zip, work_dir, IMS_RAR_MEMBER)
    if not rar.is_file():
        raise ExtractionError(f"{seven_zip}: {IMS_RAR_MEMBER} was not extracted")

    extract_rar(rar, work_dir)
    if not _is_populated(test_dir):
        raise ExtractionError(f"{rar}: {IMS_TEST_DIR} was not extracted")
    return test_dir


def _is_populated(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())
