"""Held-out metrics, the calibration diagnostic and the ablation table.

Metrics are asserted against *bounds* (``expected_metrics_bounds.json``), not
point values, so a library patch release does not fail the build while a real
modelling regression still does. The ablation is asserted per plant and only for
being computed, finite and written down: R4 forbids asserting that windowed
features beat raw ones on AI4I, and fabricating such a lift is worse than
reporting none.

R16 is asserted three ways: exactly one ``brier`` and one ``ece`` per model, the
calibration curve has ``model.evaluation.calibration_bins`` points, and the
generated document states in words that nothing applies a calibrator at serving
time.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from xpm.config import get_settings
from xpm.contracts.common import PLANT_IDS
from xpm.data import loader
from xpm.features.registry import feature_names
from xpm.model import ablation, evaluate, registry, train
from xpm.model.dataset import TrainingMatrix, build_training_matrix

from . import METRICS_BOUNDS_PATH, TINY_PLANT, tiny_matrix

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def bounds() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(METRICS_BOUNDS_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory: pytest.TempPathFactory) -> evaluate.PlantEvaluation:
    """Train the tiny fixture, then evaluate it straight out of the registry."""
    root = tmp_path_factory.mktemp("evaluated")
    matrix = tiny_matrix()
    train.train_plant(TINY_PLANT, matrix=matrix, root=root, data_sha256="0" * 64)
    return evaluate.evaluate_plant(
        TINY_PLANT, matrix, root=root, ablations=ablation.run_ablation(matrix)
    )


def _within(value: float, span: list[float]) -> bool:
    return span[0] <= value <= span[1]


def test_split_sizes_are_within_bounds(
    evaluated: evaluate.PlantEvaluation, bounds: dict[str, Any]
) -> None:
    limits = bounds["split"]
    assert evaluated.n_train_rows >= limits["min_train_rows"]
    assert evaluated.n_test_rows >= limits["min_test_rows"]
    assert evaluated.train_positives >= limits["min_train_positives"]
    assert evaluated.test_positives >= limits["min_test_positives"]
    assert evaluated.n_features == len(feature_names(TINY_PLANT))


def test_every_metric_is_within_its_bound(
    evaluated: evaluate.PlantEvaluation, bounds: dict[str, Any]
) -> None:
    assert {model.family for model in evaluated.models} == {"lgbm", "rf"}
    for model in evaluated.models:
        limits = bounds["models"][model.family]
        metrics = model.metrics
        for name, span in limits.items():
            assert _within(getattr(metrics, name), span), f"{model.family}.{name}"
        assert metrics.n_rows == evaluated.n_test_rows
        assert metrics.threshold == get_settings().alerting.probability_threshold
        assert (
            metrics.true_positives
            + metrics.false_positives
            + metrics.true_negatives
            + metrics.false_negatives
            == metrics.n_rows
        )
    assert [model.is_served for model in evaluated.models] == [True, False]


def test_summary_reports_exactly_one_brier_and_one_ece(
    evaluated: evaluate.PlantEvaluation,
) -> None:
    """R16: there is one probability, so there is one of each score."""
    for model in evaluated.models:
        summary = model.metrics.summary()
        assert [key for key in summary if "brier" in key] == ["brier"]
        assert [key for key in summary if "ece" in key] == ["ece"]
        assert set(summary) == {"pr_auc", "roc_auc", "recall_at_p80", "f1", "brier", "ece"}


def test_calibration_diagnostic_has_the_configured_bins(
    evaluated: evaluate.PlantEvaluation,
) -> None:
    configured = get_settings().model.evaluation.calibration_bins
    for model in evaluated.models:
        curve = model.metrics.reliability
        assert len(curve) == configured
        assert sum(point.count for point in curve) == model.metrics.n_rows
        assert math.isfinite(model.metrics.brier)
        assert math.isfinite(model.metrics.ece)
        assert curve[0].lower == 0.0
        assert curve[-1].upper == 1.0


def test_ablation_is_computed_per_plant_and_finite(
    evaluated: evaluate.PlantEvaluation, bounds: dict[str, Any]
) -> None:
    """R4: both numbers exist and are finite. No assertion that windowed wins."""
    groups = [item.group for item in evaluated.ablations]
    assert groups[0] == ablation.FULL_GROUP
    assert len(groups) >= bounds["ablation"]["min_groups"]
    assert len(set(groups)) == len(groups)
    for item in evaluated.ablations:
        assert item.plant_id == TINY_PLANT
        assert _within(item.auprc, bounds["ablation"]["auprc"])
        assert math.isfinite(item.auroc)
        assert math.isfinite(item.delta_auprc)
        assert 0 < item.n_features <= evaluated.n_features
    assert evaluated.ablations[0].delta_auprc == 0.0


def test_ablation_skips_groups_that_do_not_apply() -> None:
    """AI4I has no vibration-like channel, so "drop the bands" is not a row."""
    matrix = tiny_matrix()
    groups = {group.name for group in ablation.feature_groups()}
    assert "no_vibration_bands" in groups
    selected = {
        group.name
        for group in ablation.feature_groups()
        if ablation.select_columns(TINY_PLANT, group, matrix.feature_names)
    }
    ran = {item.group for item in ablation.run_ablation(matrix)}
    assert "no_vibration_bands" not in ran
    assert ran <= selected


def test_a_group_that_keeps_nothing_is_not_a_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """A group that applies to no feature of this plant is skipped, not
    reported as an ablation with zero features."""
    empty = ablation.FeatureGroup("nothing", "Keeps no feature", lambda meta: False)
    monkeypatch.setattr(
        ablation, "GROUPS", (ablation.feature_groups()[0], ablation.feature_groups()[1], empty)
    )
    groups = [item.group for item in ablation.run_ablation(tiny_matrix())]
    assert "nothing" not in groups


def test_build_training_matrix_runs_the_real_feature_path() -> None:
    """The path ``make train`` takes, on two machines of the committed parquet."""
    frame = loader.load_plant("ai4i")
    subset = frame[frame["machine_id"].isin(["ai4i-01", "ai4i-02"])]
    matrix = build_training_matrix("ai4i", frame=subset)
    assert matrix.warmup_rows_dropped > 0
    assert matrix.n_train_rows + matrix.n_test_rows + matrix.warmup_rows_dropped == len(subset)
    assert matrix.feature_names == feature_names("ai4i")


def test_ims_groups_include_the_vibration_bands() -> None:
    """The IMS side of the per-plant ablation, without fitting the real model."""
    names = feature_names("ims")
    for group in ablation.feature_groups():
        columns = ablation.select_columns("ims", group, names)
        assert columns, group.name
        if group.name == "no_vibration_bands":
            assert len(columns) < len(names)


def test_report_documents_the_numbers_and_the_caveats(
    evaluated: evaluate.PlantEvaluation, tmp_path: Path
) -> None:
    report = evaluate.build_report([evaluated], notes=evaluate.default_notes([evaluated]))
    document = tmp_path / "EVALUATION.md"
    metrics_path = tmp_path / "reports" / "metrics.json"
    evaluate.write_report(report, document=document, metrics_path=metrics_path)

    text = document.read_text(encoding="utf-8")
    assert "No isotonic or Platt calibrator exists anywhere in this system" in text
    assert "Calibration diagnostic (not applied at serving time)" in text
    assert "Feature-group ablation" in text
    assert "simulation convenience (ADR-024)" in text
    assert f"`{evaluated.models[0].model_id}`" in text
    assert "faithfulness" in text.lower()
    assert "n/a" in text, "empty reliability bins render as n/a, never as 0"

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["plants"][0]["plant_id"] == TINY_PLANT
    assert payload["plants"][0]["ablations"]
    assert payload["environment"]["lightgbm"]
    assert payload["faithfulness"] is None
    assert set(payload["notes"]) == {TINY_PLANT}


def test_report_inlines_a_faithfulness_file_when_one_exists(
    evaluated: evaluate.PlantEvaluation, tmp_path: Path
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    assert evaluate.load_faithfulness(reports) is None
    (reports / "faithfulness.json").write_text(
        json.dumps({"alerts": 12, "agreement": 0.95, "detail": {"skipped": 0}}),
        encoding="utf-8",
    )
    loaded = evaluate.load_faithfulness(reports)
    assert loaded is not None
    report = evaluate.build_report([evaluated], faithfulness=loaded)
    text = evaluate.render_markdown(report)
    assert "| `agreement` | 0.95 |" in text
    assert "was absent when" not in text


def test_notes_cover_every_plant() -> None:
    assert set(evaluate.PLANT_CAVEATS) == set(PLANT_IDS)
    assert "ims-01" in evaluate.PLANT_CAVEATS["ims"]


def test_scoring_rejects_degenerate_splits() -> None:
    with pytest.raises(ValueError, match="empty held-out split"):
        evaluate.score_predictions(np.array([], dtype=np.int64), np.array([]))
    with pytest.raises(ValueError, match="single class"):
        evaluate.score_predictions(np.zeros(4, dtype=np.int64), np.full(4, 0.5))
    with pytest.raises(ValueError, match="zero rows"):
        evaluate.expected_calibration_error((), 0)


def test_unreachable_target_precision_reports_zero_recall() -> None:
    """A model that never reaches the target precision gets 0.0, not a gap."""
    labels = np.array([0, 1, 0, 1, 0, 0, 0, 0, 0, 0], dtype=np.int64)
    proba = np.array([0.9, 0.1, 0.85, 0.2, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55])
    metrics = evaluate.score_predictions(labels, proba)
    assert metrics.recall_at_target_precision == 0.0
    assert metrics.precision < get_settings().model.evaluation.target_precision


def test_perfect_and_empty_threshold_cases_are_scored() -> None:
    labels = np.array([0, 0, 1, 1], dtype=np.int64)
    below = evaluate.score_predictions(labels, np.array([0.0, 0.0, 0.1, 0.2]))
    assert below.true_positives == 0
    assert below.precision == 0.0
    assert below.f1 == 0.0
    perfect = evaluate.score_predictions(labels, np.array([0.0, 0.05, 0.95, 1.0]))
    assert perfect.f1 == pytest.approx(1.0)
    assert perfect.auprc == pytest.approx(1.0)


def test_reliability_curve_places_the_edges() -> None:
    labels = np.array([0, 1, 0, 1], dtype=np.int64)
    proba = np.array([0.0, 1.0, 0.45, 0.55])
    curve = evaluate.reliability_curve(labels, proba, bins=2)
    assert [point.count for point in curve] == [2, 2]
    assert curve[0].observed_rate == pytest.approx(0.0)
    assert curve[1].observed_rate == pytest.approx(1.0)


def test_predict_proba_handles_both_artefact_shapes(
    evaluated: evaluate.PlantEvaluation, tmp_path_factory: pytest.TempPathFactory
) -> None:
    root = tmp_path_factory.mktemp("proba")
    matrix = tiny_matrix()
    train.train_plant(TINY_PLANT, matrix=matrix, root=root, data_sha256="0" * 64)
    for family in ("lgbm", "rf"):
        entry = registry.resolve_version(root, TINY_PLANT, family)
        model = registry.load_model(entry)
        proba = evaluate.predict_proba(entry, model, matrix.x_test)
        assert proba.shape == (matrix.n_test_rows,)
        assert ((proba >= 0.0) & (proba <= 1.0)).all()


def test_run_evaluation_scores_a_whole_plant(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The orchestration ``scripts/evaluate.py`` calls, on the tiny fixture."""
    root = tmp_path_factory.mktemp("run-evaluation")
    matrix = tiny_matrix()
    train.train_plant(TINY_PLANT, matrix=matrix, root=root, data_sha256="0" * 64)
    monkeypatch.setattr(evaluate, "build_training_matrix", lambda plant_id, settings=None: matrix)
    report = evaluate.run_evaluation([TINY_PLANT], root=root, ablation_runner=ablation.run_ablation)
    assert len(report.plants) == 1
    assert report.plants[0].ablations
    assert report.notes[TINY_PLANT]
    assert report.generated_at.endswith("Z")

    without = evaluate.run_evaluation([TINY_PLANT], root=root)
    assert without.plants[0].ablations == ()


