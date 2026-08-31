from __future__ import annotations

import datetime as dt
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from feed_helpers import (
    RETRIEVED_AT,
    SIMAP_RICH,
    make_account,
    make_icp,
    materialize,
    materialize_simap,
    simap_award,
)

from signals.accounts.schema import target_icp
from signals.billing import discovery
from signals.billing.access import feed_access
from signals.billing.schema import billing_subscription
from signals.companies import service as company_service
from signals.companies import store as company_store
from signals.companies.contracts import CompanyOfficialIdentity
from signals.companies.identity import IdentityMethod, ResolvedOfficialCompany
from signals.companies.indexing import index_signal_company_identity
from signals.companies.service import (
    company_profile_for_account,
    ensure_company_for_unlocked_signal,
)
from signals.companies.store import CompanyCandidate, get_or_create_companies
from signals.feed import query
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal

AS_OF = dt.date(2026, 8, 25)
NOW = dt.datetime(2026, 8, 25, 9, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'service.db'}")
    migrate_to_latest(value)
    return value


@contextmanager
def _isolated_postgres_engine() -> Iterator[sa.Engine]:
    dsn = os.environ.get("KIVOU_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip(
            "KIVOU_TEST_POSTGRES_DSN is required for PostgreSQL interleaving tests"
        )

    schema = f"company_batch_{uuid.uuid4().hex}"
    admin_engine = create_database_engine(dsn, pool_pre_ping=True)
    postgres_engine: sa.Engine | None = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(schema))
        postgres_engine = create_database_engine(
            dsn,
            pool_pre_ping=True,
            connect_args={
                "options": (
                    f"-c search_path={schema} "
                    "-c statement_timeout=10000 -c lock_timeout=8000"
                )
            },
        )
        migrate_to_latest(postgres_engine)
        yield postgres_engine
    finally:
        if postgres_engine is not None:
            postgres_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True, if_exists=True))
        admin_engine.dispose()


def _paid_account(connection, *, email: str):
    account_id = make_account(connection, email, email.split("@")[0])
    icp_id = make_icp(connection, account_id)
    subscribe(
        connection,
        account_id=account_id,
        plan="scale",
        subscription_id=f"sub_{account_id}",
        now=RETRIEVED_AT,
    )
    return account_id, icp_id


def _item(connection, *, account_id: str, signal_key: str, icp_id: str):
    item = query.owned_signal(
        connection,
        account_id=account_id,
        signal_key=signal_key,
        as_of=AS_OF,
        allowed_target_icp_ids=frozenset({icp_id}),
    )
    assert item is not None
    return item


def _company_key(connection, *, account_id: str, icp_id: str, signal_key: str) -> str:
    item = _item(connection, account_id=account_id, signal_key=signal_key, icp_id=icp_id)
    access = feed_access(connection, account_id=account_id, as_of=AS_OF)
    assert access.is_unlocked(item)
    key = ensure_company_for_unlocked_signal(connection, item=item, now=NOW)
    assert key is not None
    return key


def _identity_variant(
    connection,
    *,
    fixture: str,
    target_icp_id: str,
    name: str,
    address: str | None,
    identifiers: tuple | None = None,
    website: str | None = None,
):
    event, awards = simap_award(fixture)
    _, templates = simap_award(SIMAP_RICH)
    template_party = templates[0].awardee_parties[0]
    template_member = template_party.members[0]
    template_organization = template_member.organization
    assert template_organization is not None
    organization = template_organization.model_copy(
        update={
            "legal_name": name,
            "address": address,
            "identifiers": (
                template_organization.identifiers if identifiers is None else identifiers
            ),
            "website": website,
        }
    )
    member = template_member.model_copy(update={"organization": organization})
    party = template_party.model_copy(update={"members": (member,)})
    award = awards[0].model_copy(update={"awardee_parties": (party,)})
    return materialize(connection, event, award, target_icp_id=target_icp_id)


def test_feed_company_resolution_uses_one_store_batch(engine, monkeypatch) -> None:
    with engine.begin() as connection:
        account_id, icp_id = _paid_account(connection, email="batch-service@kivou.test")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        item = _item(
            connection,
            account_id=account_id,
            signal_key=signal.signal_key,
            icp_id=icp_id,
        )

        def forbid_single_store_call(*args, **kwargs):
            raise AssertionError("feed company resolution must use the batch store")

        monkeypatch.setattr(
            company_service,
            "get_or_create_company",
            forbid_single_store_call,
        )
        resolved = company_service.ensure_companies_for_unlocked_signals(
            connection,
            items=(item,),
            now=NOW,
        )

    assert resolved[signal.signal_key].startswith("cmp_")


