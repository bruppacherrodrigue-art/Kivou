from __future__ import annotations

import datetime as dt
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from feed_helpers import SIMAP_RICH, make_account, make_icp, materialize_simap

from signals.client_value.contact_lookup import (
    PLAN_MONTHLY_QUOTAS,
    CompanyContactLookupService,
    CompanyLookupIdentity,
    ContactLookupIdentityUnavailable,
    ContactLookupProviderFailure,
    ContactLookupQuotaExceeded,
    ContactLookupSuppressed,
)
from signals.companies.schema import (
    company_contact_lookup,
    company_contact_lookup_attempt,
    saas_company,
)
from signals.companies.service import ensure_companies_for_signal_keys
from signals.company_research.contracts import (
    ApolloOrganizationObservation,
    CompanyResearchProviderError,
)
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    PeopleSearchCandidate,
    PeopleSearchPage,
)
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import supplier_directory

NOW = dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC)


class FakeCompanyResearch:
    def __init__(self) -> None:
        self.calls = 0
        self.profiles = []

    def fetch_organization(self, profile):
        self.calls += 1
        self.profiles.append(profile)
        return ApolloOrganizationObservation(
            provider_organization_id=profile.provider_organization_id or "apollo-org-1",
            provider_company_name=profile.organization_name or "Entreprise",
            provider_primary_domain="holder.example",
            provider_website_url="https://holder.example/",
            provider_country="France",
            provider_employee_count=84,
            provider_observed_at=NOW,
            provider_source_fingerprint="a" * 64,
            resolution_method="name_city",
            resolution_confidence_score="0.95",
        )


class FakeContactDiscovery:
    def __init__(self) -> None:
        self.search_calls = 0
        self.match_calls = 0
        self.organization_id = "apollo-org-1"

    def search_people(self, profile, *, observed_at):
        self.search_calls += 1
        self.organization_id = profile.provider_organization_id
        return PeopleSearchPage(
            total_entries=3,
            candidates=tuple(
                PeopleSearchCandidate(
                    provider_person_id=f"person-{index}",
                    first_name=first_name,
                    last_name_obfuscated="M***",
                    title=title,
                    provider_position=index,
                    organization_name=profile.organization_name,
                    has_email=True,
                )
                for index, (first_name, title) in enumerate(
                    (
                        ("Alice", "Directrice commerciale"),
                        ("Bruno", "Responsable commercial"),
                        ("Chloé", "Dirigeante"),
                    )
                )
            ),
            rejections=(),
            observed_at=observed_at,
        )

    def enrich_person(self, provider_person_id, *, observed_at):
        self.match_calls += 1
        number = int(provider_person_id.rsplit("-", 1)[1])
        names = ("Alice Martin", "Bruno Meyer", "Chloé Dupont")
        titles = ("Directrice commerciale", "Responsable commercial", "Dirigeante")
        return ApolloEnrichedPerson(
            provider_person_id=provider_person_id,
            provider_organization_id=self.organization_id,
            display_name=names[number],
            title=titles[number],
            business_email=f"person-{number}@holder.example",
            provider_email_status="verified",
            provider_observed_at=observed_at,
            source_fingerprint=f"{number + 1}" * 64,
        )


class EmptyContactDiscovery(FakeContactDiscovery):
    def search_people(self, profile, *, observed_at):
        self.search_calls += 1
        return PeopleSearchPage(
            total_entries=0,
            candidates=(),
            rejections=(),
            observed_at=observed_at,
        )


class FailingCompanyResearch(FakeCompanyResearch):
    def fetch_organization(self, profile):
        self.calls += 1
        raise CompanyResearchProviderError("rate_limited")


class WrongCompanyResearch(FakeCompanyResearch):
    def fetch_organization(self, profile):
        observation = super().fetch_organization(profile)
        return observation.model_copy(update={"provider_organization_id": "wrong-org"})


class ReboundContactDiscovery(FakeContactDiscovery):
    def __init__(self, *, person_id: str | None = None, title: str | None = None, email: str | None = None) -> None:
        super().__init__()
        self.person_id = person_id
        self.title = title
        self.email = email

    def enrich_person(self, provider_person_id, *, observed_at):
        person = super().enrich_person(provider_person_id, observed_at=observed_at)
        return person.model_copy(
            update={
                **({"provider_person_id": self.person_id} if self.person_id else {}),
                **({"title": self.title} if self.title else {}),
                **({"business_email": self.email} if self.email else {}),
            }
        )


