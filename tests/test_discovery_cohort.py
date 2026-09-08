"""Token Discovery: one fixed bait-inclusive cohort, never a landing bonus."""

import datetime as dt

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    Clock,
    account_of,
    icp_of,
    make_app,
    make_engine,
    pay,
    seed,
    signed_up,
)

from signals.accounts import service as accounts
from signals.accounts.schema import account_landing_signal
from signals.billing import discovery
from signals.billing.access import feed_access
from signals.billing.schema import discovery_signal_grant
from signals.persistence.schema import contract_award, materialized_signal, source_event


def prepared(tmp_path, *, count=5):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = signed_up(app)
    target = icp_of(client)
    keys = seed(engine, target, count=count)
    return engine, app, client, account_of(client), keys


def promise(connection, account_id, key, *, qa=False):
    opportunity = connection.scalar(sa.select(materialized_signal.c.opportunity_key).where(
        materialized_signal.c.signal_key == key,
    ))
    return accounts.record_landing_signal(
        connection, account_id=account_id, opportunity_key=opportunity,
        signal_key=key, qa=qa, now=NOW,
    )


def event_for(connection, key):
    return connection.scalar(sa.select(contract_award.c.event_key).join(
        materialized_signal,
        materialized_signal.c.materialization_award_key == contract_award.c.award_key,
    ).where(materialized_signal.c.signal_key == key))


def grant_keys(engine, account_id):
    with engine.connect() as connection:
        return discovery.granted_signal_keys(connection, account_id=account_id)


def test_landing_transaction_immediately_allocates_bait_plus_two_and_updates_both_counters(tmp_path):
    engine, _, client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        promise(connection, account_id, keys[0])
        grants = discovery.grants(connection, account_id=account_id)
        assert len(grants) == 3
        assert keys[0] in {grant.signal_key for grant in grants}
        assert discovery.remaining_slots(connection, account_id=account_id) == 0
        assert feed_access(connection, account_id=account_id, as_of=NOW.date()).granted == {
            grant.signal_key for grant in grants
        }
    # The first dashboard must agree without a prior /signals request.
    assert client.get("/dashboard").json()["plan"]["opened"] == 3
    assert client.get("/billing/status").json()["discovery"]["granted_signal_count"] == 3


def test_multiple_lots_of_the_bait_procedure_do_not_consume_other_places(tmp_path):
    engine, _, _, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        for key in keys[:3]:
            connection.execute(sa.update(source_event).where(
                source_event.c.event_key == event_for(connection, key),
            ).values(source_procedure_id="same-public-procedure"))
        promise(connection, account_id, keys[0])
    assert grant_keys(engine, account_id) == frozenset((keys[0], keys[3], keys[4]))


def test_later_better_fit_cannot_displace_grants_and_open_rows_precede_locked_pagination(tmp_path):
    engine, _, client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        for key, score in zip(keys, (10, 20, 30, 90, 80), strict=True):
            connection.execute(sa.update(materialized_signal).where(
                materialized_signal.c.signal_key == key,
            ).values(icp_match_normalized_score=score))
        promise(connection, account_id, keys[0])
    original = grant_keys(engine, account_id)
    assert original == frozenset((keys[0], keys[3], keys[4]))
    with engine.begin() as connection:
        connection.execute(sa.update(materialized_signal).where(
            materialized_signal.c.signal_key == keys[1],
        ).values(icp_match_normalized_score=100))
        promise(connection, account_id, keys[0])
    first = client.get("/signals", params={"limit": 3}).json()["items"]
    following = client.get("/signals", params={"limit": 3, "offset": 3}).json()["items"]
    assert {item["signal_id"] for item in first} == original
    assert all(not item["locked"] for item in first)
    assert following[0]["signal_id"] == keys[1]
    assert all(item["locked"] for item in following)
    assert grant_keys(engine, account_id) == original


