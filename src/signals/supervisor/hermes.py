"""Hermes implementation of the Kivou-owned SHADOW supervisor protocol."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, ValidationError

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
    SupervisorProviderError,
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
SUPPORTED_PROVIDER_STRING_FORMATS = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "uri",
        "ipv4",
        "ipv6",
        "uuid",
    }
)
CLOSED_PROVIDER_ERROR_CODES = frozenset(
    {
        "AUTH",
        "PERMISSION",
        "RATE_LIMITED",
        "TIMEOUT",
        "HERMES_PLAN_INVALID",
        "SERVER_ERROR",
        "NETWORK",
    }
)


class _ExactlyOneActionSupervisorPlan(SupervisorPlan):
    proposed_actions: tuple[ProposedAction, ...] = Field(min_length=1, max_length=1)


def transform_provider_schema(original_schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return Anthropic's strict supported subset without mutating the source schema."""
    source = dict(original_schema)
    provider_schema: dict[str, Any] = {}

    definitions = source.pop("$defs", None)
    if definitions is not None:
        if not isinstance(definitions, Mapping):
            raise ValueError("$defs must be an object")
        provider_schema["$defs"] = {
            name: transform_provider_schema(schema)
            for name, schema in definitions.items()
        }

    reference = source.pop("$ref", None)
    if reference is not None:
        provider_schema["$ref"] = reference
        return provider_schema

    schema_type = source.pop("type", None)
    any_of = source.pop("anyOf", None)
    one_of = source.pop("oneOf", None)
    all_of = source.pop("allOf", None)
    if isinstance(any_of, list):
        provider_schema["anyOf"] = [transform_provider_schema(item) for item in any_of]
    elif isinstance(one_of, list):
        provider_schema["anyOf"] = [transform_provider_schema(item) for item in one_of]
    elif isinstance(all_of, list):
        provider_schema["allOf"] = [transform_provider_schema(item) for item in all_of]
    elif schema_type in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        provider_schema["type"] = schema_type
    else:
        raise ValueError("schema requires one supported type or composition")

    enum = source.pop("enum", None)
    if isinstance(enum, list):
        provider_schema["enum"] = enum
    description = source.pop("description", None)
    if isinstance(description, str):
        provider_schema["description"] = description
    title = source.pop("title", None)
    if isinstance(title, str):
        provider_schema["title"] = title

    if schema_type == "object":
        properties = source.pop("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError("object properties must be an object")
        provider_schema["properties"] = {
            name: transform_provider_schema(schema) for name, schema in properties.items()
        }
        source.pop("additionalProperties", None)
        provider_schema["additionalProperties"] = False
        required = source.pop("required", None)
        if isinstance(required, list):
            provider_schema["required"] = required
    elif schema_type == "string":
        string_format = source.pop("format", None)
        if string_format in SUPPORTED_PROVIDER_STRING_FORMATS:
            provider_schema["format"] = string_format
        elif string_format is not None:
            source["format"] = string_format
    elif schema_type == "array":
        items = source.pop("items", None)
        if isinstance(items, Mapping):
            provider_schema["items"] = transform_provider_schema(items)
        min_items = source.pop("minItems", None)
        if min_items in (0, 1):
            provider_schema["minItems"] = min_items
        elif min_items is not None:
            source["minItems"] = min_items

    if source:
        existing = provider_schema.get("description")
        constraints = ", ".join(f"{key}: {source[key]}" for key in sorted(source))
        provider_schema["description"] = (
            (f"{existing}\n\n" if isinstance(existing, str) else "")
            + "{"
            + constraints
            + "}"
        )
    return provider_schema


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
            error = response.get("error")
            status = response.get("status")
            expected_fields = {"ok", "error"} | ({"status"} if status is not None else set())
            if (
                response.get("ok") is False
                and set(response) == expected_fields
                and error in CLOSED_PROVIDER_ERROR_CODES
                and (
                    status is None
                    or (isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599)
                )
            ):
                raise SupervisorProviderError(error, status_code=status)
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

    def plan(
        self,
        context: SupervisorContext,
        *,
        required_action_count: Literal[1] | None = None,
    ) -> SupervisorPlan:
        self.settings.require_configured()
        try:
            validate_context(context, self.settings.limits)
        except ValueError as exc:
            raise SupervisorValidationError("Kivou supervisor context is invalid") from exc

        plan_contract = (
            _ExactlyOneActionSupervisorPlan
            if required_action_count == 1
            else SupervisorPlan
        )
        original_schema = plan_contract.model_json_schema()
        provider_schema = transform_provider_schema(original_schema)
        response = self.transport.invoke(
            {
                "operation": "plan",
                "instructions": self._instructions(original_schema),
                "context_json": self._context_json(context),
                "max_tokens": self.settings.limits.max_output_tokens,
                "timeout_seconds": self.settings.limits.invocation_timeout_seconds,
                "provider": OPENROUTER_PROVIDER,
                "model": OPENROUTER_MODEL,
                "provider_routing": OPENROUTER_PROVIDER_ROUTING,
                "response_schema": provider_schema,
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
            plan = plan_contract.model_validate(parsed)
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