class SuppressingCompanyResearch(FakeCompanyResearch):
    def __init__(self, engine, siren: str) -> None:
        super().__init__()
        self.engine = engine
        self.siren = siren

    def fetch_organization(self, profile):
        observation = super().fetch_organization(profile)
        with self.engine.begin() as connection:
            connection.execute(
                sa.update(supplier_directory)
                .where(supplier_directory.c.siren == self.siren)
                .values(suppressed_at=NOW)
            )
        return observation


class SuppressingContactDiscovery(FakeContactDiscovery):
    def __init__(self, engine, siren: str) -> None:
        super().__init__()
        self.engine = engine
        self.siren = siren

    def enrich_person(self, provider_person_id, *, observed_at):
        person = super().enrich_person(provider_person_id, observed_at=observed_at)
        if self.match_calls == 3:
            with self.engine.begin() as connection:
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == self.siren)
                    .values(suppressed_at=NOW)
                )
        return person


def _prepare_engine(engine):
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "lookup@example.test", "Client")
        target_icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=target_icp_id)
        company_key = ensure_companies_for_signal_keys(
            connection,
            signal_keys=(signal.signal_key,),
            now=NOW,
        )[signal.signal_key]
        connection.execute(
            sa.update(saas_company)
            .where(saas_company.c.company_key == company_key)
            .values(official_identifiers=[{"scheme": "SIREN", "value": "331364729"}])
        )
        connection.execute(
            sa.insert(supplier_directory).values(
                siren="331364729",
                legal_name="Egli Gartenbau AG Sursee",
                legal_name_observed_at=NOW,
                family_keys=["construction"],
                families_observed_at=NOW,
                department="38",
                department_observed_at=NOW,
                city="Grenoble",
                city_observed_at=NOW,
                domain="holder.example",
                website_url="https://holder.example/",
                domain_validation_method="name_word",
                domain_observed_at=NOW,
                apollo_organization_id="apollo-org-1",
                apollo_status="resolved",
                apollo_observed_at=NOW,
                directors=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )
    identity = CompanyLookupIdentity(
        company_key=company_key,
        siren="331364729",
        name="Egli Gartenbau AG Sursee",
        city="Grenoble",
        website_url="https://holder.example/",
    )
    company = FakeCompanyResearch()
    contacts = FakeContactDiscovery()
    service = CompanyContactLookupService(
        engine,
        company_research=company,
        contact_discovery=contacts,
    )
    return engine, account_id, identity, company, contacts, service


def prepared(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'lookup.db'}")
    return _prepare_engine(engine)


@contextmanager
def _isolated_postgres_engine() -> Iterator[sa.Engine]:
    dsn = os.environ.get("KIVOU_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KIVOU_TEST_POSTGRES_DSN is required for the contact lock-order test")
    schema = f"contact_lookup_{uuid.uuid4().hex}"
    admin = create_database_engine(dsn, pool_pre_ping=True)
    engine: sa.Engine | None = None
    try:
        with admin.begin() as connection:
            connection.execute(sa.schema.CreateSchema(schema))
        engine = create_database_engine(
            dsn,
            pool_pre_ping=True,
            connect_args={
                "options": (
                    f"-c search_path={schema} "
                    "-c statement_timeout=10000 -c lock_timeout=8000"
                )
            },
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True, if_exists=True))
        admin.dispose()


def test_paid_lookup_persists_three_contacts_and_an_append_only_apollo_attempt(
    tmp_path,
) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)

    result = service.research(
        account_id=account_id,
        plan_code="essential",
        identity=identity,
        now=NOW,
    )

    assert result["state"] == "ready"
    assert result["remaining"] == 19
    assert result["organization"] == {
        "employees": 84,
        "website_url": "https://holder.example/",
    }
    assert [contact["name"] for contact in result["contacts"]] == [
        "Alice Martin",
        "Bruno Meyer",
        "Chloé Dupont",
    ]
    assert all(contact["email_status"] == "verified" for contact in result["contacts"])
    assert company.calls == 1
    assert contacts.search_calls == 1
    assert contacts.match_calls == 3
    with engine.connect() as connection:
        row = connection.execute(sa.select(company_contact_lookup)).mappings().one()
        attempt = connection.execute(
            sa.select(company_contact_lookup_attempt)
        ).mappings().one()
    assert row["directory_siren"] == "331364729"
    assert attempt["status"] == "success"
    assert attempt["organization_enrichment_requests"] == 1
    assert attempt["people_search_requests"] == 1
    assert attempt["people_match_requests"] == 3
    assert attempt["planned_credit_units"] == 4
    assert attempt["attempted_credit_units"] == 4
    assert attempt["observed_credit_units"] is None


