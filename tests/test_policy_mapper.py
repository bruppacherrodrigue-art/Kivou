from __future__ import annotations

from decimal import Decimal

import pytest
from test_policy_gateway import request

from signals.policy.mapper import map_proposed_action
from signals.supervisor.contracts import ProposedAction


def action(arguments: dict[str, object] | None = None) -> ProposedAction:
    return ProposedAction(
        command="evaluate_opportunity",
        target_ref="target-1",
        arguments={} if arguments is None else arguments,
        reason_codes=("qualified",),
        evidence_refs=("evidence-1",),
        estimated_cost=Decimal("1"),
    )


def test_mapper_canonicalizes_arguments_and_fingerprints_deterministically() -> None:
    trusted = request().model_dump(mode="python")
    for key in (
        "command",
        "target_ref",
        "canonical_arguments",
        "action_fingerprint",
        "reason_codes",
        "evidence_refs",
        "proposed_cost",
    ):
        trusted.pop(key)
    first = map_proposed_action(action({"b": 2, "a": 1}), **trusted)
    second = map_proposed_action(action({"a": 1, "b": 2}), **trusted)
    assert first.canonical_arguments == '{"a":1,"b":2}'
    assert first.action_fingerprint == second.action_fingerprint


@pytest.mark.parametrize("arguments", [{"api_key": "x"}, {"nested": {"chainOfThought": "x"}}])
def test_mapper_rejects_secret_and_hidden_reasoning_keys(arguments: dict[str, object]) -> None:
    trusted = request().model_dump(mode="python")
    for key in (
        "command",
        "target_ref",
        "canonical_arguments",
        "action_fingerprint",
        "reason_codes",
        "evidence_refs",
        "proposed_cost",
    ):
        trusted.pop(key)
    with pytest.raises(ValueError, match="prohibited"):
        map_proposed_action(action(arguments), **trusted)
