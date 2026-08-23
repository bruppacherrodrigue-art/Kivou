from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from feed_helpers import RETRIEVED_AT, SIMAP_RICH, make_account, make_icp, materialize_simap

from signals.companies.identity import official_company_identity
from signals.companies.schema import saas_company
from signals.companies.store import get_company_by_key, get_or_create_company
from signals.feed.query import DisplayIdentity
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.repository import get_signal
from signals.persistence.schema import contract_award


@pytest.fixture
def prepared(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'store.db'}")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        account_id = make_account(connection, "company-store@kivou.test", "Kivou Store")
        icp_id = make_icp(connection, account_id)
        result = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp_id)
        signal = get_signal(connection, result.signal_key)
        assert signal is not None
        parties = connection.scalar(
            sa.select(contract_award.c.awardee_parties).where(
                contract_award.c.award_key == signal.materialization_award_key
            )
        )
    display = DisplayIdentity(
        name=signal.winner_name or "Egli Gartenbau AG Sursee",
        country=signal.winner_country,
        identifier_scheme=signal.winner_identifier_scheme,
        identifier_value=signal.winner_identifier_value,
        from_award_key=signal.materialization_award_key,
    )
    resolved = official_company_identity(
        awardee_parties=parties,
        display=display,
        opportunity_key=signal.opportunity_key,
        observed_at=RETRIEVED_AT,
    )
    assert resolved is not None
    return engine, signal, resolved


def test_exact_identity_creation_is_idempotent(prepared) -> None:
    engine, signal, resolved = prepared
    with engine.begin() as connection:
        first = get_or_create_company(
            connection,
            resolved=resolved,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT,
        )
        second = get_or_create_company(
            connection,
            resolved=resolved,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT + dt.timedelta(days=1),
        )

        assert first == second
        assert connection.scalar(sa.select(sa.func.count()).select_from(saas_company)) == 1


def test_source_facts_are_not_overwritten_by_a_later_resolution(prepared) -> None:
    engine, signal, resolved = prepared
    with engine.begin() as connection:
        stored = get_or_create_company(
            connection,
            resolved=resolved,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT,
        )
        changed = resolved.__class__(
            official=resolved.official.model_copy(update={"address": "Changed later"}),
            identity_fingerprint=resolved.identity_fingerprint,
            identity_method=resolved.identity_method,
            validation_evidence=resolved.validation_evidence,
        )
        same = get_or_create_company(
            connection,
            resolved=changed,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT + dt.timedelta(days=1),
        )

    assert same.company_key == stored.company_key
    assert same.official_identity.address == stored.official_identity.address
    assert same.official_identity.address != "Changed later"


def test_store_contains_only_normalized_official_projection(prepared) -> None:
    engine, signal, resolved = prepared
    with engine.begin() as connection:
        stored = get_or_create_company(
            connection,
            resolved=resolved,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT,
        )
        row = connection.execute(
            sa.select(saas_company).where(saas_company.c.company_key == stored.company_key)
        ).mappings().one()

    assert row["identity_validation"] == resolved.validation_evidence
    assert row["official_identifiers"] == [
        identifier.model_dump(mode="json") for identifier in resolved.official.identifiers
    ]
    serialized = repr(dict(row)).lower()
    for forbidden in ("raw_payload", "procedure_buyers", "description", "apollo", "contact"):
        assert forbidden not in serialized


def test_company_lookup_uses_only_the_opaque_key(prepared) -> None:
    engine, signal, resolved = prepared
    with engine.begin() as connection:
        stored = get_or_create_company(
            connection,
            resolved=resolved,
            source_award_key=signal.materialization_award_key,
            origin_signal_key=signal.signal_key,
            now=RETRIEVED_AT,
        )

        assert get_company_by_key(connection, company_key=stored.company_key) == stored
        assert get_company_by_key(connection, company_key="cmp_0000000000000000") is None
