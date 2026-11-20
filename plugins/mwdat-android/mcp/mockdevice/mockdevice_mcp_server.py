# @generated -- do not edit.

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""MCP server for driving the DAT MockDevice HTTP test server.

Lets an LLM agent control a simulated Meta wearable in a DAT app running in
mock/test mode: pair, power/wear/fold, cap-touch, camera feed, captured image,
inputs, motion, speech, Hey Meta voice invocations, and the glasses display.

Which routes a given app provides is discovered at connect time from the
server's own `GET /capabilities` list; a tool whose route is not advertised
reports that it is unavailable rather than failing opaquely.

Most tools are built from `mockdevice_routes.json` beside this file, which
declares each route, its request fields, and the tool that drives it.

The in-app test server starts when the app calls `startTestServer` — typically a
debug build launched with a UI-testing flag (`--ui-testing` on iOS, the
`mwdat_ui_testing` intent extra on Android), as the DAT sample apps do.

Zero third-party dependencies: this implements the MCP stdio protocol
(JSON-RPC 2.0 over newline-delimited stdin/stdout) with the Python standard
library only, so it runs anywhere with Python 3.8+ and needs no `pip install`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import sys
import urllib.parse
from typing import Any, Callable, Optional

from mockdevice_client import MockDeviceClient, MockDeviceError, RouteUnavailableError
from target_resolver import AdbForward, make_resolver, remove_forward, ResolveError

# Latest MCP protocol revision this server implements; the client's requested
# version is echoed back when present for maximum compatibility.
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "mockdevice"
# The DAT SDK release this server ships with: the plugin carrying it is that release's, and its
# routes are the ones that SDK's test server serves.
SERVER_VERSION = "1.1.0"


class _Session:
    """Holds the connection to the currently attached test server."""

    def __init__(self) -> None:
        self.client: Optional[MockDeviceClient] = None
        # The adb forward the attached Android app is reached through. The server removes it
        # once another connection replaces this one or the server stops.
        self.forward: Optional[AdbForward] = None
        self.meta: dict[str, Any] = {}
        # The agent's `clientInfo` from `initialize`, sent to the app as `User-Agent`.
        self.client_info: dict[str, Any] = {}
        # The platform mock_connect targets when a call names none: the plugin's, from --platform.
        self.default_platform: str = "ios"


_session = _Session()

# The app's test server attributes the mock device events it logs from this
# header; it validates both values the same way.
USER_AGENT_PRODUCT = "mwdat-mockdevice-mcp"
_MAX_CLIENT_NAME_LENGTH = 32
_UNKNOWN_CLIENT_NAME = "unknown"


def _client_name_token(name: Any) -> str:
    """The agent's `clientInfo.name` as one lowercase `[a-z0-9._-]` token."""
    if not isinstance(name, str):
        return _UNKNOWN_CLIENT_NAME
    token = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "-"
        for ch in name.strip().lower()
    ).strip("-")
    return token[:_MAX_CLIENT_NAME_LENGTH].rstrip("-") or _UNKNOWN_CLIENT_NAME


def _user_agent() -> str:
    client_name = _client_name_token(_session.client_info.get("name"))
    return f"{USER_AGENT_PRODUCT}/{SERVER_VERSION} {client_name}"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _require_client() -> MockDeviceClient:
    if _session.client is None:
        raise MockDeviceError("not connected; call mock_connect first")
    return _session.client


def _resolve_device_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    state = _require_client().get("/kit/paired-devices")
    ids = state.get("pairedDevices") or []
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise MockDeviceError("no paired device; call mock_pair_device first")
    raise MockDeviceError(
        f"multiple devices paired; pass device_id (one of: {', '.join(ids)})"
    )


def _try_capabilities(client: MockDeviceClient) -> Optional[dict[str, Any]]:
    # Older apps may predate the /capabilities route; treat its absence as unknown.
    try:
        return client.get("/capabilities")
    except MockDeviceError:
        return None


def _advertised_paths(capabilities: Optional[dict[str, Any]]) -> Optional[set[str]]:
    if capabilities is None:
        return None
    routes = capabilities.get("routes")
    if not isinstance(routes, list):
        return None
    return {
        route["path"]
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("path"), str)
    }


