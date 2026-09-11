from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import sqlalchemy as sa
from alembic import command

from signals.company_research.binding import (
    BindingStatus,
    SireneApolloBindingStore,
    SireneApolloResolver,
)
from signals.company_research.domain import DomainResolution
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    acquisition_contact,
    acquisition_contact_suppression,
    acquisition_supplier,
)
from signals.supplier_directory.privacy import SupplierDirectoryPrivacyService
from signals.supplier_directory.store import SupplierDirectoryStore
from signals.supplier_discovery.contracts import SireneOrganizationCandidate

NOW = dt.datetime(2026, 9, 10, 14, tzinfo=dt.UTC)


def _store(tmp_path) -> SupplierDirectoryStore:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'directory.db'}")
    command.upgrade(alembic_config(engine), "head")
    return SupplierDirectoryStore(engine, clock=lambda: NOW)


def test_directory_unions_families_and_dates_each_identity_field(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="subcontracted_structural_work",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW + dt.timedelta(hours=1),
    )

    record = store.get("331364729")

    assert record is not None
    assert record.family_keys == (
        "ready_mix_concrete",
        "subcontracted_structural_work",
    )
    assert record.legal_name_observed_at == NOW + dt.timedelta(hours=1)
    assert record.naf_observed_at == NOW + dt.timedelta(hours=1)
    assert record.department_observed_at == NOW + dt.timedelta(hours=1)
    assert record.city_observed_at == NOW + dt.timedelta(hours=1)
    assert record.employees_observed_at == NOW + dt.timedelta(hours=1)


def test_directory_reuses_fresh_domain_and_expires_it_after_90_days(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )

    assert store.fresh_domain("331364729", at=NOW + dt.timedelta(days=89)) is not None
    assert store.fresh_domain("331364729", at=NOW + dt.timedelta(days=91)) is None