def test_company_store_batch_has_constant_statement_count(engine, monkeypatch) -> None:
    statements: list[str] = []
    candidate_order: list[str] = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        if "saas_company" in statement:
            statements.append(statement)

    original_candidate_values = company_store._candidate_values

    def record_candidate_values(candidate, *, now):
        candidate_order.append(candidate.resolved.identity_fingerprint)
        return original_candidate_values(candidate, now=now)

    monkeypatch.setattr(company_store, "_candidate_values", record_candidate_values)

    with engine.begin() as connection:
        _, icp_id = _paid_account(connection, email="batch-store@kivou.test")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        indexed = index_signal_company_identity(
            connection,
            signal_key=signal.signal_key,
        )
        assert indexed is not None
        candidates = tuple(
            CompanyCandidate(
                resolved=ResolvedOfficialCompany(
                    official=CompanyOfficialIdentity(
                        name=f"Entreprise batch {index}",
                        country="CH",
                        observed_at=NOW,
                    ),
                    identity_fingerprint=f"{index + 1:064x}",
                    identity_method=IdentityMethod.OPPORTUNITY,
                    validation_evidence={"opportunity_key": f"opp_batch_{index}"},
                ),
                source_award_key=indexed.source_award_key,
                origin_signal_key=signal.signal_key,
            )
            for index in reversed(range(5))
        )
        sa.event.listen(connection, "before_cursor_execute", record_statement)
        first = get_or_create_companies(connection, candidates=candidates, now=NOW)
        assert len(first) == len(candidates)
        assert len(statements) == 2
        assert candidate_order == sorted(candidate_order)

        statements.clear()
        candidate_order.clear()
        second = get_or_create_companies(connection, candidates=candidates, now=NOW)
        assert second.keys() == first.keys()
        assert len(statements) == 2
        assert candidate_order == sorted(candidate_order)


