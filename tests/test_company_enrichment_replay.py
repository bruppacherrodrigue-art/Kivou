from __future__ import annotations

from decimal import Decimal

from signals.company_research.enrichment import CompanyEnrichmentRunResult
from signals.company_research.replay import _execute_cohort
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
