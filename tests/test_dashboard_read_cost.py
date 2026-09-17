from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from engagement_helpers import (
    NOW,
    Clock,
    account_of,
    icp_of,
    make_app,
    pay,
    seed,
    signed_up,
)

from signals.billing.schema import billing_subscription
from signals.companies.schema import saas_company
from signals.dashboard import service
from signals.engagement.schema import company_contact, signal_feedback, signal_workflow
from signals.feed import policy, query
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import materialized_signal


@pytest.fixture
def historical_account(request):
    engine = create_database_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=sa.pool.StaticPool,
        connect_args={"check_same_thread": False},
    )
    migrate_to_latest(engine)
    client = signed_up(make_app(engine, Clock()))
    pay(engine, client, plan="essential")
    profile = icp_of(client)
    account = account_of(client)
    keys = seed(engine, profile, count=12)
    count = getattr(request, "param", 12)
    with engine.begin() as connection:
        rows = [dict(row) for row in connection.execute(sa.select(materialized_signal)).mappings()]
        if count > len(rows):
            connection.execute(
                materialized_signal.insert(),
                [
                    {
                        **rows[index % len(rows)],
                        "signal_key": f"read-cost-signal-{index:06}",
                        "opportunity_key": f"read-cost-opportunity-{index:06}",
                    }
                    for index in range(count - len(rows))
                ],
            )
    # Warm the same read model, including company projection, before measuring it.
    assert client.get("/dashboard", params={"target_icp_id": profile}).status_code == 200
    old = NOW - dt.timedelta(days=16)
    with engine.begin() as connection:
        companies = connection.scalars(
            sa.select(saas_company.c.company_key).order_by(saas_company.c.company_key).limit(3)
        ).all()
        assert len(companies) == 3
        connection.execute(
            company_contact.insert(),
            [
                {
                    "account_id": account,
                    "company_key": key,
                    "status": "contacted" if index == 0 else "replied",
                    "contacted_at": old,
                    "created_at": old,
                    "updated_at": old,
                }
                for index, key in enumerate(companies)
            ],
        )
        connection.execute(
            signal_feedback.insert(),
            [
                {
                    "account_id": account,
                    "signal_key": key,
                    "relevance": "relevant",
                    "created_at": old,
                    "updated_at": old,
                    "contacted_at": old if index % 2 else None,
                }
                for index, key in enumerate(keys[:6])
            ],
        )
    try:
        yield client, engine, account, profile, keys, companies
    finally:
        client.close()
        engine.dispose()


def _read(client, profile):
    response = client.get("/dashboard", params={"target_icp_id": profile})
    assert response.status_code == 200, response.text
    return response.json()


def _record_feed_calls(monkeypatch):
    calls = []
    original = query.feed_page

    def record(*args, **kwargs):
        calls.append((kwargs.get("freshness"), kwargs.get("published_since")))
        return original(*args, **kwargs)

    monkeypatch.setattr(query, "feed_page", record)
    return calls


def _read_complete_path(monkeypatch, client, profile):
    # Keep the pre-optimization path as an oracle for every payload field,
    # including truncation and the due follow-up, not just the three zeroes.
    with monkeypatch.context() as patch:
        if hasattr(service, "_week_activity_may_exist"):
            patch.setattr(service, "_week_activity_may_exist", lambda *args, **kwargs: True)
        return _read(client, profile)


@pytest.mark.parametrize("historical_account", [12, 500, 501, 1148], indirect=True)
def test_historical_activity_does_not_rescan_all_signals_for_zero_week_counts(
    historical_account, monkeypatch
):
    client, _, _, profile, *_ = historical_account
    expected = _read_complete_path(monkeypatch, client, profile)
    assert len(expected["to_follow_up"]) == 1
    assert {key: expected["week"][key] for key in ("saved", "contacted", "replied")} == {
        "saved": 0,
        "contacted": 0,
        "replied": 0,
    }
    calls = _record_feed_calls(monkeypatch)
    assert _read(client, profile) == expected
    assert calls == [("new", None), ("all", NOW.date() - dt.timedelta(days=7))]


