#!/usr/bin/env python
"""Export the REST contract to ``contracts/openapi.json``.

The document this script emits **is** the contract: ``make contracts`` compiles
it to ``web/src/contracts/api.ts`` with ``openapi-typescript``, and
``make contracts-check`` re-exports into a temp directory and diffs, so any
drift between the models and the committed artefact fails CI.

The app built here is a route skeleton — every handler raises
``NotImplementedError``. ``T-API`` replaces the application; it does not replace
the shapes, which come from ``xpm.contracts``.

Usage::

    python scripts/export_openapi.py [--out contracts/openapi.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Query
from fastapi import Path as PathParam
from fastapi.openapi.utils import get_openapi

from xpm.config import get_settings
from xpm.contracts.common import AlertId, AlertSeverity, MachineId, ModelKind, PlantId
from xpm.contracts.mqtt import ReplayCommand, ReplayState
from xpm.contracts.rest import (
    Alert,
    AlertPage,
    ConfigPatch,
    ConfigResponse,
    Explanation,
    GlobalImportance,
    HealthResponse,
    MachineDetail,
    MachineSummary,
    ModelComparison,
    ModelInfo,
    Plant,
    PlantSnapshot,
    Problem,
    RiskSeries,
    TelemetrySeries,
    WhatIfRequest,
    WhatIfResponse,
)

#: The API contract version. Deliberately independent of the Python package
#: version so a packaging bump does not rewrite the committed artefact.
API_VERSION = "1.0.0"

#: Page sizes quoted in backend.md §3.4's endpoint table. They are transport
#: defaults rather than tunable business thresholds, so they are not settings
#: keys; `max_points` below *is* a settings key and is read from there.
DEFAULT_ALERT_PAGE_SIZE = 50
DEFAULT_IMPORTANCE_LIMIT = 20

_SETTINGS = get_settings()
DEFAULT_MAX_SERIES_POINTS = _SETTINGS.api.max_series_points

DEFAULT_OUT = Path("contracts") / "openapi.json"

#: Declared on every operation via the router default. FastAPI would otherwise
#: emit its own 422 as `application/json` + `HTTPValidationError`, which breaks
#: the rule that every error body in this system is an RFC-9457 problem
#: (backend.md §3.4). Declaring 422 ourselves suppresses that default.
VALIDATION_FAILED: dict[int | str, dict[str, Any]] = {
    422: {"model": Problem, "description": "Request validation failed"}
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": Problem, "description": "No such resource"}
}
IMMUTABLE: dict[int | str, dict[str, Any]] = {
    409: {"model": Problem, "description": "Key is not in mutable_keys"}
}

DESCRIPTION = """
REST surface of the explainable predictive-maintenance backend.

Two clocks are present on every payload: `ts` is wall-clock UTC and `dataset_ts`
is the simulated instant the row represents. Both are ISO-8601 strings; every
query, window, percentile, streak and scrub uses `dataset_ts`.

All SHAP quantities are in probability space, so a waterfall sums from
`base_value` to the probability shown on screen. Errors are RFC-9457
`application/problem+json` bodies.
"""

app = FastAPI(
    title="XPM — Explainable Predictive Maintenance API",
    version=API_VERSION,
    description=DESCRIPTION.strip(),
    openapi_url="/openapi.json",
)

#: Every route hangs off this router so `VALIDATION_FAILED` applies uniformly.
router = APIRouter(responses=VALIDATION_FAILED)


def _unimplemented() -> Any:
    """Every handler in the skeleton. T-API supplies the real implementations."""
    raise NotImplementedError("scripts/export_openapi.py only declares the contract")


@router.get("/api/health", response_model=HealthResponse, tags=["system"])
def get_health() -> Any:
    """Liveness, served model, current run and replay state."""
    return _unimplemented()


@router.get("/api/plants", response_model=list[Plant], tags=["plants"])
def list_plants() -> Any:
    """Every plant, with its canonical channel order. Bare list, no envelope."""
    return _unimplemented()


@router.get("/api/machines", response_model=list[MachineSummary], tags=["machines"])
def list_machines(plant_id: Annotated[PlantId | None, Query()] = None) -> Any:
    """Tile payloads for a plant. Bare list, no envelope."""
    return _unimplemented()


@router.get(
    "/api/machines/{machine_id}",
    response_model=MachineDetail,
    responses=NOT_FOUND,
    tags=["machines"],
)
def get_machine(machine_id: Annotated[MachineId, PathParam()]) -> Any:
    """One machine, including its channel list and alert count."""
    return _unimplemented()


@router.get(
    "/api/machines/{machine_id}/importance",
    response_model=GlobalImportance,
    responses=NOT_FOUND,
    tags=["explanations"],
)
def get_importance(
    machine_id: Annotated[MachineId, PathParam()],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_IMPORTANCE_LIMIT,
) -> Any:
    """Beeswarm-ready mean absolute SHAP across this machine's alerts."""
    return _unimplemented()


