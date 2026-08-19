"""Finite-timeout JSON transport into the isolated Hermes environment."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from signals.supervisor.runtime import (
    SupervisorProtocolError,
    SupervisorSettings,
    SupervisorTimeout,
    SupervisorUnavailable,
)


class HermesTransport(Protocol):
    def invoke(self, request: Mapping[str, Any]) -> dict[str, Any]: ...


class SubprocessHermesTransport:
    def __init__(
        self,
        settings: SupervisorSettings,
        *,
        bridge_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.bridge_path = bridge_path or Path(__file__).with_name("hermes_bridge.py")

    def _environment(self) -> dict[str, str]:
        self.settings.require_configured()
        assert self.settings.hermes_home is not None
        return {
            "HOME": str(self.settings.hermes_home),
            "HERMES_HOME": str(self.settings.hermes_home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
        }

    def invoke(self, request: Mapping[str, Any]) -> dict[str, Any]:
        self.settings.require_configured()
        assert self.settings.hermes_python is not None
        assert self.settings.working_directory is not None
        try:
            request_bytes = json.dumps(
                request, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SupervisorProtocolError("bridge request is not valid JSON") from exc
        request_limit = self.settings.limits.max_context_bytes + 65_536
        if len(request_bytes) > request_limit:
            raise SupervisorProtocolError("bridge request exceeds configured maximum")

        try:
            process = subprocess.Popen(
                [str(self.settings.hermes_python), str(self.bridge_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.settings.working_directory,
                env=self._environment(),
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            raise SupervisorUnavailable("Hermes bridge could not start") from exc

        try:
            stdout, _stderr = process.communicate(
                request_bytes,
                timeout=self.settings.limits.invocation_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise SupervisorTimeout("Hermes bridge timed out safely") from exc

        if process.returncode != 0:
            raise SupervisorUnavailable(
                f"Hermes bridge failed with exit status {process.returncode}"
            )
        if len(stdout) > self.settings.limits.max_output_bytes:
            raise SupervisorProtocolError("bridge output exceeds configured maximum")
        try:
            decoded = stdout.decode("utf-8")
            parsed = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupervisorProtocolError("bridge output is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise SupervisorProtocolError("bridge must return one JSON object")
        return parsed