@pytest.mark.parametrize("activity", ["feedback_saved", "contacted", "workflow_saved", "replied"])
@pytest.mark.parametrize("age_days", [0, 7])
def test_current_week_activity_keeps_the_authorized_scope_scan(
    historical_account, monkeypatch, activity, age_days
):
    client, engine, account, profile, keys, companies = historical_account
    activity_at = NOW - dt.timedelta(days=age_days)
    with engine.begin() as connection:
        if activity == "workflow_saved":
            connection.execute(
                signal_workflow.insert().values(
                    account_id=account,
                    signal_key=keys[-1],
                    status="saved",
                    revision=1,
                    created_at=activity_at,
                    updated_at=activity_at,
                )
            )
        elif activity == "replied":
            connection.execute(
                company_contact.update()
                .where(company_contact.c.company_key == companies[-1])
                .values(updated_at=activity_at)
            )
        else:
            connection.execute(
                signal_feedback.update()
                .where(signal_feedback.c.signal_key == keys[0])
                .values(
                    **(
                        {"contacted_at": activity_at}
                        if activity == "contacted"
                        else {"updated_at": activity_at}
                    )
                )
            )
    expected = _read_complete_path(monkeypatch, client, profile)
    metric = {
        "feedback_saved": "saved",
        "workflow_saved": "saved",
        "contacted": "contacted",
        "replied": "replied",
    }[activity]
    assert expected["week"][metric] == 1
    calls = _record_feed_calls(monkeypatch)
    assert _read(client, profile) == expected
    assert calls[-1] == ("all", None)
    assert len(calls) == 3


def test_discovery_keeps_independent_activity_truncation(historical_account, monkeypatch):
    client, engine, account, profile, *_ = historical_account
    with engine.begin() as connection:
        connection.execute(
            billing_subscription.update()
            .where(billing_subscription.c.account_id == account)
            .values(status="canceled")
        )
    expected = _read_complete_path(monkeypatch, client, profile)
    assert expected["top3"] == []
    assert expected["to_follow_up"] == []
    calls = _record_feed_calls(monkeypatch)
    assert _read(client, profile) == expected
    assert calls == [
        ("new", None),
        ("all", None),
        ("all", NOW.date() - dt.timedelta(days=7)),
        ("all", None),
    ]


def test_other_accounts_activity_does_not_trigger_an_empty_scope_scan(
    historical_account, monkeypatch
):
    client, engine, _, profile, _, companies = historical_account
    other = signed_up(client.app, email="other-read-cost@example.com")
    try:
        other_account = account_of(other)
        other_key = seed(engine, icp_of(other))[0]
        with engine.begin() as connection:
            connection.execute(
                signal_workflow.insert().values(
                    account_id=other_account,
                    signal_key=other_key,
                    status="saved",
                    revision=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                signal_feedback.insert().values(
                    account_id=other_account,
                    signal_key=other_key,
                    relevance="relevant",
                    contacted_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                company_contact.insert().values(
                    account_id=other_account,
                    company_key=companies[-1],
                    status="replied",
                    contacted_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        expected = _read_complete_path(monkeypatch, client, profile)
        calls = _record_feed_calls(monkeypatch)
        assert _read(client, profile) == expected
        assert len(calls) == 2
    finally:
        other.close()


def test_future_activity_does_not_count_as_current_week(historical_account, monkeypatch):
    client, engine, account, profile, keys, _ = historical_account
    future = NOW + dt.timedelta(microseconds=1)
    with engine.begin() as connection:
        connection.execute(
            signal_workflow.insert().values(
                account_id=account,
                signal_key=keys[-1],
                status="saved",
                revision=1,
                created_at=future,
                updated_at=future,
            )
        )
        connection.execute(
            signal_feedback.update()
            .where(signal_feedback.c.account_id == account)
            .values(updated_at=future, contacted_at=future)
        )
        connection.execute(
            company_contact.update()
            .where(company_contact.c.account_id == account, company_contact.c.status == "replied")
            .values(updated_at=future)
        )
    expected = _read_complete_path(monkeypatch, client, profile)
    calls = _record_feed_calls(monkeypatch)
    assert _read(client, profile) == expected
    assert len(calls) == 2


def test_smaller_feed_cap_keeps_independent_activity_truncation(historical_account, monkeypatch):
    client, _, _, profile, *_ = historical_account
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)
    expected = _read_complete_path(monkeypatch, client, profile)
    calls = _record_feed_calls(monkeypatch)
    assert _read(client, profile) == expected
    assert calls[-1] == ("all", None)
    assert len(calls) == 3