def _check_contract_version(capabilities: Optional[dict[str, Any]]) -> None:
    """Refuse an app whose test server serves a different route contract than this MCP calls.

    The app reports its contract at `/capabilities`. One that reports none predates the contract
    versions (a DAT SDK release before this MCP's), and serves routes this MCP doesn't call.
    """
    reported = capabilities.get("contractVersion") if capabilities else None
    # A bool is an int in Python, and JSON `true` must not pass for contract 1.
    if type(reported) is not int:
        served = "no route contract version"
    elif reported == CONTRACT_VERSION:
        return
    elif reported > CONTRACT_VERSION:
        raise MockDeviceError(
            f"This app's DAT SDK serves MockDevice route contract {reported}, newer than this "
            f"MockDevice MCP's ({CONTRACT_VERSION}). Update the plugin to the release that "
            "matches the app's DAT SDK."
        )
    else:
        served = f"route contract {reported}"
    raise MockDeviceError(
        "This app's DAT SDK is older than this MockDevice MCP supports: its test server reports "
        f"{served}, and this MCP needs {CONTRACT_VERSION}. Update the app to the DAT SDK release "
        "this plugin came with, rebuild it, and call mock_connect again."
    )


_DEVICE_ID_SCHEMA = {
    "type": "object",
    "properties": {
        "device_id": {
            "type": "string",
            "description": "Target device id. Optional — auto-resolved when exactly one device is paired.",
        }
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _coerce_timeout_s(raw: Any) -> float:
    # A JSON null (or omission) means "use the default"; anything non-numeric is a
    # caller mistake worth a clear message rather than a raw float() TypeError.
    if raw is None:
        return 10.0
    try:
        return float(raw)
    except (TypeError, ValueError) as error:
        raise MockDeviceError(f"timeout_s must be a number, got {raw!r}") from error


def _remove_forward(forward: Optional[AdbForward]) -> None:
    if forward is not None:
        remove_forward(forward)


def _h_connect(args: dict[str, Any]) -> dict[str, Any]:
    bundle_id = args.get("bundle_id")
    if not bundle_id:
        raise MockDeviceError("bundle_id is required")
    timeout_s = _coerce_timeout_s(args.get("timeout_s"))
    resolver = make_resolver(
        args.get("platform") or _session.default_platform,
        app_id=bundle_id,
        identifier=args.get("udid"),
        port_file=args.get("port_file"),
        port=args.get("port"),
    )
    target = resolver.resolve(timeout_s=timeout_s)
    try:
        client = MockDeviceClient(
            target.base_url, timeout_s=timeout_s, user_agent=_user_agent()
        )
        health = client.get("/health")
        capabilities = _try_capabilities(client)
        _check_contract_version(capabilities)
    except BaseException:
        # The connection already attached, if any, stays usable.
        _remove_forward(target.forward)
        raise
    client.advertised_paths = _advertised_paths(capabilities)
    previous_forward = _session.forward
    _session.client = client
    _session.forward = target.forward
    _session.meta = {
        "base_url": target.base_url,
        "udid": target.identifier,
        "bundle_id": target.app_id,
        "port": target.port,
    }
    # Once a forward is gone, adb can hand out its host port again.
    if previous_forward != target.forward:
        _remove_forward(previous_forward)
    return {
        "status": "ok",
        **_session.meta,
        "health": health,
        "capabilities": capabilities,
    }


def _h_status(_args: dict[str, Any]) -> dict[str, Any]:
    client = _require_client()
    return {"connected": True, **_session.meta, "health": client.get("/health")}


_NAV_PATHS = {
    "up": "/input/nav-up",
    "down": "/input/nav-down",
    "left": "/input/nav-left",
    "right": "/input/nav-right",
}

# ---------------------------------------------------------------------------
# Route spec
# ---------------------------------------------------------------------------

# Every route the app's test server serves and the tool each one backs. The iOS and
# Android router tests read the same file, so a route is declared once here, and a
# generic tool needs no code below.
ROUTE_SPEC_FILE = "mockdevice_routes.json"


def _load_spec() -> dict[str, Any]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ROUTE_SPEC_FILE)
    with open(path, encoding="utf-8") as spec_file:
        return json.load(spec_file)


def _mcp_name(wire_name: str) -> str:
    """The tool argument for a wire field: `pressType` becomes `press_type`."""
    return "".join("_" + ch.lower() if ch.isupper() else ch for ch in wire_name)


def _arguments(route: dict[str, Any]) -> dict[str, Any]:
    """The route's declared arguments: a POST's `body`, or a GET's `query`."""
    return route.get("body") or route.get("query") or {}


def _body_properties(route: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _arguments(route).get("properties") or {}


def _schema_property(prop: dict[str, Any]) -> dict[str, Any]:
    # The server applies a default itself, so the schema the agent sees omits it.
    return {key: value for key, value in prop.items() if key != "default"}


def _input_schema(route: dict[str, Any]) -> dict[str, Any]:
    properties = {
        _mcp_name(wire): _schema_property(prop)
        for wire, prop in _body_properties(route).items()
    }
    if route.get("device"):
        properties["device_id"] = _DEVICE_ID_SCHEMA["properties"]["device_id"]
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    required = [_mcp_name(wire) for wire in _arguments(route).get("required", [])]
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    return schema


def _coerce(key: str, value: Any, prop: dict[str, Any]) -> Any:
    kind = prop.get("type")
    try:
        if kind == "integer":
            value = int(value)
        elif kind == "number":
            value = float(value)
    except (TypeError, ValueError) as error:
        noun = "an integer" if kind == "integer" else "a number"
        raise MockDeviceError(f"{key} must be {noun}") from error
    if kind == "boolean":
        value = bool(value)
    allowed = prop.get("enum")
    if allowed is not None and value not in allowed:
        raise MockDeviceError(
            f"invalid {key} {value!r}; expected one of: {', '.join(map(str, allowed))}"
        )
    if "minimum" in prop and value < prop["minimum"]:
        raise MockDeviceError(f"{key} must be at least {prop['minimum']}")
    if "maximum" in prop and value > prop["maximum"]:
        raise MockDeviceError(f"{key} must be at most {prop['maximum']}")
    return value


def _request_body(route: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Validate the tool arguments and return them as the route's wire body or query."""
    required = set(_arguments(route).get("required", []))
    body: dict[str, Any] = {}
    for wire, prop in _body_properties(route).items():
        key = _mcp_name(wire)
        value = args.get(key)
        if value is None or value == "":
            if "default" in prop:
                body[wire] = prop["default"]
            elif wire in required:
                raise MockDeviceError(f"{key} is required")
            continue
        body[wire] = _coerce(key, value, prop)
    return body


def _with_query(path: str, arguments: dict[str, Any]) -> str:
    if not arguments:
        return path
    return f"{path}?{urllib.parse.urlencode(arguments, quote_via=urllib.parse.quote)}"


def _generic_handler(
    route: dict[str, Any],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    method, path = route["method"], route["path"]

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        body = _request_body(route, args)
        client = _require_client()
        if method == "GET":
            if route.get("device"):
                body = {"deviceId": _resolve_device_id(args.get("device_id")), **body}
            return client.get(_with_query(path, body))
        if route.get("device"):
            body = {"deviceId": _resolve_device_id(args.get("device_id")), **body}
        return client.post(path, body)

    return handler


_SPEC: dict[str, Any] = _load_spec()
_ROUTES: list[dict[str, Any]] = _SPEC["routes"]
# The route contract this MCP calls. A rename, removal, or reshaping of a route bumps it in the
# spec and in both routers; an added route doesn't, since a tool whose route an app lacks reports
# itself unavailable.
CONTRACT_VERSION: int = _SPEC["contractVersion"]

# The nav routes share one custom tool, which reuses their `source` field.
_INPUT_SOURCE_PROPERTY = _schema_property(
    _body_properties(next(r for r in _ROUTES if r["path"] == _NAV_PATHS["up"]))[
        "source"
    ]
)
INPUT_SOURCES: list[str] = _INPUT_SOURCE_PROPERTY["enum"]


def _choice(args: dict[str, Any], key: str, allowed: list[str], default: str) -> str:
    value = args.get(key)
    if value is None or value == "":
        return default
    if value not in allowed:
        raise MockDeviceError(
            f"invalid {key} {value!r}; expected one of: {', '.join(allowed)}"
        )
    return value


def _post_for_device(
    path: str, args: dict[str, Any], body: dict[str, Any]
) -> dict[str, Any]:
    return _require_client().post(
        path, {"deviceId": _resolve_device_id(args.get("device_id")), **body}
    )


def _h_input_nav(args: dict[str, Any]) -> dict[str, Any]:
    direction = args.get("direction")
    path = _NAV_PATHS.get(direction)
    if path is None:
        raise MockDeviceError(
            f"invalid direction {direction!r}; expected one of: {', '.join(_NAV_PATHS)}"
        )
    source = _choice(args, "source", INPUT_SOURCES, "captouch")
    return _post_for_device(path, args, {"source": source})


def _decode_display_payload(payload: str) -> dict[str, Any]:
    try:
        # binascii.Error, which b64decode raises on malformed input, subclasses ValueError.
        raw = base64.b64decode(payload, validate=True)
    except ValueError:
        return {"payload_base64": payload, "decoded": False}
    try:
        return {"tree": json.loads(raw), "decoded": True}
    except (UnicodeDecodeError, json.JSONDecodeError):
        # A mock device renders the semantic web-preview payload, which is plain JSON. Real
        # glasses get gzipped Bloks instead, so hand that back undecoded rather than guessing.
        return {"payload_base64": payload, "decoded": False}


def _h_display_content(args: dict[str, Any]) -> dict[str, Any]:
    query: dict[str, Any] = {}
    after_revision = args.get("after_revision")
    if after_revision is not None:
        try:
            after_revision = int(after_revision)
        except (TypeError, ValueError) as error:
            raise MockDeviceError("after_revision must be an integer") from error
        query["afterRevision"] = after_revision
    response = _require_client().get(_with_query("/display-preview/content", query))
    if not response:
        # A bodyless 204 means the content still matches after_revision, so the revision is
        # whatever the caller polled with. Only echo it when there is one, rather than a null.
        unchanged: dict[str, Any] = {"unchanged": True}
        if after_revision is not None:
            unchanged["revision"] = after_revision
        return unchanged
    result: dict[str, Any] = {"revision": response.get("revision")}
    payload = response.get("payload")
    if not isinstance(payload, str):
        # Null payload: the display is connected but currently showing nothing. This is still a
        # fully-read state, so carry `decoded` like the other tree-bearing branches do.
        return {**result, "tree": None, "decoded": True}
    return {**result, **_decode_display_payload(payload)}


# ---------------------------------------------------------------------------
# Tool registry. Descriptions script the self-verification loop for the agent.
# ---------------------------------------------------------------------------

# Tools that manage the connection itself rather than call one route.
_SESSION_TOOLS: list[dict[str, Any]] = [
    {
        "name": "mock_connect",
        "description": (
            "Attach to a running DAT app's MockDevice test server and cache the connection. "
            "The server starts when the app calls startTestServer — typically a debug build "
            "launched with a UI-testing flag, as the DAT sample apps do. If no server is found, "
            "relaunch it (e.g. `xcrun simctl launch <udid> <bundle_id> --ui-testing`) and call "
            "this again. Fails, saying which side to update, when the app's DAT SDK serves a "
            "different route contract than this MCP calls. Returns base_url, udid, port, health, "
            "and the server's capabilities. Call this first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_id": {
                    "type": "string",
                    "description": "The app's bundle id (iOS) / package name (Android).",
                },
                "udid": {
                    "type": "string",
                    "description": "Simulator udid / device serial. Auto-detected when exactly one is booted.",
                },
                "platform": {
                    "type": "string",
                    "enum": ["ios", "android"],
                    "description": (
                        "Target platform. Defaults to the plugin's own platform ('ios' when "
                        "the server was started without --platform)."
                    ),
                },
                "port_file": {
                    "type": "string",
                    "description": "Optional absolute path to the port file (overrides the default).",
                },
                "port": {
                    "type": "integer",
                    "description": "Optional explicit port (skips port-file discovery).",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "How long to poll for the server to become ready. Defaults to 10.",
                },
            },
            "required": ["bundle_id"],
            "additionalProperties": False,
        },
        "handler": _h_connect,
    },
    {
        "name": "mock_status",
        "description": "Report connection status and health of the attached test server.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "handler": _h_status,
    },
]

# Tools the route spec marks `custom`, by name.
_CUSTOM_ROUTE_TOOLS: dict[str, dict[str, Any]] = {
    "mock_input_nav": {
        "name": "mock_input_nav",
        "description": (
            "Inject a directional navigation event. Delivered only while the app has an Inputs "
            "session streaming and only when the session requested this source; otherwise the "
            "event is dropped."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": sorted(_NAV_PATHS),
                    "description": "Which way to navigate.",
                },
                "source": _INPUT_SOURCE_PROPERTY,
                "device_id": _DEVICE_ID_SCHEMA["properties"]["device_id"],
            },
            "required": ["direction"],
            "additionalProperties": False,
        },
        "handler": _h_input_nav,
    },
    "mock_display_content": {
        "name": "mock_display_content",
        "description": (
            "Read the display content the app has sent to the simulated glasses: a node 'tree' "
            "plus a 'revision' that increments whenever the content changes. This is the semantic "
            "content, not a rendered image, and it is a debug payload rather than a stable API — "
            "read the document you get back rather than assuming field names. Requires a "
            "display-capable device — pair with model='metaRayBanDisplay'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "after_revision": {
                    "type": "integer",
                    "description": (
                        "Pass the revision from a previous call to poll for a change; the reply "
                        "is {unchanged: true} while the content still matches it."
                    ),
                }
            },
            "additionalProperties": False,
        },
        "handler": _h_display_content,
    },
}


