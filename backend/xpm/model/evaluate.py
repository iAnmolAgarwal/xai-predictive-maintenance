"""Held-out metrics, the calibration **diagnostic**, and ``docs/EVALUATION.md``.

Everything here is measurement. Nothing here is in the serving path: there is
exactly one probability in this system and it is the model's own (R16,
ADR-016). The reliability curve, Brier score and ECE below exist so a reader can
see **how** calibrated that one probability is; no isotonic or Platt mapping is
fitted, stored or applied, and a badly calibrated model is fixed in training
(``class_weight`` / ``scale_pos_weight`` / ``alerting.probability_threshold``).

Thresholded metrics use ``alerting.probability_threshold`` — the same number the
pipeline alerts on — so the confusion matrix in the document is the confusion
matrix the running system would have produced on the held-out window.

The ablation table is produced by :mod:`xpm.model.ablation` and passed in as
data (:class:`AblationResult`), which keeps this module free of any import of
the fitting code it reports on.
"""

from __future__ import annotations

import json
import platform
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)

from xpm.config import get_settings
from xpm.contracts.common import MODEL_KINDS, ModelKind, PlantId
from xpm.contracts.settings import Settings
from xpm.model import registry
from xpm.model.dataset import TrainingMatrix, build_training_matrix
from xpm.model.registry import ModelVersion

__all__ = [
    "AblationResult",
    "CalibrationBin",
    "EvaluationReport",
    "ModelEvaluation",
    "ModelMetrics",
    "PlantEvaluation",
    "build_report",
    "default_notes",
    "evaluate_plant",
    "predict_proba",
    "reliability_curve",
    "render_markdown",
    "run_evaluation",
    "score_predictions",
    "write_report",
]

Probabilities = np.ndarray[tuple[int, ...], np.dtype[np.float64]]
Labels = np.ndarray[tuple[int, ...], np.dtype[np.int64]]
#: Injected by ``scripts/evaluate.py`` so this module never imports the fitting
#: code it reports on (see :func:`run_evaluation`).
AblationRunner = Callable[[TrainingMatrix], Sequence["AblationResult"]]


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    """One point of the reliability curve (diagnostic only — R16)."""

    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    """Held-out metrics of one model on one plant."""

    n_rows: int
    n_positives: int
    positive_rate: float
    auroc: float
    auprc: float
    threshold: float
    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    target_precision: float
    recall_at_target_precision: float
    brier: float
    ece: float
    reliability: tuple[CalibrationBin, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reliability"] = [point.to_dict() for point in self.reliability]
        return payload

    def summary(self) -> dict[str, float]:
        """``ModelInfo.metrics``: one ``brier``, one ``ece`` (R16)."""
        return {
            "pr_auc": self.auprc,
            "roc_auc": self.auroc,
            "recall_at_p80": self.recall_at_target_precision,
            "f1": self.f1,
            "brier": self.brier,
            "ece": self.ece,
        }


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    """One registry version's metrics, with the identity to print beside them."""

    plant_id: PlantId
    family: ModelKind
    version: str
    model_id: str
    is_served: bool
    metrics: ModelMetrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "plant_id": self.plant_id,
            "family": self.family,
            "version": self.version,
            "model_id": self.model_id,
            "is_served": self.is_served,
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AblationResult:
    """One feature-group ablation, reported per plant and honestly (R4).

    Declared here rather than in :mod:`xpm.model.ablation` so that this module
    can render the table without importing the module that fits the models.
    """

    plant_id: PlantId
    group: str
    description: str
    n_features: int
    auprc: float
    auroc: float
    delta_auprc: float
    """``auprc`` minus the full-vector ``auprc``; negative means the drop hurt."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PlantEvaluation:
    """Both models of one plant, plus the split arithmetic they were scored on."""

    plant_id: PlantId
    label: str
    split_ts: str
    n_train_rows: int
    n_test_rows: int
    train_positives: int
    test_positives: int
    warmup_rows_dropped: int
    n_features: int
    models: tuple[ModelEvaluation, ...]
    ablations: tuple[AblationResult, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["models"] = [model.to_dict() for model in self.models]
        payload["ablations"] = [item.to_dict() for item in self.ablations]
        return payload


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """The body of ``reports/metrics.json`` and of ``docs/EVALUATION.md``."""

    generated_at: str
    environment: dict[str, str]
    plants: tuple[PlantEvaluation, ...]
    faithfulness: dict[str, Any] | None = None
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "environment": self.environment,
            "plants": [plant.to_dict() for plant in self.plants],
            "faithfulness": self.faithfulness,
            "notes": self.notes,
        }


def predict_proba(entry: ModelVersion, model: Any, features: np.ndarray[Any, Any]) -> Probabilities:
    """Positive-class probability from either family's serialised scorer.

    The LightGBM artefact is a native ``Booster`` (not an ``LGBMClassifier``),
    whose ``predict`` already returns the positive-class probability for a
    binary objective and which takes a bare array. The RandomForest keeps
    scikit-learn's two-column ``predict_proba`` and was fitted with named
    columns, so it is handed a frame with the version's own feature order.
    """
    if entry.family == "lgbm":
        return np.asarray(model.predict(features), dtype=np.float64)
    frame = pd.DataFrame(features, columns=list(entry.feature_names()))
    return np.asarray(model.predict_proba(frame)[:, 1], dtype=np.float64)


def reliability_curve(
    labels: Labels, proba: Probabilities, *, bins: int
) -> tuple[CalibrationBin, ...]:
    """Equal-width reliability curve over ``model.evaluation.calibration_bins``.

    Empty bins are kept, with ``count == 0`` and ``NaN`` rates, so the curve has
    exactly ``bins`` points and the dashboard/document can draw a fixed x-axis.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(proba, edges[1:-1], right=False), 0, bins - 1)
    points: list[CalibrationBin] = []
    for position in range(bins):
        mask = index == position
        count = int(mask.sum())
        points.append(
            CalibrationBin(
                lower=float(edges[position]),
                upper=float(edges[position + 1]),
                count=count,
                mean_probability=float(proba[mask].mean()) if count else float("nan"),
                observed_rate=float(labels[mask].mean()) if count else float("nan"),
            )
        )
    return tuple(points)


