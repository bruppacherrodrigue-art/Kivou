from __future__ import annotations

import datetime as dt
import logging

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
        observed_at=NOW,
    )

    assert store.fresh_domain("331364729", at=NOW + dt.timedelta(days=89)) is not None
    assert store.fresh_domain("331364729", at=NOW + dt.timedelta(days=91)) is None


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
        observed_at=NOW,
    )
    store.record_domain(
        "331364729",
        domain=domain.domain,
        website_url=domain.website_url,
        source=domain.source,
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
