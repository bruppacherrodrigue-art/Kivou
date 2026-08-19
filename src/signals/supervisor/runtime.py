"""Configuration and typed failures for the isolated supervisor runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from signals.supervisor.contracts import SupervisorLimits


class HealthState(StrEnum):
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    VERSION_MISMATCH = "version_mismatch"


class SupervisorError(RuntimeError):
    category = "supervisor"


class SupervisorNotConfigured(SupervisorError):
    category = "not_configured"


class SupervisorUnavailable(SupervisorError):
    category = "unavailable"


class SupervisorTimeout(SupervisorError):
    category = "timeout"


class SupervisorProtocolError(SupervisorError):
    category = "protocol"


class SupervisorValidationError(SupervisorError):
    category = "validation"


def _optional_absolute(value: str | None, *, name: str) -> Path | None:
    if value is None or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path


@dataclass(frozen=True)
class SupervisorSettings:
    hermes_python: Path | None
    hermes_home: Path | None
    working_directory: Path | None
    limits: SupervisorLimits = field(default_factory=SupervisorLimits)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> SupervisorSettings:
        source = os.environ if environ is None else environ
        limits = SupervisorLimits(
            invocation_timeout_seconds=float(
                source.get("KIVOU_HERMES_TIMEOUT_SECONDS", "30")
            ),
            max_context_bytes=int(source.get("KIVOU_HERMES_MAX_CONTEXT_BYTES", "65536")),
            max_context_items=int(source.get("KIVOU_HERMES_MAX_CONTEXT_ITEMS", "50")),
            max_planned_actions=int(source.get("KIVOU_HERMES_MAX_ACTIONS", "10")),
            max_output_bytes=int(source.get("KIVOU_HERMES_MAX_OUTPUT_BYTES", "131072")),
            max_output_tokens=int(source.get("KIVOU_HERMES_MAX_OUTPUT_TOKENS", "2048")),
        )
        return cls(
            hermes_python=_optional_absolute(
                source.get("KIVOU_HERMES_PYTHON"), name="KIVOU_HERMES_PYTHON"
            ),
            hermes_home=_optional_absolute(
                source.get("KIVOU_HERMES_HOME"), name="KIVOU_HERMES_HOME"
            ),
            working_directory=_optional_absolute(
                source.get("KIVOU_HERMES_CWD"), name="KIVOU_HERMES_CWD"
            ),
            limits=limits,
        )

    def configuration_state(self) -> HealthState:
        if self.hermes_python and self.hermes_home and self.working_directory:
            return HealthState.CONFIGURED
        return HealthState.NOT_CONFIGURED

    def require_configured(self) -> None:
        if self.configuration_state() is not HealthState.CONFIGURED:
            raise SupervisorNotConfigured("Hermes supervisor is not configured")
        assert self.hermes_python is not None
        assert self.hermes_home is not None
        assert self.working_directory is not None
        if not self.hermes_python.is_file():
            raise SupervisorNotConfigured("configured Hermes Python is unavailable")
        if not self.hermes_home.is_dir():
            raise SupervisorNotConfigured("configured Hermes HOME is unavailable")
        if not self.working_directory.is_dir():
            raise SupervisorNotConfigured("configured Hermes working directory is unavailable")