def expected_calibration_error(points: Sequence[CalibrationBin], total: int) -> float:
    """Count-weighted mean gap between confidence and observed frequency."""
    if total == 0:
        raise ValueError("cannot compute an ECE over zero rows")
    gap = sum(
        point.count * abs(point.mean_probability - point.observed_rate)
        for point in points
        if point.count
    )
    return float(gap / total)


def _recall_at_precision(labels: Labels, proba: Probabilities, target: float) -> float:
    """Best recall among the thresholds that reach ``target`` precision.

    A model that never reaches that precision scores ``0.0``, which is a real
    answer and is printed as such: ``precision_recall_curve`` always terminates
    at ``(precision=1, recall=0)``, so the maximum below is taken over a
    non-empty set and degrades to that terminal point.
    """
    precision, recall, _ = precision_recall_curve(labels, proba)
    return float(recall[precision >= target].max())


def score_predictions(
    labels: Labels, proba: Probabilities, *, settings: Settings | None = None
) -> ModelMetrics:
    """Every held-out number the report prints, for one model on one split."""
    resolved = settings if settings is not None else get_settings()
    evaluation = resolved.model.evaluation
    threshold = resolved.alerting.probability_threshold
    total = int(labels.shape[0])
    if total == 0:
        raise ValueError("cannot score an empty held-out split")
    positives = int(labels.sum())
    if positives in (0, total):
        raise ValueError("the held-out split has a single class; AUROC is undefined")

    predicted = proba >= threshold
    truth = labels.astype(bool)
    true_positives = int(np.logical_and(predicted, truth).sum())
    false_positives = int(np.logical_and(predicted, ~truth).sum())
    false_negatives = int(np.logical_and(~predicted, truth).sum())
    true_negatives = total - true_positives - false_positives - false_negatives
    precision = true_positives / (true_positives + false_positives) if predicted.any() else 0.0
    recall = true_positives / positives
    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0.0 else 0.0

    points = reliability_curve(labels, proba, bins=evaluation.calibration_bins)
    return ModelMetrics(
        n_rows=total,
        n_positives=positives,
        positive_rate=positives / total,
        auroc=float(roc_auc_score(labels, proba)),
        auprc=float(average_precision_score(labels, proba)),
        threshold=threshold,
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        target_precision=evaluation.target_precision,
        recall_at_target_precision=_recall_at_precision(labels, proba, evaluation.target_precision),
        brier=float(brier_score_loss(labels, proba)),
        ece=expected_calibration_error(points, total),
        reliability=points,
    )


