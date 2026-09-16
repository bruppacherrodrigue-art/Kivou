"""Chief of Staff report adapter over Kivou's isolated Hermes boundary."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from signals.chief_of_staff.config import (
    ChiefOfStaffConfigurationState,
    chief_of_staff_config_from_environment,
)
from signals.chief_of_staff.contracts import ChiefOfStaffContext, ChiefOfStaffReport
from signals.chief_of_staff.profiles import (
    CHIEF_OF_STAFF_PROFILE_VERSION,
    load_chief_of_staff_profile,
)
from signals.model_runtime.budget import ModelBudgetStore
from signals.model_runtime.config import ModelRoute
from signals.model_runtime.openrouter import estimate_reservation
from signals.supervisor.hermes import (
    BRIDGE_PROTOCOL_VERSION,
    CLOSED_PROVIDER_ERROR_CODES,
    OPENROUTER_PROVIDER,
    OPENROUTER_PROVIDER_ROUTING,
    transform_provider_schema,
)
from signals.supervisor.pin import HermesPin, load_hermes_pin
from signals.supervisor.runtime import (
    SupervisorNotConfigured,
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
    call_id: str | None = None
    reserved_usd: Decimal | None = None
    actual_usd: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChiefOfStaffHermesAdapter:
    def __init__(
        self,
        settings: SupervisorSettings,
        *,
        transport: HermesTransport | None = None,
        pin: HermesPin | None = None,
        model_route: ModelRoute | None = None,
        budget_store: ModelBudgetStore | None = None,
        batch_id: str | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        configuration = chief_of_staff_config_from_environment(environment)
        if configuration.state is not ChiefOfStaffConfigurationState.CONFIGURED:
            raise SupervisorNotConfigured("Chief of Staff model is not configured")
        if model_route is None:
            raise ValueError("Chief of Staff model route is required")
        if model_route.usage != "chief_of_staff":
            raise ValueError("Chief of Staff model route usage must be chief_of_staff")
        if configuration.route != model_route:
            raise ValueError("Chief of Staff configured route does not match the adapter route")
        if budget_store is None:
            raise ValueError("Chief of Staff budget store is required")
        self.settings = settings
        self.transport = transport or SubprocessHermesTransport(settings)
        self.pin = pin or load_hermes_pin()
        self.model_route = model_route
        self.budget_store = budget_store
        self.batch_id = batch_id
        self.model = model_route.model

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
        context_json = context.model_dump_json()
        request = {
                "operation": "report",
                "instructions": instructions,
                "context_json": context_json,
                "max_tokens": self.settings.limits.max_output_tokens,
                "timeout_seconds": self.settings.limits.invocation_timeout_seconds,
                "provider": OPENROUTER_PROVIDER,
                "model": self.model,
                "provider_routing": OPENROUTER_PROVIDER_ROUTING,
                "response_schema": transform_provider_schema(original_schema),
            }
        call_id: str | None = None
        reserved_usd: Decimal | None = None
        call_id = str(uuid.uuid4())
        reserved_usd = estimate_reservation(
            self.model_route,
            messages=(
                {"role": "system", "content": instructions},
                {"role": "user", "content": context_json},
            ),
            max_tokens=self.settings.limits.max_output_tokens,
        )
        self.budget_store.reserve(
            route=self.model_route,
            estimated_usd=reserved_usd,
            call_id=call_id,
            batch_id=self.batch_id,
        )
        try:
            response = self.transport.invoke(request)
            self._metadata(response)
        except Exception:
            self.budget_store.fail(call_id=call_id, error_code="CHIEF_OF_STAFF_TRANSPORT")
            raise
        actual_usd: Decimal | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        usage = response.get("usage")
        try:
            if not isinstance(usage, Mapping):
                raise TypeError
            input_tokens = int(usage["input_tokens"])
            output_tokens = int(usage["output_tokens"])
            actual_usd = Decimal(str(usage["cost_usd"]))
            if input_tokens < 0 or output_tokens < 0 or not actual_usd.is_finite():
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            self.budget_store.fail(call_id=call_id, error_code="CHIEF_OF_STAFF_USAGE_MISSING")
            raise SupervisorValidationError("Hermes usage is missing") from exc
        self.budget_store.succeed(
            call_id=call_id,
            actual_usd=actual_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
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
        return ChiefOfStaffHermesResult(
            report=report,
            model=self.model,
            usage=(dict(usage) if isinstance(usage, Mapping) else None),
            call_id=call_id,
            reserved_usd=reserved_usd,
            actual_usd=actual_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


__all__ = ["ChiefOfStaffHermesAdapter", "ChiefOfStaffHermesResult"]
