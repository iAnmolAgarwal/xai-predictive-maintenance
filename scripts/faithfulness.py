"""Does removing the top-SHAP feature actually move the prediction its way?

    uv run python scripts/faithfulness.py            # writes reports/faithfulness.json
    uv run python scripts/faithfulness.py --plant ims --no-strict

This is the "explanation faithfulness" section GOAL requires in
``docs/EVALUATION.md``. It is **not** a pytest test: it needs the full trained
registry (``make train``) and the whole held-out split, which unit tests do not
have. ``scripts/evaluate.py`` reads the JSON it writes and inlines it into the
document, so the order is ``make train`` -> this script -> ``make evaluate``.

Method, deliberately simple so the number means something:

* the **alert set** is every held-out row the served model scores at or above
  ``alerting.probability_threshold`` — the same rows the live pipeline would
  open an alert on, per plant, so this measures the explanations users actually
  see rather than an arbitrary sample;
* for each such row the **top-|SHAP| feature** is ablated to its **median in the
  frozen SHAP background**, which is the "typical" value the interventional
  explainer marginalises against (R3), and the row is re-scored;
* the move is **as expected** when a positive contribution's removal lowers the
  probability and a negative contribution's removal raises it. A probability
  that does not move at all counts as *not* expected;
* everything runs on :class:`~xpm.explain.explainer.Explainer`, the same object
  and the same explainer configuration serving uses (R3).

The gate is ``fraction_expected_direction >= --min-fraction`` (0.90 by default,
the figure backend.md §4 names). There is no settings key for it because it is
a property of this check rather than of the running system; it is a CLI option
so a caller can tighten it without editing code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final

import numpy as np
import typer

from xpm.config import get_settings, reports_dir
from xpm.contracts.common import PLANT_IDS, PlantId
from xpm.explain.explainer import Explainer
from xpm.features.stats import Float64Array
from xpm.model import registry
from xpm.model.dataset import build_training_matrix

app = typer.Typer(add_completion=False, help=__doc__)

#: backend.md §4: "asserts the probability moves in the expected direction for
#: >= 90 % of alerts".
DEFAULT_MIN_FRACTION: Final[float] = 0.90

#: Filename ``xpm.model.evaluate.load_faithfulness`` looks for.
REPORT_NAME: Final[str] = "faithfulness.json"


@dataclass(frozen=True, slots=True)
class PlantFaithfulness:
    """One plant's result."""

    plant_id: str
    model_id: str
    n_test_rows: int
    n_alerts: int
    fraction_expected_direction: float | None
    """``None`` when the plant produced no alert-level rows at all."""
    mean_abs_delta: float | None
    probability_threshold: float
    passed: bool


def evaluate_plant(
    plant_id: PlantId, *, root: Path, min_fraction: float
) -> tuple[PlantFaithfulness, dict[str, Any]]:
    """Ablate the top feature of every alert-level held-out row of one plant."""
    settings = get_settings()
    explainer = Explainer.load(plant_id, settings.model.served, root=root)
    matrix = build_training_matrix(plant_id)
    held_out: Float64Array = np.asarray(matrix.x_test, dtype=np.float64)
    probabilities = explainer.probabilities(held_out)
    threshold = settings.alerting.probability_threshold
    alerts = np.flatnonzero(probabilities >= threshold)

    if alerts.size == 0:
        result = PlantFaithfulness(
            plant_id=plant_id,
            model_id=explainer.model_id,
            n_test_rows=int(held_out.shape[0]),
            n_alerts=0,
            fraction_expected_direction=None,
            mean_abs_delta=None,
            probability_threshold=threshold,
            passed=False,
        )
        return result, {"expected": 0, "total": 0}

    rows = held_out[alerts]
    shap_rows = explainer.shap_rows(rows)
    medians = explainer.background_medians()

    ablated = rows.copy()
    top_shap = np.empty(len(shap_rows), dtype=np.float64)
    for position, row in enumerate(shap_rows):
        column = int(np.argmax(np.abs(row.values)))
        top_shap[position] = row.values[column]
        ablated[position, column] = medians[column]

    before = np.asarray([row.probability for row in shap_rows], dtype=np.float64)
    after = explainer.probabilities(ablated)
    delta = after - before
    expected = np.where(top_shap > 0.0, delta < 0.0, delta > 0.0)

    fraction = float(expected.mean())
    result = PlantFaithfulness(
        plant_id=plant_id,
        model_id=explainer.model_id,
        n_test_rows=int(held_out.shape[0]),
        n_alerts=int(alerts.size),
        fraction_expected_direction=fraction,
        mean_abs_delta=float(np.abs(delta).mean()),
        probability_threshold=threshold,
        passed=fraction >= min_fraction,
    )
    return result, {"expected": int(expected.sum()), "total": int(expected.size)}