def evaluate_version(
    entry: ModelVersion, matrix: TrainingMatrix, *, settings: Settings | None = None
) -> ModelMetrics:
    """Load a registry version and score it on ``matrix``'s held-out split."""
    model = registry.load_model(entry)
    proba = predict_proba(entry, model, matrix.x_test)
    return score_predictions(matrix.y_test, proba, settings=settings)


def evaluate_plant(
    plant_id: PlantId,
    matrix: TrainingMatrix,
    *,
    root: Path | None = None,
    settings: Settings | None = None,
    ablations: Sequence[AblationResult] = (),
) -> PlantEvaluation:
    """Score every registry family of ``plant_id`` on the same held-out split."""
    resolved = settings if settings is not None else get_settings()
    registry_path = root if root is not None else registry.registry_root()
    served = resolved.model.served
    evaluations: list[ModelEvaluation] = []
    for family in MODEL_KINDS:
        entry = registry.resolve_version(registry_path, plant_id, family)
        evaluations.append(
            ModelEvaluation(
                plant_id=plant_id,
                family=family,
                version=entry.version,
                model_id=entry.model_id,
                is_served=family == served,
                metrics=evaluate_version(entry, matrix, settings=resolved),
            )
        )
    return PlantEvaluation(
        plant_id=plant_id,
        label=matrix.label,
        split_ts=matrix.split_ts.isoformat().replace("+00:00", "Z"),
        n_train_rows=matrix.n_train_rows,
        n_test_rows=matrix.n_test_rows,
        train_positives=matrix.train_positives,
        test_positives=matrix.test_positives,
        warmup_rows_dropped=matrix.warmup_rows_dropped,
        n_features=matrix.n_features,
        models=tuple(evaluations),
        ablations=tuple(ablations),
    )


def environment_block() -> dict[str, str]:
    """Where the numbers in the document were produced."""
    import lightgbm as lgb
    import pandas as pd
    import sklearn

    return {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "lightgbm": str(lgb.__version__),
        "scikit_learn": str(sklearn.__version__),
    }


def build_report(
    plants: Sequence[PlantEvaluation],
    *,
    faithfulness: dict[str, Any] | None = None,
    notes: Mapping[str, str] | None = None,
) -> EvaluationReport:
    """Assemble the report object both output artefacts are rendered from."""
    return EvaluationReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        environment=environment_block(),
        plants=tuple(plants),
        faithfulness=faithfulness,
        notes=dict(notes or {}),
    )


def load_faithfulness(reports_dir: Path) -> dict[str, Any] | None:
    """``reports/faithfulness.json`` if ``scripts/faithfulness.py`` has run."""
    path = reports_dir / "faithfulness.json"
    if not path.is_file():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


#: Per-plant honesty notes printed under the tables. These are statements of
#: known limitations of the data, not of the code, and they are the reason R4
#: forbids reading the two plants' ablations as one result.
PLANT_CAVEATS: Mapping[PlantId, str] = {
    "ai4i": (
        "AI4I 2020 rows are i.i.d. product records. Dealing them round-robin into "
        "12 virtual machines and calling one row five minutes of dataset time is a "
        'simulation convenience (ADR-024), so this plant\'s "history" carries no '
        "real temporal structure. Windowed features are therefore **not** expected "
        "to beat the raw channels here, and the ablation above is reported as it "
        "came out. Failures are also the native `machine_failure` flag on the row "
        "itself, so the task is closer to detection than to prediction."
    ),
    "ims": (
        "IMS is real run-to-failure vibration, but only **one** bearing fails in "
        "test set 2. Every positive row in this plant — 144 of them, the last 24 h "
        "before end-of-record (ADR-023) — belongs to `ims-01`, so per-machine "
        "numbers are meaningless and the plant-level numbers describe a single "
        "failure event. The held-out window is correspondingly small and "
        "positive-rich (see the base rate above): read PR-AUC against that base "
        "rate, not against the AI4I one. A model that generalises to other "
        "bearings is not something this dataset can demonstrate. Read the "
        "near-perfect numbers above with that in mind: the held-out positives are "
        "the last hours of the same degradation ramp whose earlier hours are in "
        "the training split, so separating them is easy by construction. This is "
        "a statement about the dataset, not a claim about the model."
    ),
}


