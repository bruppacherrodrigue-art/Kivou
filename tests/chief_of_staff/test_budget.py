from __future__ import annotations

from decimal import Decimal

import pytest

from signals.chief_of_staff.hermes import ChiefOfStaffHermesAdapter
from signals.model_runtime.config import ModelRoute

from .test_hermes import MODEL_ENV, Transport, bridge_response, context, settings, valid_report


class Budget:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.events: list[tuple[str, object]] = []

    def reserve(self, **values: object) -> None:
        self.events.append(("reserve", values))
        if self.reject:
            raise RuntimeError("budget refused")

    def succeed(self, **values: object) -> None:
        self.events.append(("succeed", values))

    def fail(self, **values: object) -> None:
        self.events.append(("fail", values))


def route() -> ModelRoute:
    return ModelRoute(
        usage="chief_of_staff",
        model="anthropic/claude-sonnet-4.6",
        daily_budget_usd=Decimal("1"),
    )


def test_budget_is_reserved_before_call_and_finalized_from_usage(tmp_path) -> None:
    budget = Budget()
    response = bridge_response(valid_report())
    response["usage"] = {
        "input_tokens": 900,
        "output_tokens": 150,
        "cost_usd": "0.0045",
    }
    transport = Transport(response)
    result = ChiefOfStaffHermesAdapter(
        settings(tmp_path),
        transport=transport,
        model_route=route(),
        budget_store=budget,
        batch_id="chief-daily",
        environment=MODEL_ENV,
    ).generate(context())

    assert [event[0] for event in budget.events] == ["reserve", "succeed"]
    assert len(transport.requests) == 1
    assert result.actual_usd == Decimal("0.0045")
    assert result.input_tokens == 900
    assert result.output_tokens == 150


def test_budget_refusal_happens_before_transport(tmp_path) -> None:
    budget = Budget(reject=True)
    transport = Transport(bridge_response(valid_report()))
    with pytest.raises(RuntimeError, match="budget refused"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            model_route=route(),
            budget_store=budget,
            environment=MODEL_ENV,
        ).generate(context())
    assert transport.requests == []


def test_transport_failure_releases_reservation(tmp_path) -> None:
    budget = Budget()
    transport = Transport(error=TimeoutError("offline"))
    with pytest.raises(TimeoutError):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            model_route=route(),
            budget_store=budget,
            environment=MODEL_ENV,
        ).generate(context())
    assert [event[0] for event in budget.events] == ["reserve", "fail"]


def test_adapter_rejects_missing_route_before_transport(tmp_path) -> None:
    transport = Transport(bridge_response(valid_report()))
    with pytest.raises(ValueError, match="model route"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            budget_store=Budget(),
            environment=MODEL_ENV,
        )
    assert transport.requests == []


def test_adapter_rejects_missing_budget_store_before_transport(tmp_path) -> None:
    transport = Transport(bridge_response(valid_report()))
    with pytest.raises(ValueError, match="budget store"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            model_route=route(),
            environment=MODEL_ENV,
        )
    assert transport.requests == []


def test_adapter_rejects_wrong_route_usage_before_transport(tmp_path) -> None:
    wrong = ModelRoute(
        usage="hermes",
        model="anthropic/claude-sonnet-4.6",
        daily_budget_usd=Decimal("1"),
    )
    transport = Transport(bridge_response(valid_report()))
    with pytest.raises(ValueError, match="chief_of_staff"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            model_route=wrong,
            budget_store=Budget(),
            environment=MODEL_ENV,
        )
    assert transport.requests == []


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"OPENROUTER_MODEL": "fallback/must-not-be-used"},
        {"KIVOU_MODEL_CHIEF_OF_STAFF": "anthropic/claude-sonnet-4.6"},
    ],
)
def test_adapter_rejects_absent_or_partial_configuration_before_transport(
    tmp_path, environment
) -> None:
    transport = Transport(bridge_response(valid_report()))
    with pytest.raises((ValueError, RuntimeError), match="configured|variables"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=transport,
            model_route=route(),
            budget_store=Budget(),
            environment=environment,
        )
    assert transport.requests == []


def test_adapter_rejects_route_that_differs_from_environment(tmp_path) -> None:
    configured = {**MODEL_ENV, "KIVOU_MODEL_CHIEF_OF_STAFF": "model/other"}
    with pytest.raises(ValueError, match="configured route"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path),
            transport=Transport(bridge_response(valid_report())),
            model_route=route(),
            budget_store=Budget(),
            environment=configured,
        )
