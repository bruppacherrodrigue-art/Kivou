from __future__ import annotations

from decimal import Decimal

import pytest

from signals.model_runtime.config import (
    MODEL_USAGES,
    ModelUsage,
    routes_from_environment,
)


def test_default_routes_cover_exactly_the_five_declared_usages() -> None:
    snapshot = routes_from_environment(batch_id="defaults", environment={})

    assert MODEL_USAGES == (
        "enrichment_judge",
        "enrichment_arbiter",
        "for_you",
        "hermes",
        "document_classifier",
    )
    assert tuple(route.usage for route in snapshot.routes) == MODEL_USAGES
    assert snapshot.route("enrichment_judge").model == "mistralai/mistral-small"
    assert snapshot.route("enrichment_arbiter").model == "anthropic/claude-sonnet-4.6"
    assert snapshot.route("for_you").model == "anthropic/claude-sonnet-4.6"
    assert snapshot.route("hermes").model == "anthropic/claude-sonnet-4.6"
    assert snapshot.route("document_classifier").model == "anthropic/claude-sonnet-4.6"
    assert snapshot.route("enrichment_judge").daily_budget_usd == Decimal("2")
    assert snapshot.route("for_you").daily_budget_usd == Decimal("1")
    assert snapshot.route("hermes").daily_budget_usd == Decimal("1")
    assert snapshot.timezone == "Europe/Zurich"


def test_route_snapshot_reads_model_and_cap_once_per_batch(monkeypatch) -> None:
    monkeypatch.setenv("KIVOU_MODEL_ENRICHMENT_JUDGE", "google/gemini-flash-lite")
    monkeypatch.setenv("KIVOU_MODEL_BUDGET_ENRICHMENT_JUDGE_USD", "7.50")

    first = routes_from_environment(batch_id="bench-1")
    monkeypatch.setenv("KIVOU_MODEL_ENRICHMENT_JUDGE", "deepseek/deepseek-chat")
    monkeypatch.setenv("KIVOU_MODEL_BUDGET_ENRICHMENT_JUDGE_USD", "9")

    assert first.route("enrichment_judge").model == "google/gemini-flash-lite"
    assert first.route("enrichment_judge").daily_budget_usd == Decimal("7.50")
    second = routes_from_environment(batch_id="bench-2")
    assert second.route("enrichment_judge").model == "deepseek/deepseek-chat"
    assert second.route("enrichment_judge").daily_budget_usd == Decimal("9")


@pytest.mark.parametrize("value", ["", "-1", "NaN", "Infinity", "one"])
def test_invalid_budget_fails_closed_at_batch_start(value: str) -> None:
    environment = {"KIVOU_MODEL_BUDGET_HERMES_USD": value}

    with pytest.raises(ValueError, match="KIVOU_MODEL_BUDGET_HERMES_USD"):
        routes_from_environment(batch_id="invalid", environment=environment)


@pytest.mark.parametrize("batch_id", ["", " ", "x" * 65])
def test_batch_id_is_required_and_bounded(batch_id: str) -> None:
    with pytest.raises(ValueError, match="batch_id"):
        routes_from_environment(batch_id=batch_id, environment={})


def test_unknown_usage_is_rejected() -> None:
    snapshot = routes_from_environment(batch_id="closed", environment={})

    with pytest.raises(ValueError, match="unknown model usage"):
        snapshot.route("contact_lookup")  # type: ignore[arg-type]


def test_model_usage_type_is_closed() -> None:
    assert ModelUsage.__args__ == MODEL_USAGES
