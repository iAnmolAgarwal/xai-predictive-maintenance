"""Training, evaluation and the versioned model registry (backend.md §1, §3.7).

Two models per plant: LightGBM is served, RandomForest is the comparison view
(ADR-026). Both are fitted by :func:`~xpm.model.train.train_plant` on the
windowed matrix :mod:`xpm.model.dataset` builds, frozen into
``models/registry/<plant>/<family>/<version>/`` together with the feature order,
the feature metadata and the 256-row interventional SHAP background (R3), and
scored by :mod:`xpm.model.evaluate`, which machine-writes ``docs/EVALUATION.md``.

**No post-hoc calibrator exists anywhere in this package** (R16, ADR-016): the
fitted model's own probability is the number the pipeline thresholds, the
dashboard prints and the SHAP waterfall closes on. Calibration is measured as a
diagnostic, never applied.

Downstream (T-SHAP, T-API) should enter through
:func:`~xpm.model.registry.resolve_version`, :func:`~xpm.model.registry.load_model`
and :func:`~xpm.model.registry.load_background`; those validate the feature
contract before returning anything.
"""

from __future__ import annotations

from xpm.model.background import sample_background
from xpm.model.dataset import TrainingMatrix, build_training_matrix, label_column
from xpm.model.evaluate import (
    AblationResult,
    EvaluationReport,
    ModelMetrics,
    PlantEvaluation,
    build_report,
    evaluate_plant,
    render_markdown,
    write_report,
)
from xpm.model.registry import (
    Manifest,
    ModelVersion,
    RegistryError,
    load_background,
    load_model,
    registry_root,
    resolve_version,
    validate_version,
)
from xpm.model.train import TrainedModel, train_plant

__all__ = [
    "AblationResult",
    "EvaluationReport",
    "Manifest",
    "ModelMetrics",
    "ModelVersion",
    "PlantEvaluation",
    "RegistryError",
    "TrainedModel",
    "TrainingMatrix",
    "build_report",
    "build_training_matrix",
    "evaluate_plant",
    "label_column",
    "load_background",
    "load_model",
    "registry_root",
    "render_markdown",
    "resolve_version",
    "sample_background",
    "train_plant",
    "validate_version",
    "write_report",
]
