"""Session fixtures for the explain suite: one trained registry, four explainers.

Training happens once per session and the explainers are built once on top of
it, mirroring how the API holds them: an :class:`~xpm.explain.explainer.Explainer`
is expensive to construct (a model load plus a 256-row interventional
background) and cheap to reuse.

``--update-goldens`` rewrites ``tests/fixtures/explain/*.json`` instead of
asserting against them. It is declared here because the explain suite is the
only owner of a golden file that is regenerated rather than hand-written; the
root ``tests/conftest.py`` belongs to T-INFRA and is not amended.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from xpm.config import get_settings
from xpm.contracts.settings import Settings
from xpm.explain.explainer import Explainer, FeatureSnapshot

from . import riskiest_snapshot, train_registry

UPDATE_GOLDENS_FLAG = "--update-goldens"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add the golden-regeneration flag (``pytest tests/explain --update-goldens``)."""
    parser.addoption(
        UPDATE_GOLDENS_FLAG,
        action="store_true",
        default=False,
        help="Rewrite tests/fixtures/explain/*.json from the current code.",
    )


@pytest.fixture(scope="session")
def update_goldens(request: pytest.FixtureRequest) -> bool:
    """Whether this run should rewrite the goldens rather than assert on them."""
    return bool(request.config.getoption(UPDATE_GOLDENS_FLAG, default=False))


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def trained_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A real registry with both families of both plants."""
    root = train_registry(tmp_path_factory.mktemp("explain-registry"))
    yield root


@pytest.fixture(scope="session")
def ai4i_lgbm(trained_root: Path) -> Explainer:
    return Explainer.load("ai4i", "lgbm", root=trained_root)


@pytest.fixture(scope="session")
def ai4i_rf(trained_root: Path) -> Explainer:
    return Explainer.load("ai4i", "rf", root=trained_root)


@pytest.fixture(scope="session")
def ims_lgbm(trained_root: Path) -> Explainer:
    return Explainer.load("ims", "lgbm", root=trained_root)


@pytest.fixture(scope="session")
def ims_rf(trained_root: Path) -> Explainer:
    return Explainer.load("ims", "rf", root=trained_root)


@pytest.fixture(scope="session")
def ai4i_snapshot(ai4i_lgbm: Explainer) -> FeatureSnapshot:
    """The AI4I row an alert would fire on, with its history bands."""
    return riskiest_snapshot("ai4i", ai4i_lgbm)


@pytest.fixture(scope="session")
def ims_snapshot(ims_lgbm: Explainer) -> FeatureSnapshot:
    """The IMS row an alert would fire on, with its history bands."""
    return riskiest_snapshot("ims", ims_lgbm)
