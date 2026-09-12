from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from signals.company_research.enrichment import (
    CompanyEnrichmentDecision,
    CompanyEnrichmentProviderResult,
    CompanyEnrichmentService,
    CompanyWebCollector,
    RenderedPage,
)
from signals.company_research.providers import company_enrichment_providers_from_environment
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC)


def _decision(**updates: object) -> CompanyEnrichmentDecision:
    values: dict[str, object] = {
        "website": "alyabat.fr",
        "website_confidence": Decimal("0.98"),
        "email": "contact@alyabat.fr",
        "email_confidence": Decimal("0.97"),
        "email_is_placeholder": False,
        "family": "subcontracted_structural_work",
        "family_confidence": Decimal("0.94"),
        "director_display_name": None,
        "phone": None,
        "requested_page_url": None,
        "notes": "preuves concordantes",
    }
    values.update(updates)
    return CompanyEnrichmentDecision.model_validate(values)


class Provider:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.judge_outputs: list[object | None] = []

    def enrich(self, identity, evidence):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return CompanyEnrichmentProviderResult(
            decision=outcome,
            model="test/model",
            cost_usd=Decimal("0.0004"),
            input_tokens=900,
            output_tokens=80,
        )

    def arbitrate(self, identity, evidence, judge_output):
        self.judge_outputs.append(judge_output)
        return self.enrich(identity, evidence)


class Collector:
    def __init__(self) -> None:
        self.calls = 0
        self.requested: list[str] = []

    def collect(self, identity):
        self.calls += 1
        return CompanyWebCollector.evidence_for_test(
            identity, domain="alyabat.fr", contact_text="contact@alyabat.fr"
        )

    def fetch_requested(self, evidence, requested_url):
        self.requested.append(requested_url)
        return evidence.model_copy(
            update={
                "candidate_pages": (
                    *evidence.candidate_pages,
                    RenderedPage(
                        url=requested_url,
                        status_code=200,
                        title="Equipe",
                        text="contact@alyabat.fr",
                        published_emails=("contact@alyabat.fr",),
                    ),
                )
            }
        )


def _service(migrated_sqlite_engine, judge: Provider, arbiter: Provider, collector=None):
    store = SupplierDirectoryStore(migrated_sqlite_engine, clock=lambda: NOW)
    store.upsert_identity(
        siren="481153435",
        legal_name="ALYA BATIMENT",
        naf_code="43.99C",
        family_key="subcontracted_structural_work",
        department="01",
        city="GUEREINS",
        employees=19,
        observed_at=NOW,
        naf_label="Maçonnerie",
    )
    return CompanyEnrichmentService(
        directory=store,
        collector=collector or Collector(),
        provider=judge,
        arbiter=arbiter,
        mx_verifier=lambda _email: True,
        clock=lambda: NOW,
    )


def test_high_confidence_valid_judge_does_not_call_arbiter(
    migrated_sqlite_engine,
) -> None:
    judge = Provider([_decision()])
    arbiter = Provider([_decision()])

    _service(migrated_sqlite_engine, judge, arbiter).enrich("481153435")

    assert judge.calls == 1
    assert arbiter.calls == 0


@pytest.mark.parametrize(
    "decision",
    [
        _decision(website_confidence=Decimal("0.79")),
        _decision(email_confidence=Decimal("0.79")),
    ],
)
def test_low_site_or_email_confidence_calls_sonnet_once(migrated_sqlite_engine, decision) -> None:
    judge = Provider([decision])
    arbiter = Provider([_decision()])

    _service(migrated_sqlite_engine, judge, arbiter).enrich("481153435")

    assert judge.calls == 1
    assert arbiter.calls == 1


def test_invalid_judge_json_calls_sonnet_once(migrated_sqlite_engine) -> None:
    from signals.company_research.enrichment import InvalidCompanyEnrichmentDecision

    judge = Provider([InvalidCompanyEnrichmentDecision("invalid JSON", raw_content="not-json")])
    arbiter = Provider([_decision()])

    _service(migrated_sqlite_engine, judge, arbiter).enrich("481153435")

    assert judge.calls == 1
    assert arbiter.calls == 1
    assert arbiter.judge_outputs == ["not-json"]


def test_invalid_judge_never_calls_the_same_arbiter_twice_on_low_confidence(
    migrated_sqlite_engine,
) -> None:
    from signals.company_research.enrichment import InvalidCompanyEnrichmentDecision

    judge = Provider([InvalidCompanyEnrichmentDecision("invalid JSON")])
    arbiter = Provider([_decision(email_confidence=Decimal("0.50"))])

    _service(migrated_sqlite_engine, judge, arbiter).enrich("481153435")

    assert judge.calls == 1
    assert arbiter.calls == 1


def test_transport_failure_does_not_spend_on_arbiter(migrated_sqlite_engine) -> None:
    judge = Provider([RuntimeError("PROVIDER_NETWORK")])
    arbiter = Provider([_decision()])

    with pytest.raises(RuntimeError, match="PROVIDER_NETWORK"):
        _service(migrated_sqlite_engine, judge, arbiter).enrich("481153435")

    assert arbiter.calls == 0


def test_judge_can_request_one_same_site_page_before_final_decision(
    migrated_sqlite_engine,
) -> None:
    collector = Collector()
    judge = Provider(
        [
            _decision(
                email=None,
                email_confidence=Decimal("0"),
                requested_page_url="https://alyabat.fr/equipe",
            ),
            _decision(),
        ]
    )
    arbiter = Provider([_decision()])

    _service(migrated_sqlite_engine, judge, arbiter, collector).enrich("481153435")

    assert judge.calls == 2
    assert collector.requested == ["https://alyabat.fr/equipe"]
    assert arbiter.calls == 0


def test_environment_factory_builds_distinct_judge_and_arbiter_routes(
    migrated_sqlite_engine,
) -> None:
    providers = company_enrichment_providers_from_environment(
        engine=migrated_sqlite_engine,
        batch_id="lot-1",
        environment={"OPENROUTER_API_KEY": "secret"},
    )

    assert providers.judge.usage == "enrichment_judge"
    assert providers.judge.model == "mistralai/mistral-small"
    assert providers.arbiter.usage == "enrichment_arbiter"
    assert providers.arbiter.model == "anthropic/claude-sonnet-4.6"
    assert providers.routes.batch_id == "lot-1"
