"""The committed ``contracts/openapi.json`` must match what the exporter emits.

This is the frontend's drift alarm: ``web/src/contracts/api.ts`` is generated
from the committed artefact, so a model change that is not re-exported would
silently give the dashboard a stale type. ``make contracts-check`` runs the same
comparison in CI.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTER = REPO_ROOT / "scripts" / "export_openapi.py"
COMMITTED = REPO_ROOT / "contracts" / "openapi.json"


def _load_exporter() -> ModuleType:
    """Import ``scripts/export_openapi.py`` by path; ``scripts`` is not a package."""
    spec = importlib.util.spec_from_file_location("xpm_export_openapi", EXPORTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Re-export through the CLI, exactly as ``make contracts-check`` does."""
    out = tmp_path_factory.mktemp("openapi") / "openapi.json"
    subprocess.run(
        [sys.executable, str(EXPORTER), "--out", str(out)],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return out.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    return json.loads(COMMITTED.read_text(encoding="utf-8"))


def test_committed_artefact_is_current(exported: str) -> None:
    assert exported == COMMITTED.read_text(encoding="utf-8"), (
        "contracts/openapi.json is stale — run `make contracts` and commit the result"
    )


def test_serialisation_is_deterministic(document: dict[str, Any]) -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    assert text == json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert text.endswith("}\n")


def test_every_planned_route_is_present(document: dict[str, Any]) -> None:
    """backend.md §3.4's endpoint table, method by method."""
    expected = {
        ("/api/health", "get"),
        ("/api/plants", "get"),
        ("/api/machines", "get"),
        ("/api/machines/{machine_id}", "get"),
        ("/api/machines/{machine_id}/importance", "get"),
        ("/api/telemetry", "get"),
        ("/api/risk", "get"),
        ("/api/alerts", "get"),
        ("/api/alerts/{alert_id}", "get"),
        ("/api/alerts/{alert_id}/explanation", "get"),
        ("/api/alerts/{alert_id}/compare", "get"),
        ("/api/state_at", "get"),
        ("/api/whatif", "post"),
        ("/api/config", "get"),
        ("/api/config", "put"),
        ("/api/replay", "get"),
        ("/api/replay/command", "post"),
        ("/api/models", "get"),
    }
    actual = {
        (path, method) for path, operations in document["paths"].items() for method in operations
    }
    assert actual == expected


@pytest.mark.parametrize(
    ("path", "schema_name"),
    [
        ("/api/health", "HealthResponse"),
        ("/api/machines/{machine_id}", "MachineDetail"),
        ("/api/telemetry", "TelemetrySeries"),
        ("/api/risk", "RiskSeries"),
        ("/api/alerts", "AlertPage"),
        ("/api/alerts/{alert_id}", "Alert"),
        ("/api/alerts/{alert_id}/explanation", "Explanation"),
        ("/api/alerts/{alert_id}/compare", "ModelComparison"),
        ("/api/machines/{machine_id}/importance", "GlobalImportance"),
        ("/api/state_at", "PlantSnapshot"),
        ("/api/config", "ConfigResponse"),
        ("/api/replay", "ReplayState"),
    ],
)
def test_response_models(document: dict[str, Any], path: str, schema_name: str) -> None:
    ok = document["paths"][path]["get"]["responses"]["200"]
    ref = ok["content"]["application/json"]["schema"]
    assert ref == {"$ref": f"#/components/schemas/{schema_name}"}


@pytest.mark.parametrize(
    ("path", "schema_name"),
    [("/api/plants", "Plant"), ("/api/machines", "MachineSummary"), ("/api/models", "ModelInfo")],
)
def test_bare_list_responses(document: dict[str, Any], path: str, schema_name: str) -> None:
    """Paging envelopes appear only on ``AlertPage``; the rest are bare arrays."""
    ok = document["paths"][path]["get"]["responses"]["200"]
    schema = ok["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": f"#/components/schemas/{schema_name}"}


def test_replay_speed_enum_is_pinned(document: dict[str, Any]) -> None:
    """The frontend derives its ``Speed`` type from this enum (§3.3)."""
    speed = document["components"]["schemas"]["ReplayCommand"]["properties"]["speed"]
    assert {"enum": [0.5, 1.0, 5.0, 20.0], "type": "number"} in speed["anyOf"]
    assert {"type": "null"} in speed["anyOf"]
    assert len(speed["anyOf"]) == 2


def test_errors_use_the_problem_media_type(document: dict[str, Any]) -> None:
    not_found = document["paths"]["/api/alerts/{alert_id}"]["get"]["responses"]["404"]
    assert not_found["content"] == {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    immutable = document["paths"]["/api/config"]["put"]["responses"]["409"]
    assert "application/problem+json" in immutable["content"]


def test_two_clocks_are_iso_strings_in_the_schema(document: dict[str, Any]) -> None:
    alert = document["components"]["schemas"]["Alert"]["properties"]
    for field in ("ts", "dataset_ts"):
        assert alert[field]["type"] == "string"
        assert alert[field]["format"] == "date-time"
    closed = alert["closed_dataset_ts"]["anyOf"]
    assert {"format": "date-time", "type": "string"} in closed
    assert {"type": "null"} in closed


def test_shap_space_is_a_closed_literal(document: dict[str, Any]) -> None:
    for schema_name in ("Explanation", "WhatIfResponse"):
        prop = document["components"]["schemas"][schema_name]["properties"]["shap_space"]
        assert prop["const"] == "probability"


def test_no_error_response_is_plain_json(document: dict[str, Any]) -> None:
    """backend.md §3.4 grants no carve-out: every 4xx/5xx body is a problem.

    FastAPI's own 422 would otherwise be ``application/json`` +
    ``HTTPValidationError``, so this also pins the exporter's 422 declaration.
    """
    offenders = [
        (path, method, status, media_type)
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
        for status, response in operation["responses"].items()
        if status[0] in {"4", "5"}
        for media_type in response.get("content", {})
        if media_type != "application/problem+json"
    ]
    assert offenders == []


def test_every_operation_declares_a_problem_validation_error(
    document: dict[str, Any],
) -> None:
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            response = operation["responses"].get("422")
            assert response is not None, f"{method.upper()} {path} has no 422"
            assert response["content"] == {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            }


def test_fastapi_default_error_schemas_are_absent(document: dict[str, Any]) -> None:
    schemas = document["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_exporter_max_points_matches_the_settings_default() -> None:
    """The literal pinned in the exporter may not drift from the settings default.

    ``scripts/export_openapi.py`` deliberately does not call ``get_settings()``:
    an ``XPM_API__MAX_SERIES_POINTS`` override in the exporting shell would
    silently rewrite the committed artefact. This is the guard that keeps the
    pinned literal honest.
    """
    exporter = _load_exporter()
    configured = yaml.safe_load(
        (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    )
    assert configured["api"]["max_series_points"] == exporter.DEFAULT_MAX_SERIES_POINTS
    telemetry = json.loads(COMMITTED.read_text(encoding="utf-8"))["paths"]["/api/telemetry"]
    max_points = next(
        param for param in telemetry["get"]["parameters"] if param["name"] == "max_points"
    )
    assert max_points["schema"]["default"] == exporter.DEFAULT_MAX_SERIES_POINTS
