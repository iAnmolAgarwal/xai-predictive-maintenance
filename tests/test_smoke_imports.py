"""The one test that must pass before any other task lands."""

import xpm


def test_package_imports_and_exposes_version() -> None:
    assert xpm.__version__ == "0.1.0"


def test_package_is_typed() -> None:
    from importlib.resources import files

    assert files("xpm").joinpath("py.typed").is_file()
