"""Chief of Staff report adapter over Kivou's isolated Hermes boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from signals.chief_of_staff.contracts import ChiefOfStaffContext, ChiefOfStaffReport
from signals.chief_of_staff.profiles import (
    CHIEF_OF_STAFF_PROFILE_VERSION,
    load_chief_of_staff_profile,
)
from signals.supervisor.hermes import (
    BRIDGE_PROTOCOL_VERSION,
    CLOSED_PROVIDER_ERROR_CODES,
    OPENROUTER_MODEL,
    OPENROUTER_PROVIDER,
    OPENROUTER_PROVIDER_ROUTING,
    transform_provider_schema,
)
from signals.supervisor.pin import HermesPin, load_hermes_pin
from signals.supervisor.runtime import (
    SupervisorProviderError,
    SupervisorSettings,
    SupervisorUnavailable,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)
from signals.supervisor.transport import HermesTransport, SubprocessHermesTransport


@dataclass(frozen=True)
class ChiefOfStaffHermesResult:
    report: ChiefOfStaffReport
    model: str
    usage: dict[str, object] | None = None


class ChiefOfStaffHermesAdapter:
    def __init__(
        self,
        settings: SupervisorSettings,
        *,
        transport: HermesTransport | None = None,
        pin: HermesPin | None = None,
        model: str = OPENROUTER_MODEL,
    ) -> None:
        self.settings = settings
        self.transport = transport or SubprocessHermesTransport(settings)
        self.pin = pin or load_hermes_pin()
        self.model = model

    def _metadata(self, response: dict[str, Any]) -> None:
        if response.get("ok") is not True:
            error = response.get("error")
            status = response.get("status")
            if error in CLOSED_PROVIDER_ERROR_CODES:
                raise SupervisorProviderError(
                    str(error), status_code=(status if isinstance(status, int) else None)
                )
            raise SupervisorUnavailable("Hermes bridge reported an unavailable runtime")
        if response.get("protocol_version") != BRIDGE_PROTOCOL_VERSION:
            raise SupervisorVersionMismatch("Hermes bridge protocol mismatch")
        if response.get("hermes_version") != self.pin.version:
            raise SupervisorVersionMismatch("Hermes package version mismatch")
        if response.get("source_commit") != self.pin.commit:
            raise SupervisorVersionMismatch("Hermes source commit mismatch")
        if response.get("executable_tools") != []:
            raise SupervisorVersionMismatch("Hermes bridge exposed executable tools")
        if (
            response.get("provider") != OPENROUTER_PROVIDER
            or response.get("model") != self.model
            or response.get("automatic_retries") != 0
            or response.get("fallbacks") is not False
        ):
            raise SupervisorVersionMismatch("Hermes bridge route mismatch")

    def _instructions(self, schema: dict[str, Any]) -> str:
        schema_json = json.dumps(schema, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return (
            f"{load_chief_of_staff_profile()}\n\n"
            "The required output JSON Schema is authoritative:\n"
            f"{schema_json}\n"
            f"supervisor_version must be hermes-agent-{self.pin.version}.\n"
            f"profile_version must be {CHIEF_OF_STAFF_PROFILE_VERSION}."
        )

    def generate(self, context: ChiefOfStaffContext) -> ChiefOfStaffHermesResult:
        self.settings.require_configured()
        original_schema = ChiefOfStaffReport.model_json_schema()
        instructions = self._instructions(original_schema)
        response = self.transport.invoke(
            {
                "operation": "report",
                "instructions": instructions,
                "context_json": context.model_dump_json(),
                "max_tokens": self.settings.limits.max_output_tokens,
                "timeout_seconds": self.settings.limits.invocation_timeout_seconds,
                "provider": OPENROUTER_PROVIDER,
                "model": self.model,
                "provider_routing": OPENROUTER_PROVIDER_ROUTING,
                "response_schema": transform_provider_schema(original_schema),
            }
        )
        self._metadata(response)
        raw = response.get("response")
        if not isinstance(raw, str):
            raise SupervisorValidationError("Hermes response is missing a structured report")
        if len(raw.encode("utf-8")) > self.settings.limits.max_output_bytes:
            raise SupervisorValidationError("Hermes report exceeds maximum output bytes")
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SupervisorValidationError("Hermes response is not one JSON object") from exc
        if not isinstance(decoded, dict):
            raise SupervisorValidationError("Hermes response is not one JSON object")
        try:
            report = ChiefOfStaffReport.model_validate_json(raw)
        except ValidationError as exc:
            raise SupervisorValidationError("Hermes report failed strict schema validation") from exc
        if report.supervisor_version != f"hermes-agent-{self.pin.version}":
            raise SupervisorValidationError("Hermes supervisor version is invalid")
        if report.profile_version != CHIEF_OF_STAFF_PROFILE_VERSION:
            raise SupervisorValidationError("Hermes profile version is invalid")
        usage = response.get("usage")
        return ChiefOfStaffHermesResult(
            report=report,
            model=self.model,
            usage=(dict(usage) if isinstance(usage, dict) else None),
        )


__all__ = ["ChiefOfStaffHermesAdapter", "ChiefOfStaffHermesResult"]
