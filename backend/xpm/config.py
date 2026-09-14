"""Settings loading, caching and path resolution (backend.md §1, §3.6).

``get_settings()`` is the cached singleton every other module reads; the config
``PUT`` endpoint calls ``reload_settings()`` after persisting an override. Path
leaves (``paths.*``, overridable as ``XPM_PATHS__DATA_DIR`` and friends) are
resolved here: a relative path is anchored to the repository root so the same
``settings.yaml`` works from any working directory and inside the containers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from xpm.contracts.rest import ConfigValue
from xpm.contracts.settings import (
    MUTABLE_CONFIG_KEYS,
    Settings,
    default_settings_file,
)

__all__ = [
    "MUTABLE_CONFIG_KEYS",
    "Settings",
    "data_dir",
    "db_path",
    "flatten_settings",
    "get_settings",
    "models_dir",
    "project_root",
    "reload_settings",
    "reports_dir",
    "resolve_path",
    "settings_file",
]


def settings_file() -> Path:
    """The YAML file the settings are loaded from."""
    return default_settings_file()


def project_root() -> Path:
    """The repository root: the parent of the ``config/`` directory in use.

    Falls back to the current working directory when the settings file could not
    be located on disk, which keeps relative paths meaningful in a bare install.
    """
    located = settings_file()
    if located.is_file():
        return located.resolve().parent.parent
    return Path.cwd()


def resolve_path(value: Path | str) -> Path:
    """Anchor a relative ``paths.*`` leaf to :func:`project_root`."""
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load, validate and cache the settings tree."""
    return Settings()


def reload_settings() -> Settings:
    """Drop the cached tree and load it again (used by ``PUT /api/config``)."""
    get_settings.cache_clear()
    return get_settings()


def data_dir() -> Path:
    """Absolute ``paths.data_dir``."""
    return resolve_path(get_settings().paths.data_dir)


def db_path() -> Path:
    """Absolute ``paths.db_path``."""
    return resolve_path(get_settings().paths.db_path)


def models_dir() -> Path:
    """Absolute ``paths.models_dir``."""
    return resolve_path(get_settings().paths.models_dir)


def reports_dir() -> Path:
    """Absolute ``paths.reports_dir``."""
    return resolve_path(get_settings().paths.reports_dir)


def _flatten(node: Any, prefix: str, out: dict[str, ConfigValue]) -> None:
    """Depth-first flatten of a JSON-mode settings dump into dotted keys."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            _flatten(value, f"{prefix}.{key}" if prefix else str(key), out)
        return
    if isinstance(node, Sequence) and not isinstance(node, str | bytes):
        out[prefix] = list(node)
        return
    out[prefix] = node


def flatten_settings(settings: Settings | None = None) -> dict[str, ConfigValue]:
    """Flatten the settings tree to the dotted-key map ``ConfigResponse.values``
    carries (backend.md §3.4.2).

    Lists stay lists; everything else is a JSON scalar, so ``dataset_start``
    appears as an ISO-8601 string and ``paths.*`` as strings.
    """
    tree = settings if settings is not None else get_settings()
    dumped = tree.model_dump(mode="json", by_alias=True)
    flat: dict[str, ConfigValue] = {}
    _flatten(dumped, "", flat)
    return flat