def default_notes(plants: Sequence[PlantEvaluation]) -> dict[str, str]:
    """The caveat paragraph for each evaluated plant."""
    return {plant.plant_id: PLANT_CAVEATS[plant.plant_id] for plant in plants}


def run_evaluation(
    plants: Sequence[PlantId],
    *,
    root: Path | None = None,
    settings: Settings | None = None,
    ablation_runner: AblationRunner | None = None,
    faithfulness: dict[str, Any] | None = None,
) -> EvaluationReport:
    """Score every plant's registry against a freshly rebuilt held-out split.

    ``ablation_runner`` is injected rather than imported so this module never
    depends on the fitting code it reports on; ``scripts/evaluate.py`` passes
    :func:`xpm.model.ablation.run_ablation`.
    """
    resolved = settings if settings is not None else get_settings()
    evaluations: list[PlantEvaluation] = []
    for plant_id in plants:
        matrix = build_training_matrix(plant_id, settings=resolved)
        ablations = ablation_runner(matrix) if ablation_runner is not None else ()
        evaluations.append(
            evaluate_plant(
                plant_id,
                matrix,
                root=root,
                settings=resolved,
                ablations=ablations,
            )
        )
    return build_report(evaluations, faithfulness=faithfulness, notes=default_notes(evaluations))


