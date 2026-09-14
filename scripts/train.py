"""Train LightGBM + RandomForest per plant and write the model registry.

    uv run python scripts/train.py --plant all        # == make train
    uv run python scripts/train.py --plant ims --bump minor

Deterministic: same committed processed parquet + same ``model.seed`` ⇒ the same
``model.txt`` bytes. Without ``--bump`` a retrain overwrites the newest version
of each family, so re-running this is idempotent.

This file is the one CLI wrapper on R6's coverage omit list; every line of logic
it calls lives in :mod:`xpm.model.train`.
"""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from xpm.contracts.common import PLANT_IDS, PlantId
from xpm.model import registry, train

app = typer.Typer(add_completion=False, help=__doc__)


class Plant(StrEnum):
    """Which plant's models to (re)train."""

    AI4I = "ai4i"
    IMS = "ims"
    ALL = "all"


class Bump(StrEnum):
    """Which part of MAJOR.MINOR.PATCH to advance."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


@app.command()
def main(
    plant: Annotated[Plant, typer.Option(help="Plant to train.")] = Plant.ALL,
    bump: Annotated[
        Bump | None, typer.Option(help="Write a new version instead of overwriting.")
    ] = None,
    models_dir: Annotated[
        Path | None, typer.Option(help="Registry root; defaults to paths.models_dir.")
    ] = None,
) -> None:
    """Train both families for one or both plants and print what was written."""
    root = models_dir if models_dir is not None else registry.registry_root()
    targets: tuple[PlantId, ...] = (
        PLANT_IDS if plant is Plant.ALL else (("ai4i" if plant is Plant.AI4I else "ims"),)
    )
    for plant_id in targets:
        started = time.perf_counter()
        trained = train.train_plant(plant_id, root=root, bump=None if bump is None else bump.value)
        elapsed = time.perf_counter() - started
        for item in trained:
            typer.echo(
                json.dumps(
                    {
                        "plant_id": plant_id,
                        "model_id": item.manifest.model_id,
                        "path": str(item.entry.path),
                        "served": item.is_served,
                        "n_train_rows": item.manifest.n_train_rows,
                        "n_features": item.manifest.n_features,
                        "train_run_id": item.manifest.train_run_id,
                        "metrics": item.metrics.summary(),
                    },
                    sort_keys=True,
                )
            )
        typer.echo(json.dumps({"plant_id": plant_id, "seconds": round(elapsed, 2)}))


if __name__ == "__main__":
    app()
