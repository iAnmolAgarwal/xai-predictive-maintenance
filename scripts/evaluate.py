"""Score the registry and regenerate docs/EVALUATION.md + reports/metrics.json.

    uv run python scripts/evaluate.py                  # == make evaluate
    uv run python scripts/evaluate.py --plant ims --no-ablation

Requires a trained registry (`make train`). The ablation refits the served
family once per feature group, which is the slow part; `--no-ablation` skips it
for a quick metrics refresh.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from xpm.config import project_root, reports_dir
from xpm.contracts.common import PLANT_IDS, PlantId
from xpm.model import ablation, evaluate, registry

app = typer.Typer(add_completion=False, help=__doc__)

#: T-MODEL owns this file because it is machine-written (backend.md §2).
DOCUMENT_RELPATH = Path("docs") / "EVALUATION.md"


class Plant(StrEnum):
    """Which plant to evaluate."""

    AI4I = "ai4i"
    IMS = "ims"
    ALL = "all"


@app.command()
def main(
    plant: Annotated[Plant, typer.Option(help="Plant to evaluate.")] = Plant.ALL,
    ablate: Annotated[
        bool, typer.Option("--ablation/--no-ablation", help="Run the feature ablation.")
    ] = True,
    models_dir: Annotated[
        Path | None, typer.Option(help="Registry root; defaults to paths.models_dir.")
    ] = None,
    document: Annotated[
        Path | None, typer.Option(help="Output Markdown; defaults to docs/EVALUATION.md.")
    ] = None,
) -> None:
    """Evaluate one or both plants and rewrite both output artefacts."""
    root = models_dir if models_dir is not None else registry.registry_root()
    targets: tuple[PlantId, ...] = (
        PLANT_IDS if plant is Plant.ALL else (("ai4i" if plant is Plant.AI4I else "ims"),)
    )
    reports = reports_dir()
    report = evaluate.run_evaluation(
        targets,
        root=root,
        ablation_runner=ablation.run_ablation if ablate else None,
        faithfulness=evaluate.load_faithfulness(reports),
    )
    target_document = document if document is not None else project_root() / DOCUMENT_RELPATH
    evaluate.write_report(report, document=target_document, metrics_path=reports / "metrics.json")
    typer.echo(f"wrote {target_document} and {reports / 'metrics.json'}")


if __name__ == "__main__":
    app()