def test_paid_lookup_accepts_a_directory_only_company_key(tmp_path) -> None:
    engine, account_id, identity, _company, _contacts, service = prepared(tmp_path)
    directory_identity = CompanyLookupIdentity(
        company_key="cmp_directory_331364729",
        siren=identity.siren,
        name=identity.name,
        city=identity.city,
        website_url=identity.website_url,
    )

    result = service.research(
        account_id=account_id,
        plan_code="essential",
        identity=directory_identity,
        now=NOW,
    )

    assert result["state"] == "ready"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(saas_company).where(
                saas_company.c.company_key == directory_identity.company_key
            )
        ) == 0
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt).where(
                company_contact_lookup_attempt.c.company_key
                == directory_identity.company_key
            )
        ) == 1


def test_fresh_lookup_is_reused_and_refreshes_only_after_ninety_days(tmp_path) -> None:
    _engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    first = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )
    cached = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW + dt.timedelta(days=89),
    )
    refreshed = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW + dt.timedelta(days=91),
    )

    assert cached["researched_at"] == first["researched_at"]
    assert refreshed["researched_at"] != first["researched_at"]
    assert company.calls == 2
    assert contacts.search_calls == 2
    assert contacts.match_calls == 6


def test_directory_apollo_rebind_invalidates_cache_before_get_and_research(tmp_path) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    first = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )
    assert first["contacts"][0]["email"] == "person-0@holder.example"

    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == identity.siren)
            .values(
                apollo_organization_id="apollo-org-2",
                apollo_observed_at=NOW + dt.timedelta(days=1),
            )
        )

    rebound_view = service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="pro",
        now=NOW + dt.timedelta(days=1),
        siren=identity.siren,
    )
    assert rebound_view["state"] == "available"
    assert "contacts" not in rebound_view

    rebound = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW + dt.timedelta(days=1),
    )

    assert rebound["state"] == "ready"
    assert company.profiles[-1].provider_organization_id == "apollo-org-2"
    assert company.calls == 2
    assert contacts.search_calls == 2
    with engine.connect() as connection:
        cache = connection.execute(sa.select(company_contact_lookup)).mappings().one()
        attempts = connection.execute(
            sa.select(company_contact_lookup_attempt).order_by(
                company_contact_lookup_attempt.c.requested_at
            )
        ).mappings().all()
    assert cache["provider_organization_id"] == "apollo-org-2"
    assert [attempt["provider_organization_id"] for attempt in attempts] == [
        "apollo-org-1",
        "apollo-org-2",
    ]


def test_discovery_is_locked_without_calling_a_provider(tmp_path) -> None:
    _engine, account_id, identity, company, contacts, service = prepared(tmp_path)

    assert service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="discovery",
        now=NOW,
        siren=identity.siren,
    ) == {
        "state": "locked",
        "remaining": 0,
        "monthly_quota": 0,
        "source": "apollo",
        "removal_path": "/contact",
    }
    with pytest.raises(ContactLookupQuotaExceeded):
        service.research(
            account_id=account_id,
            plan_code="discovery",
            identity=identity,
            now=NOW,
        )
    assert company.calls == contacts.search_calls == contacts.match_calls == 0


