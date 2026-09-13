from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import sqlalchemy as sa
from feed_helpers import BOAMP_AGING, make_account, make_icp, materialize_boamp, materialize_simap

from signals.accounts.schema import target_icp
from signals.companies.enrichment import MAX_ENRICHMENT_ATTEMPTS
from signals.companies.schema import winner_enrichment_job
from signals.company_research.enrichment import (
    CompanyEnrichmentDecision,
    CompanyEnrichmentInput,
    CompanyEnrichmentProviderResult,
    CompanyEnrichmentService,
    CompanyWebCollector,
)
from signals.company_research.instance_lock import exclusive_instance_lock
from signals.company_research.winner_worker import (
    main,
    run_winner_company_enrichment_batch,
    select_winner_enrichment_candidates,
)
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal, source_event
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 8, 18, 10, tzinfo=dt.UTC)
ACTIVATED_AT = dt.datetime(2026, 8, 18, 8, tzinfo=dt.UTC)


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'winner-worker.db'}")
    migrate_to_latest(engine)
    return engine


def _seed(connection, fixture: str, suffix: str):
    account_id = make_account(connection, f"winner-worker-{suffix}@kivou.eu", suffix)
    icp_id = make_icp(connection, account_id, label=f"ICP {suffix}")
    return materialize_simap(connection, fixture, target_icp_id=icp_id), icp_id


def _seed_french_job(connection, suffix: str):
    account_id = make_account(connection, f"winner-fr-{suffix}@kivou.eu", suffix)
    signal = materialize_boamp(
        connection, BOAMP_AGING, target_icp_id=make_icp(connection, account_id)
    )
    award_key = connection.scalar(
        sa.select(materialized_signal.c.materialization_award_key).where(
            materialized_signal.c.signal_key == signal.signal_key
        )
    )
    connection.execute(
        sa.update(contract_award)
        .where(contract_award.c.award_key == award_key)
        .values(award_date=dt.date(2026, 8, 13))
    )
    return signal


def _french_identity(siren: str) -> CompanyEnrichmentInput:
    return CompanyEnrichmentInput(
        siren=siren,
        legal_name="SARL ALCIS TRANSPORTS",
        city="BALMA",
        department="31",
        naf_code="49.41A",
        naf_label="Transports routiers de fret interurbains",
        employees=19,
        directors_raw=(),
    )


def test_selector_keeps_only_post_activation_recent_current_active_signals(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        eligible, _ = _seed(connection, "28066-04", "eligible")
        _, draft_icp = _seed(connection, "33885-03", "draft")
        _, stale_icp = _seed(connection, "38147-02", "stale")
        invalidated, _ = _seed(connection, "38918-02", "invalidated")
        old, _ = _seed(connection, "33112-02", "old")
        pre_activation, _ = _seed(connection, "42486-01", "pre-activation")

        connection.execute(
            sa.update(target_icp).where(target_icp.c.target_icp_id == draft_icp).values(status="draft")
        )
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == stale_icp)
            .values(matching_revision=target_icp.c.matching_revision + 1)
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == invalidated.signal_key)
            .values(invalidated_at=NOW, invalidation_reason="test")
        )
        old_award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == old.signal_key
            )
        )
        old_event_key = connection.scalar(
            sa.select(contract_award.c.event_key).where(contract_award.c.award_key == old_award_key)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == old_award_key)
            .values(award_date=dt.date(2026, 7, 18), contract_notification_date=None)
        )
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == old_event_key)
            .values(published_on=dt.date(2026, 7, 18))
        )
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == pre_activation.signal_key)
            .values(queued_at=ACTIVATED_AT - dt.timedelta(seconds=1))
        )

        selected = select_winner_enrichment_candidates(
            connection, now=NOW, activated_at=ACTIVATED_AT, limit=20
        )

    assert tuple(item.signal_key for item in selected) == (eligible.signal_key,)