def _fmt(value: float, digits: int = 4) -> str:
    if not np.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _metric_rows(plant: PlantEvaluation) -> list[str]:
    rows = [
        "| model | served | ROC-AUC | PR-AUC | recall @ "
        f"precision {plant.models[0].metrics.target_precision:.2f} | "
        f"precision @ {plant.models[0].metrics.threshold:.2f} | recall | F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model in plant.models:
        metrics = model.metrics
        rows.append(
            f"| `{model.model_id}` | {'yes' if model.is_served else 'no'} | "
            f"{_fmt(metrics.auroc)} | {_fmt(metrics.auprc)} | "
            f"{_fmt(metrics.recall_at_target_precision)} | {_fmt(metrics.precision)} | "
            f"{_fmt(metrics.recall)} | {_fmt(metrics.f1)} |"
        )
    return rows


def _confusion_rows(plant: PlantEvaluation) -> list[str]:
    rows = ["| model | TP | FP | TN | FN |", "|---|---|---|---|---|"]
    for model in plant.models:
        metrics = model.metrics
        rows.append(
            f"| `{model.model_id}` | {metrics.true_positives} | {metrics.false_positives} | "
            f"{metrics.true_negatives} | {metrics.false_negatives} |"
        )
    return rows


def _calibration_rows(model: ModelEvaluation) -> list[str]:
    rows = [
        f"`{model.model_id}` — Brier {_fmt(model.metrics.brier)}, ECE {_fmt(model.metrics.ece)}",
        "",
        "| bin | rows | mean predicted | observed rate |",
        "|---|---|---|---|",
    ]
    for point in model.metrics.reliability:
        rows.append(
            f"| {point.lower:.1f} to {point.upper:.1f} | {point.count} | "
            f"{_fmt(point.mean_probability, 3)} | {_fmt(point.observed_rate, 3)} |"
        )
    return rows


def _ablation_rows(plant: PlantEvaluation) -> list[str]:
    rows = [
        "| feature group | features | PR-AUC | ROC-AUC | ΔPR-AUC vs full |",
        "|---|---|---|---|---|",
    ]
    for item in plant.ablations:
        rows.append(
            f"| {item.description} (`{item.group}`) | {item.n_features} | "
            f"{_fmt(item.auprc)} | {_fmt(item.auroc)} | {item.delta_auprc:+.4f} |"
        )
    return rows


def render_markdown(report: EvaluationReport) -> str:
    """``docs/EVALUATION.md``: machine-written, real numbers only."""
    lines: list[str] = [
        "# Model evaluation",
        "",
        "Machine-generated by `scripts/evaluate.py` (`make evaluate`). Every number "
        "below comes from the run stamped here; nothing is hand-edited.",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Python `{report.environment['python']}` on `{report.environment['platform']}`",
        f"- LightGBM `{report.environment['lightgbm']}`, "
        f"scikit-learn `{report.environment['scikit_learn']}`, "
        f"numpy `{report.environment['numpy']}`, pandas `{report.environment['pandas']}`",
        "",
        "## How to read this",
        "",
        "- Models are trained per plant: the two plants have different channels and "
        "therefore different feature vectors.",
        "- The split is `model.split: grouped_time` — a single cut in dataset time "
        "applied to every machine, so no feature window spans the cut and no "
        "machine has a training row later than one of its held-out rows. The cut "
        "is the later of the `1 - model.test_size` quantile of all rows and of "
        "the positive rows: on AI4I that is the plain last-20 %-of-time split, "
        "and on IMS it is what leaves any positives in the training split at all, "
        "since every IMS positive is in the final 24 h of the run.",
        "- Thresholded numbers use `alerting.probability_threshold`, the same "
        "threshold the live pipeline alerts on.",
        "- **Calibration below is a diagnostic.** No isotonic or Platt calibrator "
        "exists anywhere in this system: the served model's own probability is "
        "the number that is thresholded, stored, explained and drawn (R16, "
        "ADR-016). A poorly calibrated model is fixed in training, never by a "
        "second number on the wire.",
        "",
    ]
    for plant in report.plants:
        lines += [
            f"## Plant `{plant.plant_id}`",
            "",
            f"- Label column: `{plant.label}`",
            f"- Feature vector: {plant.n_features} features",
            f"- Warm-up rows dropped (incomplete 24 h windows): {plant.warmup_rows_dropped}",
            f"- Train: {plant.n_train_rows} rows, {plant.train_positives} positive",
            f"- Held out: {plant.n_test_rows} rows, {plant.test_positives} positive "
            f"(base rate {plant.test_positives / plant.n_test_rows:.4f})",
            f"- Split instant (first held-out row): `{plant.split_ts}`",
            "",
            "### Held-out metrics",
            "",
            *_metric_rows(plant),
            "",
            "### Confusion matrix at the alerting threshold",
            "",
            *_confusion_rows(plant),
            "",
            "### Calibration diagnostic (not applied at serving time)",
            "",
        ]
        for model in plant.models:
            lines += [*_calibration_rows(model), ""]
        if plant.ablations:
            lines += [
                "### Feature-group ablation",
                "",
                "Each row refits the served family on a subset of the feature vector "
                "and re-scores the same held-out split. Reported per plant and read "
                "honestly (R4, ADR-004): see the caveats below.",
                "",
                *_ablation_rows(plant),
                "",
            ]
        note = report.notes.get(plant.plant_id)
        if note:
            lines += ["### Caveats", "", note, ""]

    lines += ["## Explanation faithfulness", ""]
    if report.faithfulness is None:
        lines += [
            "Not included in this run: `reports/faithfulness.json` was absent when "
            "this document was generated. `scripts/faithfulness.py` writes it and "
            "`make evaluate` inlines it here on the next run.",
            "",
        ]
    else:
        lines += [
            "| metric | value |",
            "|---|---|",
            *(
                f"| `{key}` | {value} |"
                for key, value in sorted(report.faithfulness.items())
                if not isinstance(value, dict | list)
            ),
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def write_report(report: EvaluationReport, *, document: Path, metrics_path: Path) -> None:
    """Write ``docs/EVALUATION.md`` and ``reports/metrics.json``."""
    document.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(render_markdown(report), encoding="utf-8")
    metrics_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
