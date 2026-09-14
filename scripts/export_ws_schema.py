#!/usr/bin/env python
"""Export the WebSocket contract to ``contracts/ws-schema.json``.

JSON Schema draft 2020-12, generated from the Pydantic frame unions in
``xpm.contracts.ws``. ``make contracts`` compiles it to
``web/src/contracts/ws.ts`` with ``json-schema-to-typescript``; the frontend
hand-writes no WebSocket type (R7, R15).

Both unions are emitted in **serialization** mode — the shape a client actually
receives and sends, with every field present and the ``type`` discriminator
required rather than defaulted.

Usage::

    python scripts/export_ws_schema.py [--out contracts/ws-schema.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from xpm.contracts.ws import PROTOCOL_VERSION, ClientFrame, ServerFrame

DEFAULT_OUT = Path("contracts") / "ws-schema.json"

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

DESCRIPTION = (
    "WebSocket protocol for /ws?plant_id=<ai4i|ims>. The query parameter is the "
    "complete subscription; there is no subscribe frame and no transport control "
    "over this socket. Frames are JSON text, one object per frame, discriminated "
    "on `type`. On every connect the server sends `hello` then `snapshot`. "
    "Clients must ignore unknown server frame types without erroring."
)


def _union_schema(
    adapter: TypeAdapter[Any], title: str, description: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(root, defs)`` for a frame union, with ``$defs`` lifted out."""
    schema: dict[str, Any] = adapter.json_schema(
        ref_template="#/$defs/{model}", mode="serialization"
    )
    defs: dict[str, Any] = schema.pop("$defs", {})
    schema["title"] = title
    schema["description"] = description
    return schema, defs


def _pin_defaulted_fields(schema: dict[str, Any]) -> None:
    """Make defaulted fields required rather than optional.

    ``type``, ``protocol_version`` and ``schema_version`` carry Python-side
    defaults so the backend can construct a frame without restating constants it
    already owns, but a default is *always* materialised on the wire in
    serialization mode. Leaving them optional would generate ``type?: "hello"``
    and ``schema_version?: string`` in TypeScript, weakening both the
    discriminated union the frontend switches on and every frame it reads.
    """
    for definition in schema.values():
        properties = definition.get("properties")
        if not isinstance(properties, dict):
            continue
        required: list[str] = definition.setdefault("required", [])
        for name, prop in properties.items():
            if "default" not in prop:
                continue
            del prop["default"]
            if name not in required:
                required.append(name)


def _strip_titles(node: Any) -> None:
    """Drop per-property ``title`` keys.

    Pydantic titles every field ("Dataset Ts"), and json-schema-to-typescript
    turns each one into a standalone exported alias ("export type DatasetTs8").
    The definition-level titles are what name the generated interfaces; the
    property-level ones only add hundreds of lines of noise to ``ws.ts``.
    """
    if isinstance(node, dict):
        node.pop("title", None)
        for value in node.values():
            _strip_titles(value)
    elif isinstance(node, list):
        for value in node:
            _strip_titles(value)


def build_document() -> dict[str, Any]:
    """Build the WebSocket JSON Schema document."""
    server, server_defs = _union_schema(
        TypeAdapter(ServerFrame),
        "ServerFrame",
        "Any frame the server may send to a client.",
    )
    client, client_defs = _union_schema(
        TypeAdapter(ClientFrame),
        "ClientFrame",
        "Any frame a client may send to the server. `pong` is the only one.",
    )
    defs: dict[str, Any] = {**server_defs, **client_defs}
    defs["ServerFrame"] = server
    defs["ClientFrame"] = client
    _pin_defaulted_fields(defs)
    for definition in defs.values():
        for prop in definition.get("properties", {}).values():
            _strip_titles(prop)
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": "https://xpm.local/contracts/ws-schema.json",
        "title": "XpmWsProtocol",
        "description": DESCRIPTION,
        "x-protocol-version": PROTOCOL_VERSION,
        "type": "object",
        "properties": {
            "server_frame": {"$ref": "#/$defs/ServerFrame"},
            "client_frame": {"$ref": "#/$defs/ClientFrame"},
        },
        "required": ["server_frame", "client_frame"],
        "additionalProperties": False,
        "$defs": defs,
    }


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