def test_full_non_qa_legacy_grants_are_preserved_and_bait_conflict_is_explicit(tmp_path):
    engine, _, client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        for key in keys[1:4]:
            opportunity = connection.scalar(sa.select(materialized_signal.c.opportunity_key)
                                            .where(materialized_signal.c.signal_key == key))
            connection.execute(sa.insert(discovery_signal_grant).values(
                account_id=account_id, signal_key=key, opportunity_key=opportunity,
                granted_at=NOW - dt.timedelta(days=1), created_at=NOW - dt.timedelta(days=1),
            ))
        before = discovery.grants(connection, account_id=account_id)
        promise(connection, account_id, keys[0])
        assert discovery.grants(connection, account_id=account_id) == before
        audit = discovery.cohort_audit(connection, account_id=account_id, now=NOW)
        assert audit["legacy_bait_conflict"] is True
        assert keys[0] not in feed_access(connection, account_id=account_id, as_of=NOW.date()).granted
    assert client.get("/signals").status_code == 200
    assert client.get("/dashboard").status_code == 200
    with engine.connect() as connection:
        assert discovery.grants(connection, account_id=account_id) == before


def test_paid_landing_history_exception_still_opens_the_promised_signal(tmp_path):
    engine, _, client, account_id, keys = prepared(tmp_path)
    pay(engine, client, plan="essential")
    with engine.begin() as connection:
        promise(connection, account_id, keys[0])
        access = feed_access(connection, account_id=account_id, as_of=(NOW + dt.timedelta(days=90)).date())
        assert keys[0] in access.granted
        assert discovery.grants(connection, account_id=account_id) == ()


def test_identifier_only_holder_and_empty_object_are_excluded_without_inventing_three(tmp_path):
    engine, _, _, account_id, keys = prepared(tmp_path, count=3)
    with engine.begin() as connection:
        award_key = connection.scalar(sa.select(materialized_signal.c.materialization_award_key)
                                      .where(materialized_signal.c.signal_key == keys[1]))
        parties = connection.scalar(sa.select(contract_award.c.awardee_parties)
                                    .where(contract_award.c.award_key == award_key))
        for party in parties:
            for member in party["members"]:
                member["organization"]["legal_name"] = "30689637400320"
        connection.execute(sa.update(contract_award).where(contract_award.c.award_key == award_key)
                           .values(awardee_parties=parties))
        blank_key = connection.scalar(sa.select(materialized_signal.c.materialization_award_key)
                                      .where(materialized_signal.c.signal_key == keys[2]))
        connection.execute(sa.update(contract_award).where(contract_award.c.award_key == blank_key)
                           .values(title="  "))
        promise(connection, account_id, keys[0])
    assert grant_keys(engine, account_id) == frozenset((keys[0],))


def test_qa_reconciliation_is_readonly_by_default_and_rejects_unmarked_accounts(tmp_path):
    from signals.qa.discovery_grants import reconcile_discovery_grants

    engine, _, _, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        promise(connection, account_id, keys[0], qa=True)
    before = grant_keys(engine, account_id)
    report = reconcile_discovery_grants(engine, account_id=account_id, now=NOW, dry_run=True)
    assert report["dry_run"] is True
    assert grant_keys(engine, account_id) == before
    with engine.begin() as connection:
        connection.execute(sa.update(account_landing_signal).where(
            account_landing_signal.c.account_id == account_id,
        ).values(qa=False))
    with pytest.raises(ValueError, match="QA"):
        reconcile_discovery_grants(engine, account_id=account_id, now=NOW, dry_run=False)
    assert grant_keys(engine, account_id) == before
def test_lifetime_allocation_does_not_reset_next_month(tmp_path):
    engine, _app, _client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        promise(connection, account_id, keys[0])
        before = discovery.grants(connection, account_id=account_id)
        discovery.fill_token_cohort(
            connection, account_id=account_id, now=NOW + dt.timedelta(days=40)
        )
        assert discovery.grants(connection, account_id=account_id) == before
        assert len(before) == 3


def test_global_procedure_uuid_deduplicates_across_sources(tmp_path):
    engine, _app, _client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        for key, source in zip(keys[:3], ("boamp", "ted", "simap"), strict=True):
            connection.execute(sa.update(source_event).where(
                source_event.c.event_key == event_for(connection, key)
            ).values(source_system=source, source_procedure_id="c382e651-045b-49a2-be21-58be5c7a0a66"))
        promise(connection, account_id, keys[0])
        assert discovery.granted_signal_keys(connection, account_id=account_id) == frozenset(
            (keys[0], keys[3], keys[4])
        )


