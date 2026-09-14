"""Refreshes preserve field-level facts when providers return incomplete evidence."""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from signals.company_research.company_requests import (
    request_enrichment,
    run_company_enrichment_requests,
)
from signals.company_research.enrichment import (
    CompanyEnrichmentDecision,
    CompanyEnrichmentInput,
    CompanyEnrichmentProviderResult,
    CompanyEnrichmentService,
    CompanyWebEvidence,
)
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 9, 14, 10, tzinfo=dt.UTC)
OLD = NOW - dt.timedelta(days=91)
SIREN = "481153435"


@pytest.fixture
def engine(tmp_path):
    result = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'preservation.db'}")
    migrate_to_latest(result)
    yield result
    result.dispose()


def seed(engine):
    store = SupplierDirectoryStore(engine)
    store.upsert_identity(
        siren=SIREN, legal_name="ALYA", naf_code="43.99C", naf_label="Maçonnerie",
        family_key="subcontracted_structural_work", department="01", city="GUEREINS",
        employees=19, observed_at=OLD,
    )
    with engine.begin() as connection:
        connection.execute(supplier_directory.update().values(
            family_source="model", family_confirmation_status="confirmed",
            family_confidence=Decimal(".94"), phone="+33412345678",
            phone_source="model", phone_observed_at=OLD,
        ))
    return store


def service(store, *, phone=None, fail=False):
    def provide(_identity, _evidence):
        if fail:
            raise RuntimeError("offline provider failure")
        return CompanyEnrichmentProviderResult(
            decision=CompanyEnrichmentDecision(
                website=None, website_confidence=0, email=None, email_confidence=0,
                email_is_placeholder=False, family=None, family_confidence=0,
                director_display_name=None, phone=phone, requested_page_url=None,
                notes="No new supported fact",
            ),
            model="offline/judge", cost_usd=Decimal(0), input_tokens=0, output_tokens=0,
        )

    return CompanyEnrichmentService(
        directory=store,
        collector=SimpleNamespace(collect=lambda _identity: CompanyWebEvidence(
            query="ALYA", results=(), candidate_pages=(),
        )),
        provider=SimpleNamespace(enrich=provide), mx_verifier=lambda _: False,
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("fail", [False, True])
def test_manual_worker_preserves_missing_registry_facts_and_old_confirmed_family(engine, fail):
    store = seed(engine)
    with engine.begin() as connection:
        request_enrichment(connection, siren=SIREN, now=NOW)
    batch = run_company_enrichment_requests(
        engine, now=NOW, worker_ref="preservation-test", limit=1,
        identity_source=lambda siren: CompanyEnrichmentInput(siren=siren, legal_name="ALYA SA"),
        enrichment_service=service(store, fail=fail),
    )
    assert batch.failed == int(fail) and batch.completed == int(not fail)
    actual = store.get(SIREN)
    assert actual.legal_name == "ALYA SA"
    assert actual.employees == 19
    assert actual.city == "GUEREINS" and actual.department == "01"
    assert actual.naf_code == "43.99C" and actual.naf_label == "Maçonnerie"
    assert actual.employees_observed_at == actual.city_observed_at == OLD
    assert actual.department_observed_at == actual.naf_observed_at == OLD
    assert actual.naf_label_observed_at == OLD
    assert actual.family_keys == ("subcontracted_structural_work",)
    assert actual.family_source == "model" and actual.family_confirmation_status == "confirmed"
    assert actual.family_confidence == Decimal(".94") and actual.families_observed_at == OLD


@pytest.mark.parametrize("phone", ["", "N/A", "123"])
def test_unusable_model_phone_cannot_erase_a_known_public_number(engine, phone):
    store = seed(engine)
    service(store, phone=phone).enrich(SIREN, force=True)
    actual = store.get(SIREN)
    assert actual.phone == "+33412345678"
    assert actual.phone_source == "model" and actual.phone_observed_at == OLD


def test_real_new_registry_values_still_replace_old_facts_in_manual_worker(engine):
    store = seed(engine)
    with engine.begin() as connection:
        request_enrichment(connection, siren=SIREN, now=NOW)
    run_company_enrichment_requests(
        engine, now=NOW, worker_ref="preservation-test", limit=1,
        identity_source=lambda siren: CompanyEnrichmentInput(
            siren=siren, legal_name="ALYA SA", employees=0, city="LYON", department="69",
            naf_code="43.91A", naf_label="Charpente",
        ),
        enrichment_service=service(store),
    )
    actual = store.get(SIREN)
    assert actual.employees == 0 and actual.city == "LYON" and actual.department == "69"
    assert actual.naf_code == "43.91A" and actual.naf_label == "Charpente"
    assert actual.employees_observed_at == actual.city_observed_at == NOW
