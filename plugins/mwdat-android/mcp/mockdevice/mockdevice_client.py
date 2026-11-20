# @generated -- do not edit.

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""HTTP transport for the MockDevice test server.

Thin wrapper over the DAT MockDevice HTTP test server that a DAT app exposes on
localhost when running in mock/test mode. Uses only the Python standard library,
so it runs anywhere with no third-party dependencies.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

DEFAULT_TIMEOUT_S = 10.0


class MockDeviceError(Exception):
    """A request to the test server failed (bad request, connection, or server error)."""


class RouteUnavailableError(MockDeviceError):
    """The attached build does not provide this route."""


# Server metadata routes, used before /capabilities has been read and therefore
# exempt from the advertised-paths gate: a server need not advertise them to
# answer them, and gating them would break mock_status against one that doesn't.
_META_PATHS = ("/health", "/capabilities")


class MockDeviceClient:
    """Sends HTTP requests to a running MockDevice test server."""

    def __init__(
        self,
        base_url: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        user_agent: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        # Route paths the attached server advertises via GET /capabilities. Left
        # None when the server predates that route, in which case every request is
        # attempted and unavailability surfaces as a 404 instead.
        self.advertised_paths: Optional[set[str]] = None

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def post(self, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("POST", path, body)

    def _request(
        self, method: str, path: str, body: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        route_path = path.split("?", 1)[0]
        if (
            self.advertised_paths is not None
            and route_path not in self.advertised_paths
            and route_path not in _META_PATHS
        ):
            raise RouteUnavailableError(
                f"{route_path} is not available in this app build; "
                "the attached server does not advertise it"
            )
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url=url, data=data, method=method)
        # The server closes the connection after each response (one request per
        # connection); do not attempt keep-alive.
        request.add_header("Connection", "close")
        if self.user_agent:
            request.add_header("User-Agent", self.user_agent)
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return _parse_json(response.read())
        except urllib.error.HTTPError as error:
            raise _map_http_error(
                path, error, routes_advertised=self.advertised_paths is not None
            ) from error
        except urllib.error.URLError as error:
            raise MockDeviceError(
                f"cannot reach test server at {url}: {error.reason}"
            ) from error
        except OSError as error:
            raise MockDeviceError(
                f"cannot reach test server at {url}: {error}"
            ) from error


def _parse_json(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MockDeviceError(f"invalid JSON from test server: {error}") from error
    if not isinstance(parsed, dict):
        raise MockDeviceError(f"unexpected non-object response: {parsed!r}")
    return parsed


def _map_http_error(
    path: str,
    error: urllib.error.HTTPError,
    routes_advertised: bool,
) -> MockDeviceError:
    body = error.read() if error.fp is not None else b""
    message = _error_message(body) or error.reason or "request failed"
    if error.code == 404 and not routes_advertised:
        # Same condition as the pre-flight advertised-paths gate, reached when the
        # server predates /capabilities; keep the exception type identical so
        # callers handle route-unavailability one way. When the server does advertise
        # its routes the gate has already cleared this path, so a 404 is the handler's
        # own (e.g. "display device not found") and must keep its message rather than
        # be reported as a missing route.
        return RouteUnavailableError(f"{path} is not available in this app build (404)")
    return MockDeviceError(f"{path} failed ({error.code}): {message}")


def _error_message(body: bytes) -> Optional[str]:
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.decode("utf-8", "replace")
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        return parsed["error"]
    return None
