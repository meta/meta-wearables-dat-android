# @generated -- do not edit.

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""Resolves a running app's MockDevice test-server base URL, per platform.

iOS: reads the port the in-app server wrote inside the simulator app data
container, then reaches it over the shared host localhost. Android: reads the port
the in-app server wrote into the app's files dir via `run-as`, falling back to a
fixed port, then forwards a free host TCP port over adb to it and polls /health for
readiness, removing that forward again if the server never answers; `remove_forward`
removes it once the caller is done with it. All device/app identifiers are validated before use
in a subprocess, and every subprocess runs with a fixed argument list (no shell).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

DEFAULT_PORT_FILE_NAME = "mwdat_test_server_port.txt"
_POLL_INTERVAL_S = 0.25
_SUBPROCESS_TIMEOUT_S = 30
_SYSTEM_XCRUN = "/usr/bin/xcrun"

# Fixed loopback port the Android test server binds; the host bridges a free
# local port to it with `adb forward tcp:0 tcp:<this>`. Must match the port the
# app passes to `MockDeviceKit.startTestServer(...)` (the sample app's
# MOCK_TEST_SERVER_PORT).
_DEFAULT_ANDROID_TEST_SERVER_PORT = 8237
# Per-attempt timeout for a single /health probe while polling for readiness.
_HEALTH_REQUEST_TIMEOUT_S = 2.0

_UDID_RE = re.compile(r"^[0-9A-Fa-f-]{6,64}$")
_BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


class ResolveError(Exception):
    """The test server could not be located for the requested target."""


@dataclass(frozen=True)
class AdbForward:
    """An `adb forward` this server made: host `tcp:<local_port>` to `tcp:<remote_port>`."""

    serial: str
    local_port: int
    remote_port: int


@dataclass(frozen=True)
class ResolvedTarget:
    base_url: str
    identifier: str  # simulator udid / device serial
    app_id: str  # bundle id / package name
    port: int
    # The forward made to reach an Android app; the caller removes it when done with it.
    forward: Optional[AdbForward] = None


class TargetResolver(ABC):
    @abstractmethod
    def resolve(self, timeout_s: float) -> ResolvedTarget:
        raise NotImplementedError


def make_resolver(
    platform: str,
    *,
    app_id: str,
    identifier: Optional[str] = None,
    port_file: Optional[str] = None,
    port: Optional[int] = None,
) -> TargetResolver:
    normalized = platform.lower()
    if normalized == "ios":
        return IOSSimulatorResolver(
            app_id=app_id, udid=identifier, port_file=port_file, port=port
        )
    if normalized == "android":
        return AndroidEmulatorResolver(
            app_id=app_id, serial=identifier, port_file=port_file, port=port
        )
    raise ResolveError(
        f"unsupported platform: {platform!r} (expected 'ios' or 'android')"
    )


