"""Translate advisory SPEC-017 actions into strict Kivou policy requests."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from enum import Enum
from typing import Any

from signals.policy.contracts import PolicyRequest
from signals.supervisor.contracts import ProposedAction

_PROHIBITED = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "authorization",
        "access_token",
        "refresh_token",
        "session_token",
        "private_key",
        "chain_of_thought",
        "reasoning_trace",
        "scratchpad",
        "hidden_reasoning",
    }
)


def _normalized(value: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _guard(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = _normalized(str(key))
            if normalized in _PROHIBITED:
                raise ValueError(f"prohibited policy argument key: {normalized}")
            _guard(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _guard(nested)


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _canonical(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(nested) for nested in value]
    return value


def map_proposed_action(action: ProposedAction, **trusted: Any) -> PolicyRequest:
    """Map one validated advisory intent; trusted controls are supplied by Kivou."""
    _guard(action.arguments)
    if action.command == "classify_response":
        if action.arguments:
            raise ValueError("classify_response accepts only an opaque response reference")
        if re.fullmatch(r"[0-9a-f]{64}", action.target_ref) is None:
            raise ValueError("classify_response requires an opaque response reference")
    if action.command == "reallocate_volume":
        if action.target_ref != "global:acquisition-allocation-v1":
            raise ValueError("reallocate_volume requires the frozen global target")
        if (
            set(action.arguments) != {"proposal_ref"}
            or re.fullmatch(r"[0-9a-f]{64}", str(action.arguments.get("proposal_ref", ""))) is None
        ):
            raise ValueError("reallocate_volume accepts only an opaque proposal_ref")
    if action.command == "generate_weekly_report":
        if action.target_ref != "global:commercial-cockpit-v1":
            raise ValueError("generate_weekly_report requires the frozen global target")
        if action.arguments:
            raise ValueError("generate_weekly_report accepts no arguments")
    arguments = json.dumps(action.arguments, allow_nan=False, sort_keys=True, separators=(",", ":"))
    semantic = {
        "command": action.command,
        "target_ref": action.target_ref,
        "arguments": action.arguments,
        "acquisition_opportunity_id": trusted.get("acquisition_opportunity_id"),
        "scope": _canonical(trusted.get("scope")),
        "estimated_cost": action.estimated_cost,
        "currency": trusted.get("currency"),
        "proposed_volume": trusted.get("proposed_volume", 0),
    }
    encoded = json.dumps(
        _canonical(semantic), allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return PolicyRequest(
        **trusted,
        command=action.command,
        target_ref=action.target_ref,
        canonical_arguments=arguments,
        action_fingerprint=hashlib.sha256(encoded).hexdigest(),
        reason_codes=action.reason_codes,
        evidence_refs=action.evidence_refs,
        proposed_cost=action.estimated_cost,
    )