def test_one_procedure_has_one_full_card_across_dashboard_feed_and_detail(tmp_path):
    engine, _app, client, account_id, keys = prepared(tmp_path)
    with engine.begin() as connection:
        for key in keys:
            connection.execute(sa.update(source_event).where(
                source_event.c.event_key == event_for(connection, key)
            ).values(source_procedure_id="one-local-procedure"))
        promise(connection, account_id, keys[0])
    dashboard = client.get("/dashboard").json()
    assert dashboard["plan"]["opened"] == 1
    assert {item["signal_id"] for item in dashboard["top3"]} == {keys[0]}
    feed = client.get("/signals").json()["items"]
    assert {item["signal_id"] for item in feed if not item["locked"]} == {keys[0]}
    for key in keys:
        detail = client.get(f"/signals/{key}")
        assert detail.status_code == 200
        assert detail.json()["locked"] is (key != keys[0])
@pytest.fixture(autouse=True)
def explicit_matching_proof_for_cohort_fixtures(monkeypatch):
    """These allocation fixtures represent already matched, named signals.

    The shared seed helper deliberately stores insufficient_data. Override only
    this module's seed, never the qualification gate or shared legacy fixtures.
    """
    original = seed

    def matched_seed(engine, *args, **kwargs):
        keys = original(engine, *args, **kwargs)
        with engine.begin() as connection:
            connection.execute(sa.update(materialized_signal).where(
                materialized_signal.c.signal_key.in_(keys)
            ).values(icp_match_decision="show", icp_match_band="promising",
                     icp_match_normalized_score=50))
        return keys

    monkeypatch.setitem(globals(), "seed", matched_seed)


def test_valid_missing_title_keeps_existing_cpv_object_fallback(tmp_path):
    engine, _app, _client, _account_id, keys = prepared(tmp_path, count=2)
    with engine.begin() as connection:
        row = connection.execute(sa.select(
            materialized_signal.c.materialization_award_key,
            materialized_signal.c.opportunity_key,
        ).where(materialized_signal.c.signal_key == keys[1])).one()
        connection.execute(sa.update(contract_award).where(
            contract_award.c.award_key == row.materialization_award_key
        ).values(title=None, lot_title=None, cpv_main="45000000", cpv_check_digit=None))
        facts = discovery.opportunity_facts(connection, (row.opportunity_key,), as_of=NOW.date())
        assert facts[row.opportunity_key]["eligible"]
        assert facts[row.opportunity_key]["refusal_codes"] == set()


def test_malformed_representation_is_precisely_rejected_without_hiding_named_alternative(tmp_path):
    from signals.persistence.schema import opportunity_representation

    engine, _app, _client, _account_id, keys = prepared(tmp_path, count=2)
    with engine.begin() as connection:
        rows = [connection.execute(sa.select(
            materialized_signal.c.materialization_award_key,
            materialized_signal.c.opportunity_key,
        ).where(materialized_signal.c.signal_key == key)).one() for key in keys]
        connection.execute(sa.update(contract_award).where(
            contract_award.c.award_key == rows[0].materialization_award_key
        ).values(title="  "))
        facts = discovery.opportunity_facts(connection, (rows[0].opportunity_key,), as_of=NOW.date())
        assert facts[rows[0].opportunity_key]["refusal_codes"] == {"SIGNAL_OBJECT_UNRESOLVED"}
        assert not facts[rows[0].opportunity_key]["eligible"]
        connection.execute(sa.update(opportunity_representation).where(
            opportunity_representation.c.award_key == rows[1].materialization_award_key
        ).values(opportunity_key=rows[0].opportunity_key))
        facts = discovery.opportunity_facts(connection, (rows[0].opportunity_key,), as_of=NOW.date())
        assert len(facts[rows[0].opportunity_key]["eligible"]) == 1
        assert facts[rows[0].opportunity_key]["refusal_codes"] == set()
