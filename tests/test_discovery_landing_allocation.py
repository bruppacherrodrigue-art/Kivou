"""Real matching, bounded landing scan, scoped QA apply and PostgreSQL locking."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import threading

import pytest
import sqlalchemy as sa
from engagement_helpers import NOW, make_engine
from feed_helpers import make_account
from test_ingestion_backfill import _active_target, _persist_matching_awards
from test_saas_company_service import _isolated_postgres_engine

from signals.accounts import service as accounts
from signals.accounts.schema import account_landing_signal
from signals.billing import discovery
from signals.billing.schema import discovery_signal_grant
from signals.ingestion.backfill import (
    landing_cohort_plan,
    materialize_landing_feed_in_transaction,
)
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.qa.discovery_grants import reconcile_discovery_grants


def source_fixture(engine, *, count=63):
    """Bait + sixty recent lots of its procedure, then two older procedures."""
    _persist_matching_awards(engine, count=count)
    with engine.begin() as connection:
        account_id = make_account(connection, 'cohort-qa@example.test', 'Cohort QA')
        target = _active_target(connection, account_id).target_icp_id
        rows = connection.execute(sa.select(
            source_event.c.event_key, source_event.c.source_notice_id,
            opportunity_representation.c.opportunity_key,
        ).select_from(source_event.join(
            contract_award, contract_award.c.event_key == source_event.c.event_key
        ).join(opportunity_representation,
               opportunity_representation.c.award_key == contract_award.c.award_key))).all()
        opportunities = {}
        for row in rows:
            index = int(row.source_notice_id.removeprefix('backfill-notice-'))
            opportunities[index] = row.opportunity_key
            connection.execute(sa.update(source_event).where(
                source_event.c.event_key == row.event_key
            ).values(
                source_procedure_id=('c382e651-045b-49a2-be21-58be5c7a0a66'
                                     if index < count - 2 else f'older-procedure-{index}'),
                published_at_raw=NOW.date().isoformat(), published_precision='date',
                published_on=NOW.date(),
            ))
            connection.execute(sa.update(contract_award).where(
                contract_award.c.event_key == row.event_key
            ).values(award_date=NOW.date() - dt.timedelta(days=3 if index < count - 2 else 8)))
    return account_id, target, opportunities


def test_landing_scan_reaches_older_distinct_procedures_past_sixty_recent_lots(tmp_path):
    engine = make_engine(tmp_path)
    account_id, target, opportunities = source_fixture(engine)
    with engine.begin() as connection:
        plan = landing_cohort_plan(connection, target_icp_id=target,
                                  opportunity_key=opportunities[0], as_of=NOW.date(),
                                  materialized_at=NOW)
        assert set(plan['grant_opportunities']) == {
            opportunities[0], opportunities[61], opportunities[62],
        }
        assert len(plan['candidates']) == 40
        assert plan['scan_truncated'] is True
        assert len(plan['prepared']) <= 5
        assert any(row['refusal_codes'] == ['SAME_PROCEDURE'] for row in plan['candidates'])
        bait = materialize_landing_feed_in_transaction(
            connection, target_icp_id=target, opportunity_key=opportunities[0],
            as_of=NOW.date(), materialized_at=NOW,
        )
        accounts.record_landing_signal(connection, account_id=account_id,
                                       opportunity_key=opportunities[0], signal_key=bait,
                                       qa=True, now=NOW)
        grants = discovery.grants(connection, account_id=account_id)
        assert {row.opportunity_key for row in grants} == set(plan['grant_opportunities'])
        assert connection.scalar(sa.select(sa.func.count()).select_from(materialized_signal)
                                 .where(materialized_signal.c.target_icp_id == target)) <= 5


def test_qa_dry_run_has_no_dml_and_apply_replaces_only_reviewed_marked_account(tmp_path):
    engine = make_engine(tmp_path)
    account_id, target, opportunities = source_fixture(engine, count=5)
    with engine.begin() as connection:
        bait = materialize_landing_feed_in_transaction(
            connection, target_icp_id=target, opportunity_key=opportunities[0],
            as_of=NOW.date(), materialized_at=NOW,
        )
        accounts.record_landing_signal(connection, account_id=account_id,
                                       opportunity_key=opportunities[0], signal_key=bait,
                                       qa=True, now=NOW)
        other = make_account(connection, 'untouched@example.test', 'Untouched')
        connection.execute(sa.delete(discovery_signal_grant).where(
            discovery_signal_grant.c.account_id == account_id))
        for owner, key in ((account_id, bait), (account_id, 'legacy-qa-extra'),
                           (other, 'legacy-other')):
            connection.execute(sa.insert(discovery_signal_grant).values(
                account_id=owner, signal_key=key, opportunity_key=opportunities[0],
                granted_at=NOW - dt.timedelta(days=1), created_at=NOW - dt.timedelta(days=1)))
        other_before = discovery.grants(connection, account_id=other)
        before = discovery.grants(connection, account_id=account_id)

    def prohibit_dml(_connection, _cursor, statement, _parameters, _context, _many):
        assert statement.lstrip().split(None, 1)[0].upper() not in {'INSERT', 'UPDATE', 'DELETE'}

    sa.event.listen(engine, 'before_cursor_execute', prohibit_dml)
    try:
        preview = reconcile_discovery_grants(engine, account_id=account_id, now=NOW)
    finally:
        sa.event.remove(engine, 'before_cursor_execute', prohibit_dml)
    assert preview['dry_run'] is True
    assert preview['before'] == preview['after']
    assert preview['bait_preserved'] is True
    assert len(preview['proposed_grants']) == 3
    assert all(row['procedure_references'] for row in preview['proposed_grants'])
    assert all(row['procedure_references'] for row in preview['candidates'])
    with engine.connect() as connection:
        assert discovery.grants(connection, account_id=account_id) == before
    with pytest.raises(ValueError, match='audit_token'):
        reconcile_discovery_grants(engine, account_id=account_id, now=NOW, dry_run=False)
    applied = reconcile_discovery_grants(engine, account_id=account_id, now=NOW,
                                         dry_run=False, expected_audit=preview['audit_token'])
    assert applied['after']['used'] == 3
    assert applied['after']['remaining'] == 0
    assert {row['signal_key'] for row in applied['after']['grants']} == {
        row['signal_key'] for row in preview['proposed_grants']}
    with engine.connect() as connection:
        assert discovery.grants(connection, account_id=other) == other_before
    with pytest.raises(ValueError, match='audit_token'):
        reconcile_discovery_grants(engine, account_id=account_id, now=NOW,
                                   dry_run=False, expected_audit=preview['audit_token'])
    with engine.begin() as connection:
        connection.execute(sa.update(account_landing_signal).where(
            account_landing_signal.c.account_id == account_id).values(qa=False))
    with pytest.raises(ValueError, match='QA'):
        reconcile_discovery_grants(engine, account_id=account_id, now=NOW,
                                   dry_run=False, expected_audit=applied['audit_token'])


@pytest.mark.parametrize('entry_point', ['fill', 'landing_replay'])
def test_postgres_allocation_waits_for_own_account_and_keeps_lifetime_cap(entry_point):
    with _isolated_postgres_engine() as engine:
        account_id, target, opportunities = source_fixture(engine, count=5)
        with engine.begin() as connection:
            bait = materialize_landing_feed_in_transaction(
                connection, target_icp_id=target, opportunity_key=opportunities[0],
                as_of=NOW.date(), materialized_at=NOW)
            connection.execute(sa.insert(account_landing_signal).values(
                account_id=account_id, opportunity_key=opportunities[0], signal_key=bait,
                qa=True, created_at=NOW))
        started = threading.Event()

        def contender():
            with engine.begin() as connection:
                started.set()
                if entry_point == 'fill':
                    discovery.fill_token_cohort(connection, account_id=account_id, now=NOW)
                else:
                    accounts.record_landing_signal(
                        connection, account_id=account_id, opportunity_key=opportunities[0],
                        signal_key=bait, qa=True, now=NOW)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with engine.begin() as owner:
                discovery.lock_account(owner, account_id=account_id)
                pending = pool.submit(contender)
                assert started.wait(5)
                with pytest.raises(concurrent.futures.TimeoutError):
                    pending.result(timeout=0.2)
                discovery.fill_token_cohort(owner, account_id=account_id, now=NOW)
                first = discovery.grants(owner, account_id=account_id)
                assert len(first) == 3
            pending.result(timeout=8)
        with engine.connect() as connection:
            assert discovery.grants(connection, account_id=account_id) == first


def test_postgres_allocation_does_not_wait_for_another_accounts_lock():
    with _isolated_postgres_engine() as engine:
        account_id, target, opportunities = source_fixture(engine, count=5)
        with engine.begin() as connection:
            other = make_account(connection, 'other-lock@example.test', 'Other Lock')
            bait = materialize_landing_feed_in_transaction(
                connection, target_icp_id=target, opportunity_key=opportunities[0],
                as_of=NOW.date(), materialized_at=NOW)
            connection.execute(sa.insert(account_landing_signal).values(
                account_id=account_id, opportunity_key=opportunities[0], signal_key=bait,
                qa=True, created_at=NOW))

        def fill():
            with engine.begin() as connection:
                discovery.fill_token_cohort(connection, account_id=account_id, now=NOW)
                return discovery.grants(connection, account_id=account_id)

        with (
            concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
            engine.begin() as connection,
        ):
            discovery.lock_account(connection, account_id=other)
            result = pool.submit(fill).result(timeout=5)
            assert len(result) == 3
            assert discovery.grants(connection, account_id=other) == ()


def test_account_lock_compiles_to_scoped_postgres_for_update():
    from sqlalchemy.dialects import postgresql

    class Connection:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return self

        def scalar_one(self):
            return 'only-this-account'

    connection = Connection()
    discovery.lock_account(connection, account_id='only-this-account')
    compiled = connection.statement.compile(dialect=postgresql.dialect())
    assert 'FOR UPDATE' in str(compiled)
    assert 'WHERE account.account_id =' in str(compiled)
    assert list(compiled.params.values()) == ['only-this-account']
