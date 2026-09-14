"""Shared pytest fixtures.

Keeps every test run off the developer's real ``data/`` tree by pointing the
``XPM_PATHS__DATA_DIR`` override (see backend.md §3.6, ``XPM_<SECTION>__<KEY>``)
at a throwaway directory for the whole session.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def xpm_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Redirect the settings data directory at a session-scoped temp dir."""
    data_dir = tmp_path_factory.mktemp("xpm-data")
    previous = os.environ.get("XPM_PATHS__DATA_DIR")
    os.environ["XPM_PATHS__DATA_DIR"] = str(data_dir)
    try:
        yield data_dir
    finally:
        if previous is None:
            del os.environ["XPM_PATHS__DATA_DIR"]
        else:
            os.environ["XPM_PATHS__DATA_DIR"] = previous