def test_selector_returns_only_one_job_per_holder_in_a_batch(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        first, _ = _seed(connection, "28066-04", "first")
        second, _ = _seed(connection, "28066-04", "second")

        selected = select_winner_enrichment_candidates(
            connection, now=NOW, activated_at=ACTIVATED_AT, limit=20
        )

    assert len(selected) == 1
    assert selected[0].signal_key in {first.signal_key, second.signal_key}
    assert selected[0].holder_key


def test_selector_retries_only_failed_jobs_below_the_attempt_limit(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        retryable, _ = _seed(connection, "28066-04", "retryable")
        exhausted, _ = _seed(connection, "33885-03", "exhausted")
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == retryable.signal_key)
            .values(
                status="failed",
                attempt_count=MAX_ENRICHMENT_ATTEMPTS - 1,
                error_code="test_failure",
                claimed_by="test-worker",
                started_at=NOW - dt.timedelta(minutes=1),
                finished_at=NOW,
            )
        )
        connection.execute(
            sa.update(winner_enrichment_job)
            .where(winner_enrichment_job.c.signal_key == exhausted.signal_key)
            .values(
                status="failed",
                attempt_count=MAX_ENRICHMENT_ATTEMPTS,
                error_code="test_failure",
                claimed_by="test-worker",
                started_at=NOW - dt.timedelta(minutes=1),
                finished_at=NOW,
            )
        )

        selected = select_winner_enrichment_candidates(
            connection, now=NOW, activated_at=ACTIVATED_AT, limit=20
        )

    assert tuple(item.signal_key for item in selected) == (retryable.signal_key,)