def test_monthly_quota_is_enforced_before_the_next_company_is_called(tmp_path, monkeypatch) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    monkeypatch.setitem(PLAN_MONTHLY_QUOTAS, "essential", 1)
    service.research(
        account_id=account_id,
        plan_code="essential",
        identity=identity,
        # The first request can capture its clock after a second request which
        # then waits behind the account/month lock. Quota counting must cover
        # the whole month, not only attempts timestamped before the waiter.
        now=NOW + dt.timedelta(seconds=1),
    )
    with engine.begin() as connection:
        original = (
            connection.execute(
                sa.select(saas_company).where(saas_company.c.company_key == identity.company_key)
            )
            .mappings()
            .one()
        )
        second_key = "cmp_second_lookup_company"
        values = dict(original)
        values.update(
            company_key=second_key,
            identity_fingerprint="b" * 64,
            official_name="Deuxième entreprise",
        )
        connection.execute(sa.insert(saas_company), values)
        connection.execute(
            sa.insert(supplier_directory).values(
                siren="350064226",
                legal_name="Deuxième entreprise",
                legal_name_observed_at=NOW,
                family_keys=["construction"],
                families_observed_at=NOW,
                department="69",
                department_observed_at=NOW,
                city="Lyon",
                city_observed_at=NOW,
                apollo_organization_id="apollo-org-2",
                apollo_status="resolved",
                apollo_observed_at=NOW,
                directors=[],
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with pytest.raises(ContactLookupQuotaExceeded):
        service.research(
            account_id=account_id,
            plan_code="essential",
            identity=CompanyLookupIdentity(
                company_key=second_key,
                siren="350064226",
                name="Deuxième entreprise",
                city="Lyon",
                website_url=None,
            ),
            now=NOW,
        )
    assert company.calls == 1
    assert contacts.search_calls == 1
    assert contacts.match_calls == 3


def test_lookup_without_a_verified_person_omits_the_contacts_field(tmp_path) -> None:
    engine, account_id, identity, company, _contacts, _service = prepared(tmp_path)
    empty = EmptyContactDiscovery()
    service = CompanyContactLookupService(
        engine,
        company_research=company,
        contact_discovery=empty,
    )

    result = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )

    assert result["state"] == "no_contact"
    assert "contacts" not in result
    assert result["organization"]["website_url"] == "https://holder.example/"
    assert empty.search_calls == 1
    assert empty.match_calls == 0


def test_provider_failure_is_persisted_with_the_cost_already_spent(tmp_path) -> None:
    engine, account_id, identity, _company, contacts, _service = prepared(tmp_path)
    failing = FailingCompanyResearch()
    service = CompanyContactLookupService(
        engine,
        company_research=failing,
        contact_discovery=contacts,
    )

    with pytest.raises(ContactLookupProviderFailure, match="rate_limited"):
        service.research(
            account_id=account_id,
            plan_code="essential",
            identity=identity,
            now=NOW,
        )

    view = service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="essential",
        now=NOW,
        siren=identity.siren,
    )
    assert view["state"] == "failed"
    with engine.connect() as connection:
        row = connection.execute(sa.select(company_contact_lookup)).mappings().one()
        attempt = connection.execute(
            sa.select(company_contact_lookup_attempt)
        ).mappings().one()
    assert row["error_code"] == "rate_limited"
    assert attempt["status"] == "failed"
    assert attempt["organization_enrichment_requests"] == 1
    assert attempt["attempted_credit_units"] == 1
    assert attempt["observed_credit_units"] is None
    assert contacts.search_calls == 0


def test_known_directory_apollo_id_uses_the_exact_organization_endpoint(tmp_path) -> None:
    engine, account_id, identity, company, _contacts, _service = prepared(tmp_path)
    empty = EmptyContactDiscovery()
    service = CompanyContactLookupService(
        engine,
        company_research=company,
        contact_discovery=empty,
    )

    service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )

    assert company.profiles[0].provider_organization_id == "apollo-org-1"
    assert company.profiles[0].endpoint_kind == "exact_organization_id"
    assert company.profiles[0].organization_name is None


def test_directory_domain_or_city_without_apollo_id_is_not_enough_for_lookup(tmp_path) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == identity.siren)
            .values(apollo_organization_id=None, apollo_status="unresolved")
        )

    with pytest.raises(ContactLookupIdentityUnavailable):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW,
        )

    assert company.calls == contacts.search_calls == contacts.match_calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
        ) == 0


def test_exact_company_response_must_match_the_directory_apollo_id(tmp_path) -> None:
    engine, account_id, identity, _company, contacts, _service = prepared(tmp_path)
    wrong = WrongCompanyResearch()
    service = CompanyContactLookupService(
        engine,
        company_research=wrong,
        contact_discovery=contacts,
    )

    with pytest.raises(ContactLookupProviderFailure, match="provider_identity_mismatch"):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW,
        )

    assert wrong.calls == 1
    assert contacts.search_calls == contacts.match_calls == 0