def _build_tools(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools = list(_SESSION_TOOLS)
    seen = {tool["name"] for tool in tools}
    for route in routes:
        name = route.get("tool")
        if name is None or name in seen:
            continue
        seen.add(name)
        if route.get("handler") == "custom":
            tools.append(_CUSTOM_ROUTE_TOOLS[name])
            continue
        tools.append(
            {
                "name": name,
                "description": route["description"],
                "inputSchema": _input_schema(route),
                "handler": _generic_handler(route),
            }
        )
    return tools


TOOLS: list[dict[str, Any]] = _build_tools(_ROUTES)

_TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


# ---------------------------------------------------------------------------
# MCP stdio protocol (JSON-RPC 2.0, newline-delimited)
# ---------------------------------------------------------------------------


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": f"unknown tool: {name}"}, indent=2),
                }
            ],
            "isError": True,
        }
    try:
        result = tool["handler"](arguments or {})
    except RouteUnavailableError as error:
        result = {"error": str(error), "available": False}
    except (MockDeviceError, ResolveError) as error:
        result = {"error": str(error)}
    except Exception as error:  # noqa: BLE001 — surface unexpected failures as tool errors
        return {
            "content": [
                {"type": "text", "text": json.dumps({"error": str(error)}, indent=2)}
            ],
            "isError": True,
        }
    is_error = isinstance(result, dict) and "error" in result
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
        "isError": is_error,
    }