def test_worker_enriches_a_new_winner_and_duplicate_signal_uses_cache(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        first_account = make_account(connection, "winner-first@kivou.eu", "First")
        second_account = make_account(connection, "winner-second@kivou.eu", "Second")
        first = materialize_boamp(
            connection, BOAMP_AGING, target_icp_id=make_icp(connection, first_account)
        )
        second = materialize_boamp(
            connection, BOAMP_AGING, target_icp_id=make_icp(connection, second_account)
        )
        award_keys = tuple(
            connection.scalars(
                sa.select(materialized_signal.c.materialization_award_key).where(
                    materialized_signal.c.signal_key.in_((first.signal_key, second.signal_key))
                )
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key.in_(award_keys))
            .values(award_date=dt.date(2026, 8, 13))
        )

    directory = SupplierDirectoryStore(engine, clock=lambda: NOW)

    class Collector:
        calls = 0

        def collect(self, identity):
            self.calls += 1
            return CompanyWebCollector.evidence_for_test(
                identity, domain="alcis.fr", contact_text="SARL ALCIS TRANSPORTS"
            )

    class Provider:
        calls = 0

        def enrich(self, identity, evidence):
            self.calls += 1
            return CompanyEnrichmentProviderResult(
                decision=CompanyEnrichmentDecision(
                    website="alcis.fr",
                    website_confidence=Decimal("0.95"),
                    email=None,
                    email_confidence=Decimal("0.90"),
                    email_is_placeholder=False,
                    family=None,
                    family_confidence=Decimal("0.90"),
                    director_display_name=None,
                    phone=None,
                    requested_page_url=None,
                    notes="site confirmé",
                ),
                model="test/judge",
                cost_usd=Decimal("0.001"),
                input_tokens=700,
                output_tokens=80,
            )

    collector = Collector()
    provider = Provider()
    service = CompanyEnrichmentService(
        directory=directory,
        collector=collector,
        provider=provider,
        mx_verifier=lambda _email: True,
        clock=lambda: NOW,
    )

    def identity_source(siren: str) -> CompanyEnrichmentInput:
        assert siren == "479673980"
        return CompanyEnrichmentInput(
            siren=siren,
            legal_name="SARL ALCIS TRANSPORTS",
            city="BALMA",
            department="31",
            naf_code="49.41A",
            naf_label="Transports routiers de fret interurbains",
            employees=19,
            directors_raw=(),
        )

    first_batch = run_winner_company_enrichment_batch(
        engine,
        now=NOW,
        activated_at=ACTIVATED_AT,
        worker_ref="winner-model-test",
        identity_source=identity_source,
        enrichment_service=service,
        limit=10,
    )
    second_batch = run_winner_company_enrichment_batch(
        engine,
        now=NOW + dt.timedelta(hours=1),
        activated_at=ACTIVATED_AT,
        worker_ref="winner-model-test",
        identity_source=identity_source,
        enrichment_service=service,
        limit=10,
    )

    record = directory.get("479673980")
    with engine.connect() as connection:
        statuses = tuple(
            connection.scalars(
                sa.select(winner_enrichment_job.c.status).where(
                    winner_enrichment_job.c.signal_key.in_((first.signal_key, second.signal_key))
                )
            )
        )

    assert first_batch.completed == 1
    assert second_batch.completed == 1
    assert provider.calls == collector.calls == 1
    assert record is not None
    assert record.enrichment_model_id == "test/judge"
    assert set(statuses) <= {"completed", "partial"}


def test_worker_records_an_unresolved_directory_identity_as_a_failed_job(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        signal = _seed_french_job(connection, "unresolved")

    class Service:
        def enrich(self, *_args, **_kwargs):
            raise AssertionError("the model must not run without a directory identity")

    batch = run_winner_company_enrichment_batch(
        engine,
        now=NOW,
        activated_at=ACTIVATED_AT,
        worker_ref="winner-unresolved-test",
        identity_source=lambda _siren: None,
        enrichment_service=Service(),
        limit=10,
    )

    with engine.connect() as connection:
        row = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()
    assert batch.failed == 1
    assert row.status == "failed"
    assert row.error_code == "winner_directory_identity_unresolved"


def test_worker_contains_an_identity_provider_failure_to_one_job(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        signal = _seed_french_job(connection, "identity-error")

    class Service:
        def enrich(self, *_args, **_kwargs):
            raise AssertionError("the model must not run after an identity failure")

    def broken_identity_source(_siren: str):
        raise RuntimeError("registry unavailable")

    batch = run_winner_company_enrichment_batch(
        engine,
        now=NOW,
        activated_at=ACTIVATED_AT,
        worker_ref="winner-identity-error-test",
        identity_source=broken_identity_source,
        enrichment_service=Service(),
        limit=10,
    )

    with engine.connect() as connection:
        row = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()
    assert batch.failed == 1
    assert row.status == "failed"
    assert row.error_code == "winner_directory_identity_failed"


def test_cli_refuses_a_second_instance_before_provider_validation(
    tmp_path, monkeypatch, capsys
) -> None:
    lock_path = tmp_path / "winner.lock"
    monkeypatch.setenv("KIVOU_WINNER_ENRICHMENT_ACTIVATED_AT", NOW.isoformat())
    monkeypatch.setenv("KIVOU_WINNER_ENRICHMENT_LOCK_FILE", str(lock_path))
    monkeypatch.delenv("KIVOU_SERPER_API_KEY", raising=False)

    with exclusive_instance_lock(lock_path):
        result = main([])

    assert result == os.EX_TEMPFAIL
    assert "INSTANCE_ALREADY_RUNNING" in capsys.readouterr().err


def test_budget_stop_returns_the_job_to_pending_without_spending_an_attempt(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as connection:
        signal = _seed_french_job(connection, "budget")

    class Service:
        def enrich(self, *_args, **_kwargs):
            raise DailyModelBudgetExhausted(
                usage="enrichment_judge",
                cap_usd=Decimal("2"),
                actual_usd=Decimal("1.99"),
                reserved_usd=Decimal("0"),
                requested_usd=Decimal("0.02"),
            )

    batch = run_winner_company_enrichment_batch(
        engine,
        now=NOW,
        activated_at=ACTIVATED_AT,
        worker_ref="winner-budget-test",
        identity_source=_french_identity,
        enrichment_service=Service(),
        limit=10,
    )

    with engine.connect() as connection:
        row = connection.execute(
            sa.select(winner_enrichment_job).where(
                winner_enrichment_job.c.signal_key == signal.signal_key
            )
        ).one()
    assert batch.budget_usage == "enrichment_judge"
    assert row.status == "pending"
    assert row.attempt_count == 0
    assert row.claimed_by is None