@pytest.mark.parametrize(
    "contacts",
    (
        ReboundContactDiscovery(person_id="different-person"),
        ReboundContactDiscovery(title="Responsable comptable"),
        ReboundContactDiscovery(email="info@holder.example"),
        ReboundContactDiscovery(email="a..b@holder.example"),
    ),
    ids=("wrong-person", "changed-role", "generic-mailbox", "invalid-email"),
)
def test_rebound_or_invalid_people_are_never_persisted(tmp_path, contacts) -> None:
    engine, account_id, identity, company, _contacts, _service = prepared(tmp_path)
    service = CompanyContactLookupService(
        engine,
        company_research=company,
        contact_discovery=contacts,
    )

    result = service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )

    assert result["state"] == "no_contact"
    assert "contacts" not in result
    with engine.connect() as connection:
        cached = connection.execute(sa.select(company_contact_lookup)).mappings().one()
    assert cached["contacts"] == []


def test_suppression_before_lookup_blocks_every_provider_call(tmp_path) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == identity.siren)
            .values(suppressed_at=NOW)
        )

    with pytest.raises(ContactLookupSuppressed):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW,
        )

    assert company.calls == contacts.search_calls == contacts.match_calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
        ) == 0


def test_suppression_after_lookup_purges_cache_and_prevents_rediscovery(tmp_path) -> None:
    engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    service.research(
        account_id=account_id,
        plan_code="pro",
        identity=identity,
        now=NOW,
    )

    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == identity.siren)
            .values(suppressed_at=NOW + dt.timedelta(days=1))
        )

    assert service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="pro",
        now=NOW + dt.timedelta(days=1),
        siren=identity.siren,
    ) is None
    with pytest.raises(ContactLookupSuppressed):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW + dt.timedelta(days=1),
        )
    assert company.calls == 1
    assert contacts.search_calls == 1
    assert contacts.match_calls == 3
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup)
        ) == 0


def test_suppression_during_provider_chain_stops_before_people_search(tmp_path) -> None:
    engine, account_id, identity, _company, contacts, _service = prepared(tmp_path)
    suppressing = SuppressingCompanyResearch(engine, identity.siren or "")
    service = CompanyContactLookupService(
        engine,
        company_research=suppressing,
        contact_discovery=contacts,
    )

    with pytest.raises(ContactLookupProviderFailure, match="lookup_superseded"):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW,
        )

    assert suppressing.calls == 1
    assert contacts.search_calls == contacts.match_calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup)
        ) == 0
        attempt = connection.execute(
            sa.select(company_contact_lookup_attempt)
        ).mappings().one()
    assert attempt["status"] == "suppressed"
    assert attempt["attempted_credit_units"] == 1


def test_suppression_during_final_person_match_returns_a_stable_provider_error(
    tmp_path,
) -> None:
    engine, account_id, identity, company, _contacts, _service = prepared(tmp_path)
    suppressing = SuppressingContactDiscovery(engine, identity.siren or "")
    service = CompanyContactLookupService(
        engine,
        company_research=company,
        contact_discovery=suppressing,
    )

    with pytest.raises(ContactLookupProviderFailure, match="lookup_superseded"):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=identity,
            now=NOW,
        )

    assert suppressing.search_calls == 1
    assert suppressing.match_calls == 3
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup)
        ) == 0
        attempt = connection.execute(
            sa.select(company_contact_lookup_attempt)
        ).mappings().one()
    assert attempt["status"] == "suppressed"


