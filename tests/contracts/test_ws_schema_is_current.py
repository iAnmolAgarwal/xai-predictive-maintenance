"""The committed ``contracts/ws-schema.json`` must match what the exporter emits.

``web/src/contracts/ws.ts`` is generated from this artefact by
``json-schema-to-typescript``; the frontend hand-writes no WebSocket type, so
drift here is drift in the dashboard's understanding of the protocol.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from xpm.contracts.channels import AI4I_CHANNELS, IMS_CHANNELS

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTER = REPO_ROOT / "scripts" / "export_ws_schema.py"
COMMITTED = REPO_ROOT / "contracts" / "ws-schema.json"

SERVER_FRAME_TYPES = {
    "hello",
    "snapshot",
    "telemetry",
    "risk",
    "alert",
    "explanation",
    "replay_state",
    "config",
    "ping",
    "error",
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> str:
    out = tmp_path_factory.mktemp("ws") / "ws-schema.json"
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
        "contracts/ws-schema.json is stale — run `make contracts` and commit the result"
    )


def test_serialisation_is_deterministic(document: dict[str, Any]) -> None:
    text = COMMITTED.read_text(encoding="utf-8")
    assert text == json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_dialect_is_draft_2020_12(document: dict[str, Any]) -> None:
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_server_frame_union_is_discriminated_on_type(document: dict[str, Any]) -> None:
    server = document["$defs"]["ServerFrame"]
    assert server["discriminator"]["propertyName"] == "type"
    assert set(server["discriminator"]["mapping"]) == SERVER_FRAME_TYPES
    assert len(server["oneOf"]) == len(SERVER_FRAME_TYPES)


def test_client_frame_union_is_pong_only(document: dict[str, Any]) -> None:
    client = document["$defs"]["ClientFrame"]
    assert client["properties"]["type"]["const"] == "pong"
    assert set(client["properties"]) == {"type", "ts"}
    assert client["additionalProperties"] is False


def test_discriminators_are_required_not_defaulted(document: dict[str, Any]) -> None:
    """``type?: "hello"`` would weaken the frontend's exhaustive switch."""
    for name, definition in document["$defs"].items():
        properties = definition.get("properties", {})
        if "type" in properties:
            assert "default" not in properties["type"], name
            assert "type" in definition["required"], name


def test_hello_carries_the_protocol_version_and_the_plant(document: dict[str, Any]) -> None:
    hello = document["$defs"]["HelloFrame"]
    assert hello["properties"]["protocol_version"]["const"] == 1
    assert hello["properties"]["plant"] == {"$ref": "#/$defs/Plant"}
    assert set(hello["required"]) == {"type", "protocol_version", "run_id", "server_time", "plant"}


def test_telemetry_updates_are_positional(document: dict[str, Any]) -> None:
    values = document["$defs"]["TelemetryUpdate"]["properties"]["values"]
    assert values["type"] == "array"
    assert document["$defs"]["MachineSnapshot"]["properties"]["values"]["type"] == "array"


def test_risk_frame_has_no_frame_level_dataset_ts(document: dict[str, Any]) -> None:
    """Each risk update carries its own dataset clock (FE §3.2)."""
    risk = document["$defs"]["RiskFrame"]["properties"]
    assert "dataset_ts" not in risk
    assert "dataset_ts" in document["$defs"]["RiskUpdate"]["properties"]
    assert "dataset_ts" in document["$defs"]["TelemetryFrame"]["properties"]


def test_canonical_channel_order_is_pinned() -> None:
    """Reordering a channel shifts every positional ``values[]`` array."""
    assert [c.name for c in AI4I_CHANNELS] == [
        "air_temp",
        "process_temp",
        "temp_diff",
        "rot_speed",
        "torque",
        "power",
        "tool_wear",
    ]
    assert [c.name for c in IMS_CHANNELS] == [
        "vibration_0k5khz",
        "vibration_1khz",
        "vibration_2khz",
        "vibration_3khz",
        "vibration_5khz",
        "vibration_8khz",
        "vibration_rms",
        "vibration_kurtosis",
        "vibration_crest",
    ]


def test_clocks_are_date_time_strings(document: dict[str, Any]) -> None:
    ping = document["$defs"]["PingFrame"]["properties"]["ts"]
    assert ping == {"format": "date-time", "type": "string"}