def test_postgresql_opposed_company_batches_do_not_deadlock() -> None:
    with _isolated_postgres_engine() as postgres_engine:
        with postgres_engine.begin() as connection:
            _, icp_id = _paid_account(connection, email="batch-postgres@kivou.test")
            signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
            indexed = index_signal_company_identity(
                connection,
                signal_key=signal.signal_key,
            )
            assert indexed is not None
            connection.execute(
                sa.text(
                    """
                    CREATE FUNCTION slow_company_batch_insert() RETURNS trigger AS $$
                    BEGIN
                        PERFORM pg_sleep(0.5);
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
            )
            connection.execute(
                sa.text(
                    """
                    CREATE TRIGGER slow_company_batch_insert
                    AFTER INSERT ON saas_company
                    FOR EACH ROW EXECUTE FUNCTION slow_company_batch_insert()
                    """
                )
            )

        def candidate(fingerprint: str) -> CompanyCandidate:
            return CompanyCandidate(
                resolved=ResolvedOfficialCompany(
                    official=CompanyOfficialIdentity(
                        name=f"Entreprise concurrente {fingerprint[-1]}",
                        country="CH",
                        observed_at=NOW,
                    ),
                    identity_fingerprint=fingerprint,
                    identity_method=IdentityMethod.OPPORTUNITY,
                    validation_evidence={"opportunity_key": f"opp_{fingerprint[-1]}"},
                ),
                source_award_key=indexed.source_award_key,
                origin_signal_key=signal.signal_key,
            )

        low = candidate("1" * 64)
        high = candidate("2" * 64)
        start = threading.Barrier(3)
        results: list[dict[str, object]] = []
        errors: list[BaseException] = []

        def run(candidates: tuple[CompanyCandidate, ...]) -> None:
            try:
                with postgres_engine.begin() as connection:
                    start.wait(timeout=3)
                    results.append(
                        get_or_create_companies(
                            connection,
                            candidates=candidates,
                            now=NOW,
                        )
                    )
            except BaseException as error:  # noqa: BLE001 - asserted from the thread
                errors.append(error)

        first = threading.Thread(target=run, args=((low, high),), daemon=True)
        second = threading.Thread(target=run, args=((high, low),), daemon=True)
        try:
            first.start()
            second.start()
            start.wait(timeout=3)
            first.join(timeout=15)
            second.join(timeout=15)

            assert not first.is_alive()
            assert not second.is_alive()
            assert errors == []
            assert len(results) == 2
            assert all(set(result) == {"1" * 64, "2" * 64} for result in results)
            with postgres_engine.connect() as connection:
                count = connection.scalar(
                    sa.select(sa.func.count()).select_from(company_store.saas_company)
                )
            assert count == 2
        finally:
            first.join(timeout=1)
            second.join(timeout=1)


def test_current_unlocked_signal_authorizes_official_profile(engine) -> None:
    with engine.begin() as connection:
        account_id, icp_id = _paid_account(connection, email="alice-service@kivou.test")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        key = _company_key(
            connection, account_id=account_id, icp_id=icp_id, signal_key=signal.signal_key
        )
        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )

    assert profile is not None
    assert profile.official_identity.name == "Egli Gartenbau AG Sursee"
    assert profile.official_identity.source == "public_notice"
    assert [signal.signal_id for signal in profile.related_signals] == [signal.signal_key]
    assert profile.related_signals[0].plausible_needs
    assert profile.related_signals[0].fit.label


def test_company_is_invisible_to_another_account_without_a_matching_signal(engine) -> None:
    with engine.begin() as connection:
        account_a, icp_a = _paid_account(connection, email="a-service@kivou.test")
        account_b, icp_b = _paid_account(connection, email="b-service@kivou.test")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_a)
        key = _company_key(
            connection, account_id=account_a, icp_id=icp_a, signal_key=signal.signal_key
        )

        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_b,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_b}),
            access=feed_access(connection, account_id=account_b, as_of=AS_OF),
            lang="fr",
        )

    assert profile is None


def test_same_exact_official_identity_can_authorize_two_accounts(engine) -> None:
    with engine.begin() as connection:
        account_a, icp_a = _paid_account(connection, email="shared-a@kivou.test")
        account_b, icp_b = _paid_account(connection, email="shared-b@kivou.test")
        first = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_a)
        second = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_b)
        key = _company_key(
            connection, account_id=account_a, icp_id=icp_a, signal_key=first.signal_key
        )

        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_b,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_b}),
            access=feed_access(connection, account_id=account_b, as_of=AS_OF),
            lang="en",
        )

    assert profile is not None
    assert [item.signal_id for item in profile.related_signals] == [second.signal_key]
    assert "a-service" not in profile.model_dump_json()


def test_official_fields_come_only_from_this_accounts_accessible_notice(engine) -> None:
    with engine.begin() as connection:
        account_a, icp_a = _paid_account(connection, email="facts-a@kivou.test")
        account_b, icp_b = _paid_account(connection, email="facts-b@kivou.test")
        first = _identity_variant(
            connection,
            fixture=SIMAP_RICH,
            target_icp_id=icp_a,
            name="Entreprise Partagee SA",
            address="Adresse visible uniquement dans avis A",
            website="https://partagee.example/a",
        )
        second = _identity_variant(
            connection,
            fixture="33885-03",
            target_icp_id=icp_b,
            name="Entreprise Partagee SA",
            address=None,
            website=None,
        )
        key = _company_key(
            connection, account_id=account_a, icp_id=icp_a, signal_key=first.signal_key
        )

        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_b,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_b}),
            access=feed_access(connection, account_id=account_b, as_of=AS_OF),
            lang="fr",
        )

    assert profile is not None
    assert [item.signal_id for item in profile.related_signals] == [second.signal_key]
    assert profile.official_identity.address is None
    assert profile.official_identity.website_url is None
    assert "Adresse visible uniquement" not in profile.model_dump_json()


def test_domain_identity_survives_an_official_name_change(engine) -> None:
    with engine.begin() as connection:
        account_a, icp_a = _paid_account(connection, email="domain-a@kivou.test")
        account_b, icp_b = _paid_account(connection, email="domain-b@kivou.test")
        first = _identity_variant(
            connection,
            fixture=SIMAP_RICH,
            target_icp_id=icp_a,
            name="Ancienne raison sociale SA",
            address=None,
            identifiers=(),
            website="https://identite-domaine.example/a",
        )
        second = _identity_variant(
            connection,
            fixture="33885-03",
            target_icp_id=icp_b,
            name="Nouvelle raison sociale SA",
            address=None,
            identifiers=(),
            website="https://identite-domaine.example/b",
        )
        key = _company_key(
            connection, account_id=account_a, icp_id=icp_a, signal_key=first.signal_key
        )

        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_b,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_b}),
            access=feed_access(connection, account_id=account_b, as_of=AS_OF),
            lang="fr",
        )

    assert profile is not None
    assert profile.official_identity.name == "Nouvelle raison sociale SA"
    assert [item.signal_id for item in profile.related_signals] == [second.signal_key]


def test_locked_matches_cannot_hide_an_older_permanent_discovery_grant(
    engine, monkeypatch
) -> None:
    monkeypatch.setattr(company_service, "MAX_RELATED_SIGNALS", 1)
    with engine.begin() as connection:
        account_id = make_account(connection, "bounded-grant@kivou.test", "Bounded Grant")
        icp_id = make_icp(connection, account_id)
        granted_signal = _identity_variant(
            connection,
            fixture=SIMAP_RICH,
            target_icp_id=icp_id,
            name="Entreprise Borne SA",
            address=None,
        )
        locked_signal = _identity_variant(
            connection,
            fixture="33885-03",
            target_icp_id=icp_id,
            name="Entreprise Borne SA",
            address=None,
        )
        granted_item = _item(
            connection,
            account_id=account_id,
            signal_key=granted_signal.signal_key,
            icp_id=icp_id,
        )
        discovery.grant_up_to_limit(
            connection, account_id=account_id, candidates=[granted_item], now=NOW
        )
        key = ensure_company_for_unlocked_signal(connection, item=granted_item, now=NOW)
        assert key is not None

        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )

    assert locked_signal.signal_key != granted_signal.signal_key
    assert profile is not None
    assert [item.signal_id for item in profile.related_signals] == [granted_signal.signal_key]


def test_locked_only_invalidated_and_old_revision_signals_do_not_authorize(engine) -> None:
    with engine.begin() as connection:
        account_id = make_account(connection, "locked-service@kivou.test", "Locked")
        icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        item = _item(
            connection, account_id=account_id, signal_key=signal.signal_key, icp_id=icp_id
        )
        # Creation is deliberately done through a temporary paid access, then the
        # read is exercised under Discovery without a grant.
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id=f"sub_{account_id}",
            now=RETRIEVED_AT,
        )
        key = ensure_company_for_unlocked_signal(connection, item=item, now=NOW)
        assert key is not None
        connection.execute(
            sa.update(billing_subscription)
            .where(billing_subscription.c.account_id == account_id)
            .values(status="canceled", current_period_end=RETRIEVED_AT)
        )

        locked = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal.signal_key)
            .values(invalidated_at=NOW, invalidation_reason="test")
        )
        invalidated = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal.signal_key)
            .values(invalidated_at=None, invalidation_reason=None)
        )
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == icp_id)
            .values(matching_revision=target_icp.c.matching_revision + 1)
        )
        old_revision = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )

    assert locked is None
    assert invalidated is None
    assert old_revision is None


def test_permanent_discovery_grant_remains_authoritative(engine) -> None:
    with engine.begin() as connection:
        account_id = make_account(connection, "grant-service@kivou.test", "Grant")
        icp_id = make_icp(connection, account_id)
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        item = _item(
            connection, account_id=account_id, signal_key=signal.signal_key, icp_id=icp_id
        )
        discovery.grant_up_to_limit(
            connection, account_id=account_id, candidates=[item], now=NOW
        )
        key = ensure_company_for_unlocked_signal(connection, item=item, now=NOW)
        assert key is not None

        later = dt.date(2027, 8, 25)
        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=later,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=later),
            lang="fr",
        )

    assert profile is not None
    assert profile.related_signals[0].signal_id == signal.signal_key


def test_related_signal_order_reuses_the_server_sort_order(engine) -> None:
    with engine.begin() as connection:
        account_id, icp_id = _paid_account(connection, email="order-service@kivou.test")
        first = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        # Same exact public organization under a second account-scoped signal is
        # not manufactured here; the singleton still proves equality with feed order.
        key = _company_key(
            connection, account_id=account_id, icp_id=icp_id, signal_key=first.signal_key
        )
        expected = query.feed_page(
            connection,
            account_id=account_id,
            as_of=AS_OF,
            freshness="all",
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=100,
        )
        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )

    assert profile is not None
    assert [item.signal_id for item in profile.related_signals] == [
        item.signal.signal_key for item in expected.items
    ]


def test_profile_hydrates_only_indexed_company_matches_among_many_account_signals(
    engine, monkeypatch
) -> None:
    with engine.begin() as connection:
        account_id, icp_id = _paid_account(connection, email="bounded-scan@kivou.test")
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        key = _company_key(
            connection,
            account_id=account_id,
            icp_id=icp_id,
            signal_key=signal.signal_key,
        )
        template = dict(
            connection.execute(
                sa.select(materialized_signal).where(
                    materialized_signal.c.signal_key == signal.signal_key
                )
            ).mappings().one()
        )
        noise = []
        for index in range(600):
            row = dict(template)
            row["signal_key"] = f"sig_unrelated_{index:04d}"
            row["opportunity_key"] = f"opp_unrelated_{index:04d}"
            if "company_identity_fingerprint" in row:
                row["company_identity_fingerprint"] = None
            noise.append(row)
        connection.execute(sa.insert(materialized_signal), noise)

        hydrated: list[str] = []
        original = company_service.signal_from_row

        def counting_signal_from_row(row):
            hydrated.append(row.signal_key)
            return original(row)

        monkeypatch.setattr(company_service, "signal_from_row", counting_signal_from_row)
        profile = company_profile_for_account(
            connection,
            company_key=key,
            account_id=account_id,
            as_of=AS_OF,
            allowed_target_icp_ids=frozenset({icp_id}),
            access=feed_access(connection, account_id=account_id, as_of=AS_OF),
            lang="fr",
        )

    assert profile is not None
    assert hydrated == [signal.signal_key]
