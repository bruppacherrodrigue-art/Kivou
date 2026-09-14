from __future__ import annotations

from decimal import Decimal

import pytest

from signals.company_research.enrichment import CompanyEnrichmentRunResult
from signals.company_research.instance_lock import InstanceAlreadyRunning, exclusive_instance_lock
from signals.company_research.replay import _execute_cohort, main
from signals.model_runtime.budget import DailyModelBudgetExhausted


class BudgetedService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def enrich(self, siren: str, *, force: bool):
        self.calls.append(siren)
        if len(self.calls) == 2:
            raise DailyModelBudgetExhausted(
                usage="enrichment_judge",
                cap_usd=Decimal("2"),
                actual_usd=Decimal("1.9"),
                reserved_usd=Decimal("0.09"),
                requested_usd=Decimal("0.02"),
            )
        return CompanyEnrichmentRunResult(
            siren=siren,
            cached=False,
            website_retained=False,
            email_retained=False,
            family_confirmed=False,
            reverification_required=True,
            cost_usd=Decimal("0.01"),
        )


def test_replay_stops_cleanly_when_daily_model_budget_is_exhausted() -> None:
    service = BudgetedService()

    result = _execute_cohort(
        service=service,
        sirens=("100000001", "100000002", "100000003"),
        workers=1,
        force=False,
    )

    assert result.status == "stopped_budget"
    assert result.processed == 1
    assert result.cost_usd == Decimal("0.01")
    assert result.errors == ()
    assert result.budget_usage == "enrichment_judge"
    assert service.calls == ["100000001", "100000002"]


def test_instance_lock_refuses_a_second_holder(tmp_path) -> None:
    path = tmp_path / "replay.lock"

    with (
        exclusive_instance_lock(path),
        pytest.raises(InstanceAlreadyRunning),
        exclusive_instance_lock(path),
    ):
        raise AssertionError("the second holder must never enter")


def test_replay_refuses_a_second_launch_before_provider_configuration(
    tmp_path, monkeypatch, capsys
) -> None:
    path = tmp_path / "replay.lock"
    monkeypatch.setenv("KIVOU_ENRICHMENT_REPLAY_LOCK_FILE", str(path))
    monkeypatch.delenv("KIVOU_SERPER_API_KEY", raising=False)

    with exclusive_instance_lock(path):
        result = main([])

    assert result == 75
    assert "INSTANCE_ALREADY_RUNNING" in capsys.readouterr().err