def test_directory_rejects_a_domain_shared_by_two_distinct_sirens(tmp_path) -> None:
    store = _store(tmp_path)
    for siren, name in (("331364729", "ESCOLLE BETON"), ("350064226", "BETON LYON")):
        store.upsert_identity(
            siren=siren,
            legal_name=name,
            naf_code="23.63Z",
            family_key="ready_mix_concrete",
            department="38",
            city="GRENOBLE",
            employees=19,
            observed_at=NOW,
        )

    assert store.record_domain(
        "331364729",
        domain="shared.example",
        website_url="https://shared.example",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    assert not store.record_domain(
        "350064226",
        domain="shared.example",
        website_url="https://shared.example",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW + dt.timedelta(minutes=1),
    )

    for siren in ("331364729", "350064226"):
        record = store.get(siren)
        assert record is not None
        assert record.domain == "shared.example"
        assert record.domain_validation_method is None
        assert record.reverification_reason == "shared_domain_blocklist"
        assert store.fresh_domain(siren, at=NOW + dt.timedelta(minutes=2)) is None


def test_directory_records_dated_contact_form(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )

    store.record_contact_form("331364729", url="https://escolle-beton.fr/contact", observed_at=NOW)

    record = store.get("331364729")
    assert record is not None
    assert record.contact_form_url == "https://escolle-beton.fr/contact"
    assert record.contact_form_observed_at == NOW


def test_directory_marks_missing_website_without_expiration(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )

    assert store.mark_without_website(
        "331364729",
        search_queries_completed=3,
        search_results_examined=30,
        observed_at=NOW,
    )
    assert store.permanently_without_website("331364729")
    assert store.permanently_without_website("331364729")


def test_directory_suppression_clears_only_personal_contact_fields(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_directors(
        "331364729",
        directors=({"name": "Alice Martin", "title": "Gérante"},),
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    store.record_email(
        "331364729",
        email="contact@escolle-beton.fr",
        source="site",
        verification_status="mx_verified",
        contact_name="Alice Martin",
        contact_title="Gérante",
        observed_at=NOW,
    )

    removed_email = store.suppress_personal_data("331364729", at=NOW)
    record = store.get("331364729")

    assert removed_email == "contact@escolle-beton.fr"
    assert record is not None
    assert record.directors == ()
    assert record.professional_email is None
    assert record.domain == "escolle-beton.fr"
    assert record.suppressed_at == NOW


def test_directory_does_not_restore_contact_after_suppression(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.suppress_personal_data("331364729", at=NOW)

    restored = store.record_email(
        "331364729",
        email="contact@escolle-beton.fr",
        source="site",
        verification_status="mx_verified",
        contact_name="Alice Martin",
        contact_title="Gérante",
        observed_at=NOW + dt.timedelta(days=1),
    )

    assert restored is False


def test_directory_marks_untrusted_contact_data_for_reverification(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="societeinfo.com",
        website_url="https://societeinfo.com/escolle",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    store.record_email(
        "331364729",
        email="contact@societeinfo.com",
        source="site",
        verification_status="mx_verified",
        contact_name="ESCOLLE BETON",
        contact_title="Entreprise",
        observed_at=NOW,
    )
    store.record_contact_form("331364729", url="https://societeinfo.com/contact", observed_at=NOW)

    assert store.mark_for_reverification(
        "331364729", reason="third_party_domain", observed_at=NOW + dt.timedelta(hours=1)
    )
    record = store.get("331364729")

    assert record is not None
    assert record.domain is None
    assert record.professional_email is None
    assert record.contact_form_url is None
    assert record.apollo_organization_id is None
    assert record.reverification_required_at == NOW + dt.timedelta(hours=1)
    assert record.reverification_reason == "third_party_domain"


def test_directory_reverification_expected_domain_does_not_clear_a_corrected_domain(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="corrected.example",
        website_url="https://corrected.example",
        source="serper",
        validation_method="registration_number",
        validation_evidence_url="https://corrected.example/mentions-legales",
        observed_at=NOW,
    )

    modified = store.mark_for_reverification(
        "331364729",
        reason="blocked_domain_audit",
        observed_at=NOW + dt.timedelta(hours=1),
        expected_domain="stale.localbiz.fr",
    )

    record = store.get("331364729")
    assert modified is False
    assert record is not None
    assert record.domain == "corrected.example"
    assert record.domain_validation_method == "registration_number"
    assert record.reverification_required_at is None


def test_directory_rejects_email_outside_the_validated_company_domain(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )

    recorded = store.record_email(
        "331364729",
        email="contact@societeinfo.com",
        source="site",
        verification_status="mx_verified",
        contact_name="ESCOLLE BETON",
        contact_title="Entreprise",
        observed_at=NOW,
    )

    assert recorded is False
    assert store.get("331364729").professional_email is None


def test_directory_accepts_cross_domain_email_published_on_confirmed_site(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ALTRAD PREZIOSO",
        naf_code="43.99C",
        family_key="scaffolding",
        department="69",
        city="CHASSE-SUR-RHONE",
        employees=120,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="altrad-prezioso.fr",
        website_url="https://altrad-prezioso.fr",
        source="serper",
        validation_method="registration_number",
        validation_evidence_url="https://altrad-prezioso.fr/mentions-legales",
        observed_at=NOW,
    )

    recorded = store.record_email(
        "331364729",
        email="contact@altrad.com",
        source="site",
        verification_status="mx_verified",
        contact_name="ALTRAD PREZIOSO",
        contact_title="Entreprise",
        evidence_url="https://altrad-prezioso.fr/contact",
        observed_at=NOW,
    )

    assert recorded is True
    record = store.fresh_email("331364729", at=NOW + dt.timedelta(days=1))
    assert record is not None
    assert record.professional_email == "contact@altrad.com"
    assert record.email_evidence_url == "https://altrad-prezioso.fr/contact"


def test_directory_retries_two_connection_failures_at_one_day_before_unreachable(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ALTRAD PREZIOSO",
        naf_code="43.99C",
        family_key="scaffolding",
        department="69",
        city="CHASSE-SUR-RHONE",
        employees=120,
        observed_at=NOW,
    )

    for attempt in range(1, 4):
        store.record_website_connection_failure(
            "331364729", observed_at=NOW + dt.timedelta(days=attempt - 1)
        )
        record = store.get("331364729")
        assert record.website_failure_count == attempt
        if attempt <= 2:
            assert record.website_next_retry_at == NOW + dt.timedelta(days=attempt)
            assert record.website_unreachable_at is None
        else:
            assert record.website_next_retry_at is None
            assert record.website_unreachable_at == NOW + dt.timedelta(days=2)


def test_directory_refuses_permanent_no_site_before_three_full_serper_queries(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ENTREPRISE GIRARD",
        naf_code="43.99C",
        family_key="formwork",
        department="26",
        city="VALENCE",
        employees=20,
        observed_at=NOW,
    )

    assert not store.mark_without_website(
        "331364729",
        search_queries_completed=2,
        search_results_examined=20,
        observed_at=NOW,
    )
    assert store.permanently_without_website("331364729") is False


def test_directory_does_not_reuse_email_after_validated_domain_changes(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    assert store.record_email(
        "331364729",
        email="contact@escolle-beton.fr",
        source="site",
        verification_status="mx_verified",
        contact_name="ESCOLLE BETON",
        contact_title="Entreprise",
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle.fr",
        website_url="https://escolle.fr",
        source="serper",
        validation_method="registration_number",
        validation_evidence_url="https://escolle.fr/mentions-legales",
        observed_at=NOW + dt.timedelta(hours=1),
    )

    assert store.fresh_email(
        "331364729", at=NOW + dt.timedelta(hours=1)
    ) is None


def test_resolver_avoids_serper_and_apollo_for_fresh_directory_binding(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    store = _store(tmp_path)
    engine = store._engine
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    domain = DomainResolution(
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        query="Escolle Beton Saint-Egreve",
        validation_method="name_word",
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain=domain.domain,
        website_url=domain.website_url,
        source=domain.source,
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    store.record_apollo("331364729", organization_id=None, status="unresolved", observed_at=NOW)
    SireneApolloBindingStore(engine, clock=lambda: NOW).put(
        siren="331364729",
        apollo_organization_id=None,
        resolution_method="domain",
        confidence_score=None,
        status=BindingStatus.UNRESOLVED,
        domain_resolution=domain,
    )

    class NoApollo:
        def fetch_organization(self, _profile):
            raise AssertionError("Apollo should be avoided")

    class NoSerper:
        def resolve(self, _identity):
            raise AssertionError("Serper should be avoided")

    identity = SireneOrganizationCandidate(
        provider_organization_id="331364729",
        display_name="ESCOLLE BETON",
        normalized_name="escolle beton",
        location="SAINT-EGREVE",
        industry="ready_mix_concrete:23.63Z",
        provider_observed_at=NOW + dt.timedelta(days=1),
        source_fingerprint="a" * 64,
    )

    binding = SireneApolloResolver(
        engine,
        provider=NoApollo(),
        domain_resolver=NoSerper(),
        directory=store,
        clock=lambda: NOW + dt.timedelta(days=1),
    ).resolve(identity)

    assert binding.status is BindingStatus.UNRESOLVED
    assert "provider_call_avoided" in caplog.text


def test_resolver_clears_cached_binding_domain_when_revalidation_fails(tmp_path) -> None:
    store = _store(tmp_path)
    engine = store._engine
    identity = SireneOrganizationCandidate(
        provider_organization_id="331364729",
        display_name="ESCOLLE BETON",
        normalized_name="escolle beton",
        location="SAINT-EGREVE",
        industry="ready_mix_concrete:23.63Z",
        provider_observed_at=NOW,
        source_fingerprint="a" * 64,
    )
    store.upsert_identity(
        siren="331364729",
        legal_name=identity.display_name,
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city=identity.location,
        employees=19,
        observed_at=NOW,
    )
    domain = DomainResolution(
        domain="stale.example",
        website_url="https://stale.example",
        source="serper",
        query="Escolle Beton Saint-Egreve",
        validation_method="name_word",
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain=domain.domain,
        website_url=domain.website_url,
        source=domain.source,
        validation_method=domain.validation_method,
        validation_evidence_url=None,
        observed_at=NOW,
    )
    store.record_apollo(
        "331364729",
        organization_id="apollo-42",
        status="resolved",
        observed_at=NOW + dt.timedelta(days=100),
    )
    SireneApolloBindingStore(engine, clock=lambda: NOW).put(
        siren="331364729",
        apollo_organization_id="apollo-42",
        resolution_method="domain",
        confidence_score=Decimal("0.95"),
        status=BindingStatus.RESOLVED,
        domain_resolution=domain,
    )

    class NoDomain:
        def resolve(self, _identity):
            return None

    class NoApollo:
        def fetch_organization(self, _profile):
            raise AssertionError("fresh Apollo binding should be reused")

    binding = SireneApolloResolver(
        engine,
        provider=NoApollo(),
        domain_resolver=NoDomain(),
        directory=store,
        clock=lambda: NOW + dt.timedelta(days=100),
    ).resolve(identity)

    assert binding.apollo_organization_id == "apollo-42"
    assert binding.domain is None
    assert SireneApolloBindingStore(engine).get("331364729").domain is None


def test_suppression_request_clears_directory_and_blocks_campaign_identity(tmp_path) -> None:
    store = _store(tmp_path)
    engine = store._engine
    store.upsert_identity(
        siren="331364729",
        legal_name="ESCOLLE BETON",
        naf_code="23.63Z",
        family_key="ready_mix_concrete",
        department="38",
        city="SAINT-EGREVE",
        employees=19,
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain="escolle-beton.fr",
        website_url="https://escolle-beton.fr",
        source="serper",
        validation_method="name_word",
        validation_evidence_url=None,
        observed_at=NOW,
    )
    store.record_email(
        "331364729",
        email="contact@escolle-beton.fr",
        source="site",
        verification_status="mx_verified",
        contact_name="Alice Martin",
        contact_title="Gérante",
        observed_at=NOW,
    )
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_supplier).values(
                supplier_ref="s" * 64,
                provider="sirene",
                provider_organization_id="331364729",
                display_name="ESCOLLE BETON",
                normalized_name="escolle beton",
                country_code="FR",
                location="SAINT-EGREVE",
                industry="ready_mix_concrete:23.63Z",
                identity_status="SIRENE_IDENTIFIED",
                provider_observed_at=NOW,
                source_fingerprint="a" * 64,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(acquisition_contact).values(
                contact_ref="c" * 64,
                supplier_ref="s" * 64,
                provider="company_website",
                provider_person_id="web-alice",
                provider_organization_id="331364729",
                display_name="Alice Martin",
                title="Gérante",
                normalized_title="dirigeant",
                role_profile_version="runtime-qa-contact-v3",
                role_tier=1,
                business_email="contact@escolle-beton.fr",
                provider_email_status="mx_accepted",
                verification_state="DELIVERABILITY_VERIFIED",
                verification_provider="dns_mx",
                provider_observed_at=NOW,
                email_observed_at=NOW,
                source_fingerprint="b" * 64,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    count = SupplierDirectoryPrivacyService(
        engine,
        keyring=SuppressionIdentityKeyring(
            current_key_version="v1", keys={"v1": b"directory-test-key"}
        ),
    ).suppress("331364729", received_at=NOW)

    assert count == 1
    assert store.get("331364729").professional_email is None
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
            )
            == 1
        )
