from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest

from signals.model_runtime.budget import DailyModelBudgetExhausted, ModelBudgetStore
from signals.model_runtime.config import ModelRoute
from signals.model_runtime.openrouter import OpenRouterGateway


class RecordingClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def post(self, url, **kwargs):
        self.requests.append({"url": url, **kwargs})
        return self.response


def _response(
    *, status: int = 200, content: str = '{"answer":"ok"}'
) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 812,
                "completion_tokens": 42,
                "cost": 0.00037,
            },
        },
    )


def _route(cap: str = "2") -> ModelRoute:
    return ModelRoute(
        usage="enrichment_judge",
        model="mistralai/mistral-small",
        daily_budget_usd=Decimal(cap),
        reserve_input_usd_per_million=Decimal("0.20"),
        reserve_output_usd_per_million=Decimal("0.60"),
    )


@pytest.fixture
def store(migrated_sqlite_engine) -> ModelBudgetStore:
    return ModelBudgetStore(
        migrated_sqlite_engine,
        clock=lambda: dt.datetime(2026, 9, 12, 10, tzinfo=dt.UTC),
    )


def test_gateway_reserves_before_http_and_journals_real_usage(
    store: ModelBudgetStore,
) -> None:
    client = RecordingClient(_response())
    gateway = OpenRouterGateway(api_key="secret", budgets=store, client=client)

    result = gateway.json_call(
        route=_route(),
        messages=[{"role": "user", "content": "x"}],
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
        schema_name="answer",
        max_tokens=300,
        siren="123456789",
        batch_id="bench",
    )

    assert result.content == '{"answer":"ok"}'
    assert result.input_tokens == 812
    assert result.output_tokens == 42
    assert result.actual_usd == Decimal("0.00037")
    assert len(client.requests) == 1
    request = client.requests[0]
    assert request["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert request["headers"]["authorization"] == "Bearer secret"  # type: ignore[index]
    call = store.calls()[0]
    assert call.status == "succeeded"
    assert call.actual_usd == Decimal("0.00037000")
    assert call.input_tokens == 812


def test_budget_rejection_makes_no_http_call(store: ModelBudgetStore) -> None:
    client = RecordingClient(_response())
    gateway = OpenRouterGateway(api_key="secret", budgets=store, client=client)

    with pytest.raises(DailyModelBudgetExhausted):
        gateway.json_call(
            route=_route(cap="0"),
            messages=[{"role": "user", "content": "x"}],
            schema={"type": "object"},
            schema_name="answer",
            max_tokens=300,
        )

    assert client.requests == []
    assert store.calls()[0].status == "rejected_budget"


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (_response(status=503), "PROVIDER_HTTP_503"),
        (httpx.Response(200, content=b"x" * 262_145), "PROVIDER_RESPONSE_TOO_LARGE"),
        (httpx.Response(200, json={"choices": []}), "PROVIDER_INVALID_RESPONSE"),
    ],
)
def test_provider_failures_release_reservation_and_are_journalled(
    store: ModelBudgetStore, response: httpx.Response, error_code: str
) -> None:
    client = RecordingClient(response)
    gateway = OpenRouterGateway(api_key="secret", budgets=store, client=client)

    with pytest.raises(RuntimeError, match=error_code):
        gateway.json_call(
            route=_route(),
            messages=[{"role": "user", "content": "x"}],
            schema={"type": "object"},
            schema_name="answer",
            max_tokens=300,
        )

    call = store.calls()[0]
    assert call.status == "failed"
    assert call.error_code == error_code
    assert store.summary("enrichment_judge").reserved_usd == Decimal("0E-8")


def test_reservation_uses_conservative_utf8_estimate(store: ModelBudgetStore) -> None:
    gateway = OpenRouterGateway(
        api_key="secret", budgets=store, client=RecordingClient(_response())
    )

    result = gateway.json_call(
        route=_route(),
        messages=[{"role": "user", "content": "é" * 900}],
        schema={"type": "object"},
        schema_name="answer",
        max_tokens=300,
    )

    assert result.reserved_usd >= Decimal("0.000300")


def test_api_key_is_required(store: ModelBudgetStore) -> None:
    with pytest.raises(ValueError, match="OpenRouter API key"):
        OpenRouterGateway(api_key=" ", budgets=store)


def test_text_call_is_metered_without_a_response_schema(store: ModelBudgetStore) -> None:
    client = RecordingClient(_response(content='{"sentence":"Bonjour"}'))
    gateway = OpenRouterGateway(api_key="secret", budgets=store, client=client)

    result = gateway.text_call(
        route=ModelRoute(
            usage="for_you",
            model="anthropic/claude-sonnet-4.6",
            daily_budget_usd=Decimal("1"),
        ),
        messages=[{"role": "user", "content": "Rédige une phrase"}],
        max_tokens=100,
        batch_id="for-you-1",
    )

    assert result.content == '{"sentence":"Bonjour"}'
    assert "response_format" not in client.requests[0]["json"]  # type: ignore[operator]
    assert store.calls()[0].usage == "for_you"