@router.get(
    "/api/telemetry",
    response_model=TelemetrySeries,
    responses=NOT_FOUND,
    tags=["series"],
)
def get_telemetry(
    machine_id: Annotated[MachineId, Query()],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    channels: Annotated[str | None, Query(description="Comma-separated channel names")] = None,
    max_points: Annotated[int, Query(ge=1)] = DEFAULT_MAX_SERIES_POINTS,
) -> Any:
    """Columnar channel history in dataset time, LTTB-downsampled server side."""
    return _unimplemented()


@router.get("/api/risk", response_model=RiskSeries, responses=NOT_FOUND, tags=["series"])
def get_risk(
    machine_id: Annotated[MachineId, Query()],
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    max_points: Annotated[int, Query(ge=1)] = DEFAULT_MAX_SERIES_POINTS,
) -> Any:
    """Columnar probability history with alert markers."""
    return _unimplemented()


@router.get("/api/alerts", response_model=AlertPage, tags=["alerts"])
def list_alerts(
    plant_id: Annotated[PlantId | None, Query()] = None,
    machine_id: Annotated[MachineId | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    severity: Annotated[AlertSeverity | None, Query()] = None,
    feature: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1)] = DEFAULT_ALERT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> Any:
    """The alert feed. The only paged endpoint in the API."""
    return _unimplemented()


@router.get("/api/alerts/{alert_id}", response_model=Alert, responses=NOT_FOUND, tags=["alerts"])
def get_alert(alert_id: Annotated[AlertId, PathParam()]) -> Any:
    """One alert, open or closed."""
    return _unimplemented()


@router.get(
    "/api/alerts/{alert_id}/explanation",
    response_model=Explanation,
    responses=NOT_FOUND,
    tags=["explanations"],
)
def get_explanation(
    alert_id: Annotated[AlertId, PathParam()],
    model: Annotated[ModelKind, Query()] = "lgbm",
) -> Any:
    """The stored explanation for an alert. Never recomputed."""
    return _unimplemented()


@router.get(
    "/api/alerts/{alert_id}/compare",
    response_model=ModelComparison,
    responses=NOT_FOUND,
    tags=["explanations"],
)
def compare_models(alert_id: Annotated[AlertId, PathParam()]) -> Any:
    """LightGBM against RandomForest for the same alert."""
    return _unimplemented()


@router.get("/api/state_at", response_model=PlantSnapshot, tags=["plants"])
def state_at(
    plant_id: Annotated[PlantId, Query()],
    dataset_ts: Annotated[datetime, Query()],
) -> Any:
    """The exact historical state at a dataset instant, for scrubbing."""
    return _unimplemented()


@router.post(
    "/api/whatif", response_model=WhatIfResponse, responses=NOT_FOUND, tags=["explanations"]
)
def whatif(body: WhatIfRequest) -> Any:
    """Recompute probability, SHAP and gradients under feature overrides."""
    return _unimplemented()


@router.get("/api/config", response_model=ConfigResponse, tags=["config"])
def get_config() -> Any:
    """The full flattened settings tree plus the mutable-key list."""
    return _unimplemented()


@router.put("/api/config", response_model=ConfigResponse, responses=IMMUTABLE, tags=["config"])
def put_config(body: ConfigPatch) -> Any:
    """Patch mutable settings; mints a new run id and broadcasts a config frame."""
    return _unimplemented()


@router.get("/api/replay", response_model=ReplayState, tags=["replay"])
def get_replay() -> Any:
    """Current transport state."""
    return _unimplemented()


@router.post("/api/replay/command", response_model=ReplayState, tags=["replay"])
def post_replay_command(body: ReplayCommand) -> Any:
    """The only authoritative transport control (R11)."""
    return _unimplemented()


@router.get("/api/models", response_model=list[ModelInfo], tags=["models"])
def list_models() -> Any:
    """Registry metadata for both families. Bare list, no envelope."""
    return _unimplemented()


app.include_router(router)


def _use_problem_media_type(document: dict[str, Any]) -> None:
    """Re-key ``Problem`` error bodies to ``application/problem+json`` (RFC-9457).

    FastAPI emits additional responses under ``application/json``; the wire
    format for errors in this system is ``application/problem+json``.
    """
    problem_ref = "#/components/schemas/Problem"
    for operations in document.get("paths", {}).values():
        for operation in operations.values():
            for response in operation.get("responses", {}).values():
                content = response.get("content", {})
                schema = content.get("application/json", {}).get("schema", {})
                if schema.get("$ref") == problem_ref:
                    response["content"] = {"application/problem+json": content["application/json"]}


def build_document() -> dict[str, Any]:
    """Build the OpenAPI document for the contract app."""
    document: dict[str, Any] = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    _use_problem_media_type(document)
    return document


def render(document: dict[str, Any]) -> str:
    """Serialise deterministically: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"destination file (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(build_document()), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
