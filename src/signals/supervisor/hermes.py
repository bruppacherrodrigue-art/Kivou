"""Hermes implementation of the Kivou-owned SHADOW supervisor protocol."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from signals.supervisor.contracts import (
    ProposedAction,
    SupervisorContext,
    SupervisorPlan,
    validate_context,
    validate_plan,
)
from signals.supervisor.pin import HermesPin, load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION, load_supervisor_profile
from signals.supervisor.runtime import (
    HealthState,
    SupervisorHealth,
    SupervisorNotConfigured,
    SupervisorSettings,
    SupervisorUnavailable,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)
from signals.supervisor.transport import HermesTransport, SubprocessHermesTransport

BRIDGE_PROTOCOL_VERSION = 1
OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"
OPENROUTER_PROVIDER_ROUTING = {
    "require_parameters": True,
    "data_collection": "deny",
}


class HermesSupervisorAdapter:
    def __init__(
        self,
        settings: SupervisorSettings,
        *,
        transport: HermesTransport | None = None,
        pin: HermesPin | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or SubprocessHermesTransport(settings)
        self.pin = pin or load_hermes_pin()

    def _validate_metadata(self, response: dict[str, Any]) -> None:
        if response.get("ok") is not True:
            raise SupervisorUnavailable("Hermes bridge reported an unavailable runtime")
        if response.get("protocol_version") != BRIDGE_PROTOCOL_VERSION:
            raise SupervisorVersionMismatch("Hermes bridge protocol mismatch")
        if response.get("hermes_version") != self.pin.version:
            raise SupervisorVersionMismatch("Hermes package version mismatch")
        if response.get("source_commit") != self.pin.commit:
            raise SupervisorVersionMismatch("Hermes source commit mismatch")
        if response.get("executable_tools") != []:
            raise SupervisorVersionMismatch("Hermes bridge exposed executable tools")

    @staticmethod
    def _validate_route(response: dict[str, Any]) -> None:
        if (
            response.get("provider") != OPENROUTER_PROVIDER
            or response.get("model") != OPENROUTER_MODEL
            or response.get("automatic_retries") != 0
            or response.get("fallbacks") is not False
        ):
            raise SupervisorVersionMismatch("Hermes bridge route mismatch")

    def health(self) -> SupervisorHealth:
        if self.settings.configuration_state() is HealthState.NOT_CONFIGURED:
            return SupervisorHealth(state=HealthState.NOT_CONFIGURED)
        try:
            self.settings.require_configured()
            response = self.transport.invoke({"operation": "health"})
            self._validate_metadata(response)
        except SupervisorNotConfigured:
            return SupervisorHealth(state=HealthState.NOT_CONFIGURED)
        except SupervisorVersionMismatch:
            return SupervisorHealth(state=HealthState.VERSION_MISMATCH)
        except Exception:  # noqa: BLE001 - diagnostic must not couple customer runtime to Hermes
            return SupervisorHealth(state=HealthState.UNAVAILABLE)
        return SupervisorHealth(
            state=HealthState.AVAILABLE,
            hermes_version=self.pin.version,
            source_commit=self.pin.commit,
            executable_tools=(),
        )

    def _instructions(self, response_schema: dict[str, Any]) -> str:
        schema = json.dumps(
            response_schema,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            f"{load_supervisor_profile()}\n\n"
            "The required output JSON Schema is authoritative:\n"
            f"{schema}\n"
            f"supervisor_version must be hermes-agent-{self.pin.version}.\n"
            f"skill_version must be {PROFILE_VERSION}."
        )

    @staticmethod
    def _context_json(context: SupervisorContext) -> str:
        payload = context.model_dump(mode="json")
        payload["content_boundary"] = "UNTRUSTED_DATA"
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def plan(self, context: SupervisorContext) -> SupervisorPlan:
        self.settings.require_configured()
        try:
            validate_context(context, self.settings.limits)
        except ValueError as exc:
            raise SupervisorValidationError("Kivou supervisor context is invalid") from exc

        response_schema = SupervisorPlan.model_json_schema()
        response = self.transport.invoke(
            {
                "operation": "plan",
                "instructions": self._instructions(response_schema),
                "context_json": self._context_json(context),
                "max_tokens": self.settings.limits.max_output_tokens,
                "timeout_seconds": self.settings.limits.invocation_timeout_seconds,
                "provider": OPENROUTER_PROVIDER,
                "model": OPENROUTER_MODEL,
                "provider_routing": OPENROUTER_PROVIDER_ROUTING,
                "response_schema": response_schema,
            }
        )
        self._validate_metadata(response)
        self._validate_route(response)
        raw_plan = response.get("response")
        if not isinstance(raw_plan, str):
            raise SupervisorValidationError("Hermes response is missing a structured plan")
        if len(raw_plan.encode("utf-8")) > self.settings.limits.max_output_bytes:
            raise SupervisorValidationError("Hermes structured plan exceeds maximum output bytes")
        try:
            parsed = json.loads(raw_plan)
        except json.JSONDecodeError as exc:
            raise SupervisorValidationError("Hermes response is not one JSON object") from exc
        if not isinstance(parsed, dict):
            raise SupervisorValidationError("Hermes response is not one JSON object")
        try:
            plan = SupervisorPlan.model_validate(parsed)
        except ValidationError as exc:
            raise SupervisorValidationError("Hermes plan failed strict schema validation") from exc
        try:
            validate_plan(plan, self.settings.limits)
        except ValueError as exc:
            message = str(exc)
            if "maximum planned actions" in message:
                raise SupervisorValidationError(message) from exc
            raise SupervisorValidationError("Hermes plan contains a denied command") from exc
        if any(action.command not in context.available_commands for action in plan.proposed_actions):
            raise SupervisorValidationError("Hermes command is not available in this context")
        if plan.supervisor_version != f"hermes-agent-{self.pin.version}":
            raise SupervisorValidationError("Hermes supervisor version is invalid")
        if plan.skill_version != PROFILE_VERSION:
            raise SupervisorValidationError("Hermes skill version is invalid")
        if plan.estimated_cost > context.budget.maximum_cycle_cost:
            raise SupervisorValidationError("Hermes plan exceeds the Kivou budget envelope")
        if sum((action.estimated_cost for action in plan.proposed_actions), start=0) > (
            context.budget.maximum_cycle_cost
        ):
            raise SupervisorValidationError("Hermes actions exceed the Kivou budget envelope")
        return plan

    def propose_actions(self, context: SupervisorContext) -> tuple[ProposedAction, ...]:
        return self.plan(context).proposed_actions