def test_expired_lease_cannot_overwrite_the_newer_attempt(tmp_path) -> None:
    engine, account_id, identity, _company, _contacts, service = prepared(tmp_path)
    first = service._reserve(
        account_id=account_id,
        identity=identity,
        quota=100,
        now=NOW,
    )
    second = service._reserve(
        account_id=account_id,
        identity=identity,
        quota=100,
        now=NOW + dt.timedelta(minutes=6),
    )

    with pytest.raises(RuntimeError, match=first.attempt_id or "missing"):
        service._finish_success(
            attempt_id=first.attempt_id or "missing",
            account_id=account_id,
            company_key=identity.company_key,
            provider_organization_id="apollo-org-1",
            now=NOW + dt.timedelta(minutes=7),
            organization={"employees": 1},
            contacts=[],
        )

    with engine.connect() as connection:
        attempts = connection.execute(
            sa.select(
                company_contact_lookup_attempt.c.attempt_id,
                company_contact_lookup_attempt.c.status,
            ).order_by(company_contact_lookup_attempt.c.requested_at)
        ).all()
        cache = connection.execute(sa.select(company_contact_lookup)).mappings().one()
    assert attempts == [(first.attempt_id, "expired"), (second.attempt_id, "running")]
    assert cache["lease_id"] == second.attempt_id
    assert cache["status"] == "running"


def test_completion_locks_attempt_before_cache_to_match_postgresql_trigger(tmp_path) -> None:
    engine, account_id, identity, _company, _contacts, service = prepared(tmp_path)
    reservation = service._reserve(
        account_id=account_id,
        identity=identity,
        quota=100,
        now=NOW,
    )
    statements: list[str] = []

    def record_update(_connection, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update company_contact_lookup"):
            statements.append(normalized)

    sa.event.listen(engine, "before_cursor_execute", record_update)
    try:
        service._finish_success(
            attempt_id=reservation.attempt_id or "missing",
            account_id=account_id,
            company_key=identity.company_key,
            provider_organization_id="apollo-org-1",
            now=NOW,
            organization={},
            contacts=[],
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_update)

    assert statements[0].startswith("update company_contact_lookup_attempt")
    assert statements[1].startswith("update company_contact_lookup set")


def test_postgresql_completion_and_directory_rebind_do_not_deadlock() -> None:
    with _isolated_postgres_engine() as postgres_engine:
        engine, account_id, identity, _company, _contacts, service = _prepare_engine(
            postgres_engine
        )
        reservation = service._reserve(
            account_id=account_id,
            identity=identity,
            quota=100,
            now=NOW,
        )
        advisory_key = 6_053_224
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    """
                    CREATE FUNCTION block_contact_cache_update() RETURNS trigger AS $$
                    BEGIN
                        PERFORM pg_advisory_xact_lock(6053224);
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    CREATE TRIGGER block_contact_cache_update
                    AFTER UPDATE ON company_contact_lookup
                    FOR EACH ROW EXECUTE FUNCTION block_contact_cache_update()
                    """
                )
            )

        control = engine.connect()
        control.execute(sa.text("SELECT pg_advisory_lock(:key)"), {"key": advisory_key})
        cache_update_started = threading.Event()
        errors: list[BaseException] = []

        def mark_cache_update(
            _connection, _cursor, statement, _parameters, _context, _many
        ) -> None:
            if " ".join(statement.lower().split()).startswith(
                "update company_contact_lookup set"
            ):
                cache_update_started.set()

        def finish() -> None:
            try:
                service._finish_success(
                    attempt_id=reservation.attempt_id or "missing",
                    account_id=account_id,
                    company_key=identity.company_key,
                    provider_organization_id="apollo-org-1",
                    now=NOW,
                    organization={},
                    contacts=[],
                )
            except BaseException as error:  # noqa: BLE001 - asserted from thread
                errors.append(error)

        def rebind() -> None:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        sa.update(supplier_directory)
                        .where(supplier_directory.c.siren == identity.siren)
                        .values(
                            apollo_organization_id="apollo-org-2",
                            apollo_observed_at=NOW + dt.timedelta(seconds=1),
                        )
                    )
            except BaseException as error:  # noqa: BLE001 - asserted from thread
                errors.append(error)

        sa.event.listen(engine, "before_cursor_execute", mark_cache_update)
        finishing = threading.Thread(target=finish, daemon=True)
        rebinding = threading.Thread(target=rebind, daemon=True)
        try:
            finishing.start()
            assert cache_update_started.wait(timeout=3)
            time.sleep(0.1)
            rebinding.start()
            time.sleep(0.2)
            control.execute(
                sa.text("SELECT pg_advisory_unlock(:key)"), {"key": advisory_key}
            )
            finishing.join(timeout=5)
            rebinding.join(timeout=5)
        finally:
            control.execute(
                sa.text("SELECT pg_advisory_unlock(:key)"), {"key": advisory_key}
            )
            control.close()
            sa.event.remove(engine, "before_cursor_execute", mark_cache_update)
            finishing.join(timeout=1)
            rebinding.join(timeout=1)

        assert not finishing.is_alive()
        assert not rebinding.is_alive()
        assert errors == []
        with engine.connect() as connection:
            assert connection.scalar(
                sa.select(sa.func.count()).select_from(company_contact_lookup)
            ) == 0
            attempt = connection.execute(
                sa.select(company_contact_lookup_attempt).where(
                    company_contact_lookup_attempt.c.attempt_id
                    == reservation.attempt_id
                )
            ).mappings().one()
        assert attempt["status"] == "no_contact"