def handle_message(message: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Dispatch one JSON-RPC message. Returns a response, or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")

    if "id" not in message:
        # JSON-RPC 2.0: a notification carries no id and never gets a reply,
        # whatever its method — so this precedes dispatch, not follows it.
        return None

    if method == "initialize":
        params = message.get("params") or {}
        client_info = params.get("clientInfo")
        _session.client_info = client_info if isinstance(client_info, dict) else {}
        return _result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "tools/list":
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in TOOLS
        ]
        return _result(request_id, {"tools": tools})
    if method == "tools/call":
        params = message.get("params") or {}
        return _result(
            request_id,
            _call_tool(params.get("name", ""), params.get("arguments") or {}),
        )
    if method == "ping":
        return _result(request_id, {})

    return _error(request_id, -32601, f"Method not found: {method}")


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve the MockDevice MCP tools over stdio."
    )
    parser.add_argument(
        "--platform",
        choices=("ios", "android"),
        default="ios",
        help=(
            "the platform mock_connect targets when a call names none; each plugin passes "
            "its own (default: ios)"
        ),
    )
    # A launcher that runs this file through `runpy` leaves the script path among the
    # arguments, so an argument the server does not know is reported, not fatal.
    args, unrecognized = parser.parse_known_args(argv)
    if unrecognized:
        sys.stderr.write(f"ignoring unrecognized arguments: {' '.join(unrecognized)}\n")
    return args