def test_ims_evaluation_path_works_on_a_synthetic_matrix(tmp_path: Path) -> None:
    """IMS has 198 features and its own label column; exercise that branch
    without fitting on the real bearing data."""
    names = feature_names("ims")
    generator = np.random.default_rng(0)
    rows = 60
    features = generator.normal(size=(rows, len(names)))
    labels = (features[:, 0] > 0.5).astype(np.int64)
    labels[:5] = 1
    labels[5:10] = 0
    stamps = pd.date_range("2004-02-12", periods=rows, freq="10min", tz="UTC")
    index = pd.DataFrame({"machine_id": ["ims-01"] * rows, "dataset_ts": stamps})
    matrix = TrainingMatrix(
        plant_id="ims",
        feature_names=names,
        x_train=features[:40],
        y_train=labels[:40],
        x_test=features[40:],
        y_test=labels[40:],
        train_index=index.iloc[:40].reset_index(drop=True),
        test_index=index.iloc[40:].reset_index(drop=True),
        label="failure_imminent",
        split_ts=stamps[40].to_pydatetime(),
        warmup_rows_dropped=7,
    )
    train.train_plant("ims", matrix=matrix, root=tmp_path, data_sha256="0" * 64)
    evaluation = evaluate.evaluate_plant("ims", matrix, root=tmp_path)
    assert evaluation.label == "failure_imminent"
    assert evaluation.n_features == len(names)
    assert evaluation.warmup_rows_dropped == 7
    card = (registry.resolve_version(tmp_path, "ims", "lgbm").artefact("model_card.md")).read_text(
        encoding="utf-8"
    )
    assert "ims-01" in card
    assert "associations learned from historical data" in card
    assert "no isotonic or Platt calibrator".lower() in card.lower()


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"xpm_scripts_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_train_and_evaluate_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``make train`` then ``make evaluate``, wired exactly as the Makefile does,
    with the tiny matrix standing in for the full datasets."""
    matrix = tiny_matrix()
    monkeypatch.setattr(train, "build_training_matrix", lambda plant_id, settings=None: matrix)
    monkeypatch.setattr(evaluate, "build_training_matrix", lambda plant_id, settings=None: matrix)
    monkeypatch.setattr(
        train.loader, "load_manifest", lambda plant_id: {"parquet_sha256": "0" * 64}
    )
    runner = CliRunner()
    root = tmp_path / "registry"

    train_cli = _load_script("train")
    result = runner.invoke(train_cli.app, ["--plant", "ai4i", "--models-dir", str(root)])
    assert result.exit_code == 0, result.output
    assert "lgbm@1.0.0" in result.output
    assert registry.resolve_version(root, TINY_PLANT).version == "1.0.0"

    evaluate_cli = _load_script("evaluate")
    document = tmp_path / "EVALUATION.md"
    monkeypatch.setattr(evaluate_cli, "reports_dir", lambda: tmp_path / "reports")
    result = runner.invoke(
        evaluate_cli.app,
        [
            "--plant",
            "ai4i",
            "--no-ablation",
            "--models-dir",
            str(root),
            "--document",
            str(document),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "# Model evaluation" in document.read_text(encoding="utf-8")
    assert (tmp_path / "reports" / "metrics.json").is_file()