def _run(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
            check=False,
            shell=False,
        )
    except FileNotFoundError as error:
        raise ResolveError(f"command not found: {args[0]}") from error
    except OSError as error:
        raise ResolveError(f"could not run {args[0]}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise ResolveError(f"command timed out: {' '.join(args)}") from error
    if completed.returncode != 0:
        raise ResolveError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def _xcrun() -> str:
    if os.path.isfile(_SYSTEM_XCRUN) and os.access(_SYSTEM_XCRUN, os.X_OK):
        return _SYSTEM_XCRUN
    fallback = shutil.which("xcrun")
    if fallback is None:
        raise ResolveError("xcrun was not found at /usr/bin or on PATH")
    return fallback


class IOSSimulatorResolver(TargetResolver):
    def __init__(
        self,
        *,
        app_id: str,
        udid: Optional[str] = None,
        port_file: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        if not _BUNDLE_ID_RE.match(app_id):
            raise ResolveError(f"invalid bundle id: {app_id!r}")
        if udid is not None and not _UDID_RE.match(udid):
            raise ResolveError(f"invalid simulator udid: {udid!r}")
        self.app_id = app_id
        self.udid = udid
        self.port_file = port_file
        self.explicit_port = port

    def resolve(self, timeout_s: float) -> ResolvedTarget:
        udid = self.udid or self._booted_udid()
        port = (
            self.explicit_port
            if self.explicit_port is not None
            else self._read_port(udid, timeout_s)
        )
        return ResolvedTarget(
            base_url=f"http://127.0.0.1:{port}",
            identifier=udid,
            app_id=self.app_id,
            port=port,
        )

    def _booted_udid(self) -> str:
        raw = _run([_xcrun(), "simctl", "list", "devices", "booted", "-j"])
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ResolveError(f"could not parse simctl output: {error}") from error
        booted = [
            device["udid"]
            for devices in data.get("devices", {}).values()
            for device in devices
            if device.get("state") == "Booted" and "udid" in device
        ]
        if not booted:
            raise ResolveError(
                "no booted simulator found; boot one and launch the app with --ui-testing"
            )
        if len(booted) > 1:
            raise ResolveError(
                "multiple booted simulators; pass udid explicitly (one of: "
                + ", ".join(booted)
                + ")"
            )
        return booted[0]

    def _container(self, udid: str) -> str:
        raw = _run([_xcrun(), "simctl", "get_app_container", udid, self.app_id, "data"])
        container = raw.strip()
        if not container:
            raise ResolveError(
                f"app {self.app_id} is not installed on simulator {udid}"
            )
        return container

    def _read_port(self, udid: str, timeout_s: float) -> int:
        container = self._container(udid)
        port_path = self.port_file or os.path.join(
            container, "tmp", DEFAULT_PORT_FILE_NAME
        )
        deadline = time.monotonic() + timeout_s
        while True:
            port = _read_port_file(port_path)
            if port is not None:
                return port
            if time.monotonic() >= deadline:
                raise ResolveError(
                    f"no test-server port at {port_path}; launch a DEBUG build with "
                    f"--ui-testing (e.g. xcrun simctl launch {udid} {self.app_id} "
                    "--ui-testing)"
                )
            time.sleep(_POLL_INTERVAL_S)


class AndroidEmulatorResolver(TargetResolver):
    """Reaches the Android test server over `adb forward` to its fixed loopback port."""

    def __init__(
        self,
        *,
        app_id: str,
        serial: Optional[str] = None,
        port_file: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        if not _BUNDLE_ID_RE.match(app_id):
            raise ResolveError(f"invalid package name: {app_id!r}")
        if serial is not None and not _SERIAL_RE.match(serial):
            raise ResolveError(f"invalid device serial: {serial!r}")
        self.app_id = app_id
        self.serial = serial
        # Android reads a fixed name inside the app's own files dir, so an arbitrary host path
        # means nothing here; accepted for a uniform resolver signature but ignored.
        self.port_file = port_file
        # Overrides the device-side port to forward to, skipping discovery.
        self.explicit_port = port

    def resolve(self, timeout_s: float) -> ResolvedTarget:
        serial = self._connected_serial()
        device_port = (
            self.explicit_port
            or self._published_port(serial)
            or _DEFAULT_ANDROID_TEST_SERVER_PORT
        )
        forward = self._forward(serial, device_port)
        base_url = f"http://127.0.0.1:{forward.local_port}"
        try:
            _wait_for_health(base_url, timeout_s)
        except BaseException:
            remove_forward(forward)
            raise
        return ResolvedTarget(
            base_url=base_url,
            identifier=serial,
            app_id=self.app_id,
            port=forward.local_port,
            forward=forward,
        )

    def _connected_serial(self) -> str:
        serial = self.serial or os.environ.get("ANDROID_SERIAL")
        if not serial:
            return self._only_device()
        if not _SERIAL_RE.match(serial):
            raise ResolveError(f"invalid Android device serial: {serial!r}")
        if ":" not in serial:
            return serial
        output = _run(["adb", "connect", serial]).strip().lower()
        if "connected to" not in output:
            raise ResolveError(
                f"adb could not connect to Android device endpoint {serial!r}: {output}"
            )
        return serial

    def _only_device(self) -> str:
        serials = _parse_adb_devices(_run(["adb", "devices"]))
        if not serials:
            raise ResolveError(
                "no device/emulator found; start one (adb devices), then run your "
                "app's debug build with its MockDevice test server enabled"
            )
        if len(serials) > 1:
            raise ResolveError(
                "multiple devices/emulators; pass the serial explicitly (one of: "
                + ", ".join(serials)
                + ")"
            )
        return serials[0]

    def _published_port(self, serial: str) -> Optional[int]:
        """Read the port the app published, or None to fall back to the fixed port.

        `run-as` only works for a debuggable app, which is the same gate the sample apps put
        on starting the test server.
        """
        try:
            stdout = _run(
                [
                    "adb",
                    "-s",
                    serial,
                    "shell",
                    "run-as",
                    self.app_id,
                    "cat",
                    f"files/{DEFAULT_PORT_FILE_NAME}",
                ]
            )
        except ResolveError:
            return None
        try:
            port = int(stdout.strip())
        except ValueError:
            return None
        return port if 0 < port <= 65535 else None

    def _forward(self, serial: str, device_port: int) -> AdbForward:
        # Bridge a free *host* port (tcp:0, whose number adb prints) to the app's
        # loopback test-server port inside the device.
        stdout = _run(
            [
                "adb",
                "-s",
                serial,
                "forward",
                "tcp:0",
                f"tcp:{device_port}",
            ]
        ).strip()
        try:
            local_port = int(stdout)
        except ValueError as error:
            raise ResolveError(
                f"could not parse forwarded port from 'adb forward' output: {stdout!r}"
            ) from error
        return AdbForward(serial=serial, local_port=local_port, remote_port=device_port)


def remove_forward(forward: AdbForward) -> bool:
    """Remove `forward` if adb still lists it as this server made it; return whether it did.

    `adb forward --remove` frees a host port whatever it forwards to, so a port that no
    longer leads to the same device and port is left alone: something else made it. When
    adb fails, returns False rather than raising, since it runs while a connection is torn
    down.
    """
    made = (forward.serial, f"tcp:{forward.local_port}", f"tcp:{forward.remote_port}")
    try:
        listed = {
            tuple(line.split())
            for line in _run(["adb", "forward", "--list"]).splitlines()
        }
        if made not in listed:
            return False
        _run(["adb", "-s", forward.serial, "forward", "--remove", made[1]])
    except ResolveError:
        return False
    return True


def _parse_adb_devices(raw: str) -> list[str]:
    """Return the serials of devices in the `device` state from `adb devices`."""
    serials = []
    for line in raw.splitlines():
        line = line.strip()
        # Skip the header, blank lines, and daemon notices ("* daemon ... *").
        if not line or line.startswith("*") or line == "List of devices attached":
            continue
        parts = line.split()
        # Only fully-online devices count; skip `offline`, `unauthorized`, etc.
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _wait_for_health(base_url: str, timeout_s: float) -> None:
    """Poll GET /health until it answers or the timeout elapses."""
    url = base_url + "/health"
    deadline = time.monotonic() + timeout_s
    last_error = "no response"
    while True:
        try:
            request = urllib.request.Request(url=url, method="GET")
            request.add_header("Connection", "close")
            with urllib.request.urlopen(request, timeout=_HEALTH_REQUEST_TIMEOUT_S):
                return
        except (urllib.error.URLError, OSError) as error:
            last_error = str(getattr(error, "reason", error))
        if time.monotonic() >= deadline:
            raise ResolveError(
                f"test server did not become ready at {url} within {timeout_s:g}s "
                f"(last error: {last_error}); make sure the app's debug build is "
                "running with its MockDevice test server enabled (see the app's MCP "
                "integration docs)"
            )
        time.sleep(_POLL_INTERVAL_S)


def _read_port_file(path: str) -> Optional[int]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        port = int(content)
    except ValueError:
        return None
    return port if 0 < port <= 65535 else None
