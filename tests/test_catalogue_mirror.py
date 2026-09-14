"""Idempotent, recoverable and strictly staging-only public catalogue import."""

import datetime as dt
import importlib

import pytest
import sqlalchemy as sa
from test_catalogue_publication import NOW, publication, seed
from test_saas_company_api import _insert_directory_company
from test_saas_company_api import engine as engine  # noqa: PLC0414

from signals.accounts.schema import account
from signals.companies.schema import company_contact_lookup
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import supplier_directory


def mirror():
    try:
        return importlib.import_module("signals.supplier_directory.catalogue_mirror")
    except ModuleNotFoundError:
        pytest.fail("the transactional staging catalogue mirror is not implemented")


def snapshot(engine, *, at=NOW):
    with engine.connect() as connection:
        return publication().build_snapshot(connection, now=at)


def apply(engine, payload, *, environment="STAGING", at=NOW):
    with engine.begin() as connection:
        return mirror().apply_snapshot(
            connection, payload, destination_environment=environment, now=at
        )


def row(engine, siren="481153435"):
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
            )
            .mappings()
            .one()
        )


def test_import_and_replay_keep_one_identity_and_private_columns(engine):
    seed(engine)
    payload = snapshot(engine)
    apply(engine, payload)
    again = apply(engine, payload)
    assert again["inserted"] == 0
    assert row(engine)["enrichment_notes"] == "PRIVATE_MODEL_TRACE"
    assert row(engine)["apollo_organization_id"] == "LICENSED_PROVIDER_ID"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(supplier_directory)) == 1


def test_new_snapshot_updates_and_withdraws_only_source_owned_companies(engine):
    seed(engine)
    original = snapshot(engine)
    apply(engine, original)
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="562136036", name="Locale uniquement")
        connection.execute(
            supplier_directory.update()
            .where(supplier_directory.c.siren == "481153435")
            .values(legal_name="Nom corrigé", updated_at=NOW + dt.timedelta(minutes=1))
        )
    updated = snapshot(engine, at=NOW + dt.timedelta(minutes=2))
    # The local-only row is deliberately not part of the source publication.
    payload = publication().make_snapshot(
        tuple(value for value in updated.rows if value["siren"] == "481153435"),
        now=NOW + dt.timedelta(minutes=2),
    )
    apply(engine, payload, at=NOW + dt.timedelta(minutes=2))
    assert row(engine)["legal_name"] == "Nom corrigé"
    withdrawn = publication().make_snapshot((), now=NOW + dt.timedelta(minutes=3))
    result = apply(engine, withdrawn, at=NOW + dt.timedelta(minutes=3))
    assert result["withdrawn"] == 1
    assert row(engine)["suppressed_at"] is not None
    assert row(engine, "562136036")["suppressed_at"] is None


def test_local_suppression_is_never_undone_by_source_reappearance(engine):
    seed(engine)
    payload = snapshot(engine)
    apply(engine, payload)
    with engine.begin() as connection:
        connection.execute(
            supplier_directory.update().values(suppressed_at=NOW + dt.timedelta(seconds=10))
        )
    later = publication().make_snapshot(payload.rows, now=NOW + dt.timedelta(minutes=1))
    apply(engine, later, at=NOW + dt.timedelta(minutes=1))
    assert row(engine)["suppressed_at"] is not None


def test_stale_snapshot_and_production_destination_are_rejected(engine):
    seed(engine)
    payload = snapshot(engine)
    with pytest.raises(ValueError, match="staging"):
        apply(engine, payload, environment="PRODUCTION")
    apply(engine, payload)
    stale = publication().make_snapshot(payload.rows, now=NOW - dt.timedelta(minutes=1))
    with pytest.raises(ValueError, match="stale"):
        apply(engine, stale)
    assert row(engine)["legal_name"] == "Entreprise réelle"


def test_empty_destination_inserts_source_and_preserves_newer_local_contact(engine):
    seed(engine)
    source = snapshot(engine)
    target = create_database_engine("sqlite+pysqlite:///:memory:")
    migrate_to_latest(target)
    try:
        inserted = apply(target, source)
        assert inserted["inserted"] == 1
        assert row(target)["enrichment_notes"] is None
        assert row(target)["apollo_organization_id"] is None
        with target.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    website_url="https://nouveau-site.fr/",
                    domain="nouveau-site.fr",
                    domain_observed_at=NOW + dt.timedelta(minutes=2),
                    updated_at=NOW + dt.timedelta(minutes=2),
                )
            )
        with engine.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    city="Nice",
                    city_observed_at=NOW + dt.timedelta(minutes=3),
                    updated_at=NOW + dt.timedelta(minutes=3),
                )
            )
        apply(
            target,
            snapshot(engine, at=NOW + dt.timedelta(minutes=4)),
            at=NOW + dt.timedelta(minutes=4),
        )
        observed = row(target)
        assert observed["city"] == "Nice"
        assert observed["website_url"] == "https://nouveau-site.fr/"
        # A retained domain cannot acquire an unrelated old-domain email.
        assert observed["professional_email"] is None
    finally:
        target.dispose()