def test_defensive_binding_purge_expires_the_orphaned_running_attempt(tmp_path) -> None:
    engine, account_id, identity, _company, _contacts, service = prepared(tmp_path)
    reservation = service._reserve(
        account_id=account_id,
        identity=identity,
        quota=100,
        now=NOW,
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(company_contact_lookup)
            .where(company_contact_lookup.c.company_key == identity.company_key)
            .values(provider_organization_id="stale-org")
        )

    result = service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="pro",
        now=NOW + dt.timedelta(seconds=1),
        siren=identity.siren,
    )

    assert result["state"] == "available"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup)
        ) == 0
        attempt = connection.execute(
            sa.select(company_contact_lookup_attempt).where(
                company_contact_lookup_attempt.c.attempt_id == reservation.attempt_id
            )
        ).mappings().one()
    assert attempt["status"] == "expired"
    assert attempt["error_code"] == "directory_identity_changed"


def test_each_failed_retry_consumes_one_monthly_attempt(tmp_path, monkeypatch) -> None:
    engine, account_id, identity, _company, contacts, _service = prepared(tmp_path)
    monkeypatch.setitem(PLAN_MONTHLY_QUOTAS, "essential", 2)
    failing = FailingCompanyResearch()
    service = CompanyContactLookupService(
        engine,
        company_research=failing,
        contact_discovery=contacts,
    )

    for minute in (0, 1):
        with pytest.raises(ContactLookupProviderFailure):
            service.research(
                account_id=account_id,
                plan_code="essential",
                identity=identity,
                now=NOW + dt.timedelta(minutes=minute),
            )
    with pytest.raises(ContactLookupQuotaExceeded):
        service.research(
            account_id=account_id,
            plan_code="essential",
            identity=identity,
            now=NOW + dt.timedelta(minutes=2),
        )

    assert failing.calls == 2
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
        ) == 2


def test_missing_company_identity_fails_before_quota_or_provider_call(tmp_path) -> None:
    _engine, account_id, identity, company, contacts, service = prepared(tmp_path)
    missing = CompanyLookupIdentity(
        company_key=identity.company_key,
        siren=None,
        name=identity.name,
        city="Lieu du marché",
        website_url=None,
    )

    with pytest.raises(ContactLookupIdentityUnavailable):
        service.research(
            account_id=account_id,
            plan_code="pro",
            identity=missing,
            now=NOW,
        )

    assert company.calls == contacts.search_calls == contacts.match_calls == 0


def test_missing_company_identity_disables_the_paid_lookup_button(tmp_path) -> None:
    _engine, account_id, identity, company, contacts, service = prepared(tmp_path)

    result = service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="pro",
        now=NOW,
        siren=None,
    )

    assert result is not None
    assert result["state"] == "identity_unavailable"
    assert result["remaining"] == 100
    assert company.calls == contacts.search_calls == contacts.match_calls == 0


def test_exhausted_paid_quota_is_not_rendered_as_available(tmp_path, monkeypatch) -> None:
    _engine, account_id, identity, _company, _contacts, service = prepared(tmp_path)
    monkeypatch.setitem(PLAN_MONTHLY_QUOTAS, "essential", 0)

    result = service.view(
        account_id=account_id,
        company_key=identity.company_key,
        plan_code="essential",
        now=NOW,
        siren=identity.siren,
    )

    assert result["state"] == "quota_exhausted"
    assert result["remaining"] == 0
    assert result["next_reset_at"] == "2026-10-01T00:00:00+00:00"
