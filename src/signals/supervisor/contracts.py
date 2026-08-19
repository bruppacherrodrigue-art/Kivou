"""Strict Kivou input and advisory-plan contracts for SPEC-017."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from signals.supervisor.registry import ALLOWED_COMMANDS

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ShortCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Decision = Literal["SEND", "HOLD", "ENRICH", "NO_SEND", "REVIEW"]


class SupervisorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class SupervisorLimits(SupervisorModel):
    invocation_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_context_bytes: int = Field(default=65_536, ge=1_024, le=1_000_000)
    max_context_items: int = Field(default=50, ge=1, le=500)
    max_planned_actions: int = Field(default=10, ge=1, le=100)
    max_output_bytes: int = Field(default=131_072, ge=1_024, le=1_000_000)
    max_output_tokens: int = Field(default=2_048, ge=128, le=16_384)


class BudgetEnvelope(SupervisorModel):
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    maximum_cycle_cost: Decimal = Field(ge=0)


class PublicFacts(SupervisorModel):
    source: ShortCode
    title: NonEmpty | None = None
    description: Annotated[str, StringConstraints(max_length=8_000)] | None = None
    evidence_refs: tuple[ShortCode, ...] = Field(default=(), max_length=100)


class KivouAnalysis(SupervisorModel):
    opportunity_key: ShortCode
    decision: Decision
    plausible_needs: tuple[ShortCode, ...] = Field(default=(), max_length=50)
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=50)


class OpportunitySummary(SupervisorModel):
    object_ref: ShortCode
    public_facts: PublicFacts
    kivou_analysis: KivouAnalysis


class OperationalOutcome(SupervisorModel):
    outcome_id: ShortCode
    decision: Decision
    occurred_at: dt.datetime
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=50)

    _validate_occurred_at = field_validator("occurred_at")(_aware)


class SupervisorContext(SupervisorModel):
    current_time: dt.datetime
    runtime_mode: Literal["SHADOW"]
    policy_version: ShortCode
    budget: BudgetEnvelope
    available_commands: tuple[ShortCode, ...] = Field(min_length=1, max_length=100)
    opportunities: tuple[OpportunitySummary, ...] = Field(default=(), max_length=500)
    recent_outcomes: tuple[OperationalOutcome, ...] = Field(default=(), max_length=500)

    _validate_current_time = field_validator("current_time")(_aware)


def _validate_json(value: dict[str, Any]) -> dict[str, Any]:
    try:
        json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("arguments must contain finite JSON values") from exc
    return value


class ProposedAction(SupervisorModel):
    command: ShortCode
    target_ref: ShortCode
    arguments: dict[str, Any]
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=50)
    evidence_refs: tuple[ShortCode, ...] = Field(default=(), max_length=100)
    estimated_cost: Decimal = Field(ge=0)

    _json_arguments = field_validator("arguments")(_validate_json)


class SupervisorPlan(SupervisorModel):
    plan_id: ShortCode
    created_at: dt.datetime
    objective: NonEmpty
    priority: int = Field(ge=1, le=5)
    proposed_actions: tuple[ProposedAction, ...] = Field(default=(), max_length=100)
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=50)
    confidence: Decimal = Field(ge=0, le=1)
    estimated_cost: Decimal = Field(ge=0)
    next_review_at: dt.datetime
    supervisor_version: ShortCode
    skill_version: ShortCode

    _validate_created_at = field_validator("created_at")(_aware)
    _validate_next_review_at = field_validator("next_review_at")(_aware)


def validate_context(context: SupervisorContext, limits: SupervisorLimits) -> None:
    unknown = set(context.available_commands).difference(ALLOWED_COMMANDS)
    if unknown:
        raise ValueError(f"unknown command in context: {min(unknown)}")
    if len(context.opportunities) > limits.max_context_items:
        raise ValueError("maximum opportunity context items exceeded")
    if len(context.recent_outcomes) > limits.max_context_items:
        raise ValueError("maximum operational outcome context items exceeded")
    size = len(context.model_dump_json().encode("utf-8"))
    if size > limits.max_context_bytes:
        raise ValueError(f"context bytes exceed configured maximum: {size}")


def validate_plan(plan: SupervisorPlan, limits: SupervisorLimits) -> None:
    if len(plan.proposed_actions) > limits.max_planned_actions:
        raise ValueError("maximum planned actions exceeded")
    unknown = [
        action.command for action in plan.proposed_actions if action.command not in ALLOWED_COMMANDS
    ]
    if unknown:
        raise ValueError(f"unknown command in plan: {unknown[0]}")
