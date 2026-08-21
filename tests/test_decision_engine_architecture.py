from __future__ import annotations

import inspect

import signals.decision_engine.contracts as contracts_module
import signals.decision_engine.evaluator as evaluator_module
import signals.decision_engine.input as input_module
import signals.decision_engine.service as service_module


def test_decision_engine_has_no_customer_private_or_external_dependencies() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            contracts_module,
            evaluator_module,
            input_module,
            service_module,
        )
    )
    for forbidden in (
        "TargetICP",
        "signals.accounts",
        "signals.billing",
        "signals.matching",
        "materialized_signal",
        "customer feedback",
        "business_email",
        "first_name",
        "last_name",
        "linkedin",
        "httpx",
        "requests.",
        "instantly",
        "smtp",
        "openai",
    ):
        assert forbidden.lower() not in source.lower()


def test_decision_authorization_cannot_supply_business_result_or_clock() -> None:
    fields = set(contracts_module.DecisionAuthorizationInput.model_fields)
    assert not {
        "evaluated_at",
        "as_of_date",
        "proposed_decision",
        "decision",
        "score",
        "threshold",
        "reason_codes",
        "evidence_refs",
    } & fields
