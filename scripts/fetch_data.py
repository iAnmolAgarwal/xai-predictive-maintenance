"""Fetch and preprocess the AI4I and IMS datasets into ``data/processed/``.

    uv run python scripts/fetch_data.py --plant ai4i   # == make data
    uv run python scripts/fetch_data.py --plant ims    # == make data-ims
    uv run python scripts/fetch_data.py --plant all

Set ``XPM_DATA_CACHE`` to a directory holding ``bearings.zip`` (or a
pre-extracted ``IMS/2nd_test/`` tree) to skip the 1 GB IMS download.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated

import typer

from xpm.data import ai4i, ims
from xpm.data.loader import Manifest

app = typer.Typer(add_completion=False, help=__doc__)


class Plant(StrEnum):
    """Which dataset to (re)generate."""

    AI4I = "ai4i"
    IMS = "ims"
    ALL = "all"


def _report(manifest: Manifest) -> None:
    typer.echo(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))


@app.command()
def main(
    plant: Annotated[Plant, typer.Option(help="Dataset to process.")] = Plant.ALL,
) -> None:
    """Process one or both plants and print each resulting manifest."""
    if plant in (Plant.AI4I, Plant.ALL):
        _report(ai4i.process())
    if plant in (Plant.IMS, Plant.ALL):
        _report(ims.process())


if __name__ == "__main__":
    app()