def test_reappearance_cannot_undo_a_concurrent_independent_suppression(engine):
    seed(engine)
    source = snapshot(engine)
    apply(engine, source)
    apply(
        engine,
        publication().make_snapshot((), now=NOW + dt.timedelta(minutes=1)),
        at=NOW + dt.timedelta(minutes=1),
    )
    independent_at = NOW + dt.timedelta(minutes=2)
    injected = False

    def suppress_before_reappearance(connection, cursor, statement, parameters, context, many):
        nonlocal injected
        if not injected and statement.startswith("UPDATE supplier_directory SET"):
            injected = True
            connection.execute(supplier_directory.update().values(suppressed_at=independent_at))

    sa.event.listen(engine, "before_cursor_execute", suppress_before_reappearance)
    try:
        apply(
            engine,
            publication().make_snapshot(source.rows, now=NOW + dt.timedelta(minutes=3)),
            at=NOW + dt.timedelta(minutes=3),
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", suppress_before_reappearance)
    assert injected
    assert row(engine)["suppressed_at"] == independent_at.replace(tzinfo=None)


def test_source_owned_withdrawal_can_reappear_without_losing_identity(engine):
    seed(engine)
    source = snapshot(engine)
    apply(engine, source)
    apply(
        engine,
        publication().make_snapshot((), now=NOW + dt.timedelta(minutes=1)),
        at=NOW + dt.timedelta(minutes=1),
    )
    apply(
        engine,
        publication().make_snapshot(source.rows, now=NOW + dt.timedelta(minutes=2)),
        at=NOW + dt.timedelta(minutes=2),
    )
    assert row(engine)["suppressed_at"] is None
    assert row(engine)["enrichment_notes"] == "PRIVATE_MODEL_TRACE"


@pytest.mark.parametrize("revoke_domain", [False, True])
@pytest.mark.parametrize("newer_local", [False, True])
def test_source_fact_withdrawal_propagates_but_preserves_newer_local_facts(
    engine, revoke_domain, newer_local
):
    seed(engine)
    target = create_database_engine("sqlite+pysqlite:///:memory:")
    migrate_to_latest(target)
    try:
        apply(target, snapshot(engine))
        if newer_local:
            with target.begin() as connection:
                connection.execute(
                    supplier_directory.update().values(
                        professional_email="nouveau@entreprise.fr",
                        email_observed_at=NOW + dt.timedelta(minutes=3),
                        domain_observed_at=NOW + dt.timedelta(minutes=3),
                        updated_at=NOW + dt.timedelta(minutes=3),
                    )
                )
        with engine.begin() as connection:
            removal = {
                "professional_email": None,
                "email_source": None,
                "email_evidence_url": None,
                "email_observed_at": None,
                "updated_at": NOW + dt.timedelta(minutes=2),
            }
            if revoke_domain:
                removal.update(domain=None, website_url=None, domain_observed_at=None)
            connection.execute(supplier_directory.update().values(**removal))
        apply(
            target,
            snapshot(engine, at=NOW + dt.timedelta(minutes=4)),
            at=NOW + dt.timedelta(minutes=4),
        )
        observed = row(target)
        assert observed["professional_email"] == ("nouveau@entreprise.fr" if newer_local else None)
        assert bool(observed["website_url"]) is (not revoke_domain or newer_local)
    finally:
        target.dispose()


def test_source_missing_fact_never_erases_a_locally_owned_contact(engine):
    seed(engine)
    target = create_database_engine("sqlite+pysqlite:///:memory:")
    migrate_to_latest(target)
    try:
        seed(target)
        with engine.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    professional_email=None,
                    email_source=None,
                    email_evidence_url=None,
                    email_observed_at=None,
                    updated_at=NOW + dt.timedelta(minutes=1),
                )
            )
        apply(
            target,
            snapshot(engine, at=NOW + dt.timedelta(minutes=1)),
            at=NOW + dt.timedelta(minutes=1),
        )
        with engine.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    city="Nice",
                    updated_at=NOW + dt.timedelta(minutes=2),
                )
            )
        apply(
            target,
            snapshot(engine, at=NOW + dt.timedelta(minutes=2)),
            at=NOW + dt.timedelta(minutes=2),
        )
        assert row(target)["professional_email"] == "bonjour@entreprise.fr"
    finally:
        target.dispose()


@pytest.mark.parametrize(
    "website,kept",
    [("https://nouvelle-entreprise.fr/", False), ("https://www.entreprise.fr/", True)],
)
def test_source_website_identity_correction_invalidates_only_mismatched_local_lookup(
    engine, website, kept
):
    seed(engine)
    target = create_database_engine("sqlite+pysqlite:///:memory:")
    migrate_to_latest(target)
    try:
        apply(target, snapshot(engine))
        with target.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    apollo_organization_id="local-org", apollo_status="resolved"
                )
            )
            connection.execute(
                account.insert().values(
                    account_id="mirror-owner",
                    display_name="Owner",
                    locale="fr",
                    onboarding_status="account_created",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                company_contact_lookup.insert().values(
                    lookup_id="local-lookup",
                    account_id="mirror-owner",
                    company_key="cmp_directory_481153435",
                    directory_siren="481153435",
                    provider_organization_id="local-org",
                    status="ready",
                    contacts=[{"email": "private-licensed@entreprise.fr"}],
                    requested_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        with engine.begin() as connection:
            connection.execute(
                supplier_directory.update().values(
                    website_url=website,
                    domain=website.removeprefix("https://").rstrip("/"),
                    domain_observed_at=NOW + dt.timedelta(minutes=1),
                    updated_at=NOW + dt.timedelta(minutes=1),
                    apollo_organization_id="source-org-never-copied",
                )
            )
        apply(
            target,
            snapshot(engine, at=NOW + dt.timedelta(minutes=2)),
            at=NOW + dt.timedelta(minutes=2),
        )
        assert row(target)["apollo_organization_id"] == ("local-org" if kept else None)
        with target.connect() as connection:
            assert connection.scalar(
                sa.select(sa.func.count()).select_from(company_contact_lookup)
            ) == int(kept)
            assert connection.scalar(sa.select(sa.func.count()).select_from(account)) == 1
    finally:
        target.dispose()