def build_report(
    results: list[PlantFaithfulness], counts: list[dict[str, Any]], *, min_fraction: float
) -> dict[str, Any]:
    """The body of ``reports/faithfulness.json``.

    Top-level keys are scalars on purpose: ``xpm.model.evaluate.render_markdown``
    inlines exactly the scalar keys into ``docs/EVALUATION.md``'s faithfulness
    table and skips the nested per-plant block.
    """
    settings = get_settings()
    total = sum(item["total"] for item in counts)
    expected = sum(item["expected"] for item in counts)
    pooled = expected / total if total else None
    weighted = [
        result.mean_abs_delta * result.n_alerts
        for result in results
        if result.mean_abs_delta is not None
    ]
    alerts = sum(result.n_alerts for result in results)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": (
            "ablate the top-|SHAP| feature of every held-out row scored at or above "
            "alerting.probability_threshold to its median in the frozen SHAP background, "
            "then re-score with the same explainer configuration"
        ),
        "shap_space": "probability",
        "feature_perturbation": settings.model.shap.feature_perturbation,
        "background_rows": settings.model.shap.background_rows,
        "probability_threshold": settings.alerting.probability_threshold,
        "min_fraction": min_fraction,
        "n_alerts": alerts,
        "fraction_expected_direction": pooled,
        "mean_abs_delta": (sum(weighted) / alerts) if alerts else None,
        "passed": bool(pooled is not None and pooled >= min_fraction),
        "plants": {result.plant_id: asdict(result) for result in results},
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    """Write the JSON ``scripts/evaluate.py`` reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@app.command()
def main(
    plant: Annotated[str, typer.Option(help="ai4i, ims or all.")] = "all",
    models_dir: Annotated[
        Path | None, typer.Option(help="Registry root; defaults to paths.models_dir.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Output JSON; defaults to reports/faithfulness.json.")
    ] = None,
    min_fraction: Annotated[
        float, typer.Option(help="Required fraction of alerts moving the expected way.")
    ] = DEFAULT_MIN_FRACTION,
    strict: Annotated[
        bool, typer.Option("--strict/--no-strict", help="Exit non-zero when the gate fails.")
    ] = True,
) -> None:
    """Measure explanation faithfulness and write ``reports/faithfulness.json``."""
    root = models_dir if models_dir is not None else registry.registry_root()
    targets: tuple[PlantId, ...] = PLANT_IDS if plant == "all" else (_plant_id(plant),)

    results: list[PlantFaithfulness] = []
    counts: list[dict[str, Any]] = []
    for plant_id in targets:
        result, count = evaluate_plant(plant_id, root=root, min_fraction=min_fraction)
        results.append(result)
        counts.append(count)
        typer.echo(json.dumps(asdict(result), sort_keys=True))

    report = build_report(results, counts, min_fraction=min_fraction)
    destination = out if out is not None else reports_dir() / REPORT_NAME
    write_report(report, destination)
    typer.echo(f"wrote {destination}")
    if strict and not report["passed"]:
        raise typer.Exit(code=1)


def _plant_id(value: str) -> PlantId:
    if value not in PLANT_IDS:
        raise typer.BadParameter(f"{value!r} is not one of {PLANT_IDS} or 'all'")
    return "ai4i" if value == "ai4i" else "ims"


if __name__ == "__main__":
    app()