def main(argv: Optional[list[str]] = None) -> None:
    _session.default_platform = _parse_args(argv).platform
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def _stop_signals() -> list[int]:
    """SIGTERM, which MCP clients send when closing stdin does not stop a server, and
    SIGHUP, which a closing terminal sends. Windows has no SIGHUP."""
    return [
        getattr(signal, name) for name in ("SIGTERM", "SIGHUP") if hasattr(signal, name)
    ]


def _exit_on_signal(signum: int, _frame: Any) -> None:
    # A second signal must not interrupt the cleanup this one starts.
    for stop_signal in _stop_signals():
        signal.signal(stop_signal, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def _disconnect() -> None:
    """Drop the attached connection and remove the adb forward it was reached through."""
    forward = _session.forward
    _session.client = None
    _session.forward = None
    _session.meta = {}
    _remove_forward(forward)


def run() -> None:
    """Serve over stdio, then remove the server's adb forward however serving stops.

    MCP clients stop a stdio server by closing its stdin, then by SIGTERM if it is still
    running. A process killed outright (SIGKILL, or TerminateProcess on Windows) runs no
    cleanup.
    """
    for stop_signal in _stop_signals():
        signal.signal(stop_signal, _exit_on_signal)
    try:
        main()
    finally:
        _disconnect()


if __name__ == "__main__":
    run()
