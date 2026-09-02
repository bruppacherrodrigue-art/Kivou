"""Phase 1 — historique exhaustif, tri factuel et curseur fermé."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    make_account,
    make_icp,
    materialize,
    pin_session_cookie,
    simap_award,
)

from signals.accounts.schema import target_icp
from signals.api import ApiConfig, create_app
from signals.domain.values import Location
from signals.feed.history import (
    HistoryCursor,
    InvalidHistoryCursor,
    decode_history_cursor,
    encode_history_cursor,
)
from signals.feed.query import history_page
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, materialized_signal

READ_ON = dt.date(2026, 8, 25)
NAMES = ("29997-02", "33112-02", "33885-03", "34794-02", "38918-02")


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def account(engine) -> tuple[str, str]:
    with engine.begin() as connection:
        account_id = make_account(connection, "history-owner@kivou.test", "History Owner")
        return account_id, make_icp(connection, account_id, "Historique")


def _seed(engine, icp_id: str, *, count: int = 5) -> list[str]:
    keys: list[str] = []
    with engine.begin() as connection:
        for index, name in enumerate(NAMES[:count]):
            event, awards = simap_award(name)
            award = awards[0].model_copy(
                update={"award_date": dt.date(2026, 8, 13) - dt.timedelta(days=index)}
            )
            keys.append(materialize(connection, event, award, target_icp_id=icp_id).signal_key)
    return keys


def test_history_cursor_round_trips_exactly_and_rejects_malformed_payloads() -> None:
    value = HistoryCursor(date=dt.date(2026, 2, 3), signal_key="a" * 64)
    encoded = encode_history_cursor(value)

    assert decode_history_cursor(encoded) == value
    for malformed in (
        "",
        "not-base64!",
        "e30",  # {}
        "eyJ2IjoyLCJkIjoiMjAyNi0wMi0wMyIsImsiOiJhIn0",  # version inconnue
        "x" * 513,
    ):
        with pytest.raises(InvalidHistoryCursor):
            decode_history_cursor(malformed)


def test_history_pages_follow_effective_date_without_overlap_or_missing_rows(
    engine, account
) -> None:
    account_id, icp_id = account
    expected = _seed(engine, icp_id)

    seen: list[str] = []
    cursor: str | None = None
    with engine.begin() as connection:
        while True:
            page = history_page(
                connection,
                account_id=account_id,
                as_of=READ_ON,
                allowed_target_icp_ids=frozenset({icp_id}),
                limit=2,
                cursor=cursor,
            )
            seen.extend(item.signal.signal_key for item in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    assert seen == expected
    assert len(seen) == len(set(seen))


def test_history_uses_notification_then_publication_as_explicit_fallbacks(
    engine, account
) -> None:
    account_id, icp_id = account
    with engine.begin() as connection:
        event_a, awards_a = simap_award("29997-02")
        notification = awards_a[0].model_copy(
            update={
                "award_date": None,
                "contract_notification_date": dt.date(2026, 8, 12),
            }
        )
        notification_key = materialize(
            connection, event_a, notification, target_icp_id=icp_id
        ).signal_key

        event_b, awards_b = simap_award("33112-02")
        publication = awards_b[0].model_copy(
            update={"award_date": None, "contract_notification_date": None}
        )
        publication_key = materialize(
            connection, event_b, publication, target_icp_id=icp_id
        ).signal_key

        page = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=10,
        )

    by_key = {item.signal.signal_key: item for item in page.items}
    assert by_key[notification_key].history_date == dt.date(2026, 8, 12)
    assert by_key[notification_key].history_date_kind == "notification"
    assert by_key[publication_key].history_date == by_key[publication_key].signal.event.published_on
    assert by_key[publication_key].history_date_kind == "publication"


def test_history_cursor_never_crosses_the_account_boundary(engine, account) -> None:
    account_id, icp_id = account
    expected = set(_seed(engine, icp_id, count=2))
    with engine.begin() as connection:
        other_account = make_account(connection, "history-other@kivou.test", "Other")
        other_icp = make_icp(connection, other_account, "Other history")
        event, awards = simap_award("38918-02")
        foreign = materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": dt.date(2026, 8, 14)}),
            target_icp_id=other_icp,
        ).signal_key

        page = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=10,
        )

    keys = {item.signal.signal_key for item in page.items}
    assert keys == expected
    assert foreign not in keys


def test_history_applies_authorised_winner_and_current_event_filters(engine, account) -> None:
    account_id, icp_id = account
    with engine.begin() as connection:
        recent_event, recent_awards = simap_award("29997-02")
        recent = recent_awards[0].model_copy(update={"award_date": dt.date(2026, 8, 13)})
        recent_key = materialize(
            connection, recent_event, recent, target_icp_id=icp_id
        ).signal_key

        stale_event, stale_awards = simap_award("33112-02")
        stale = stale_awards[0].model_copy(update={"award_date": dt.date(2024, 1, 3)})
        materialize(connection, stale_event, stale, target_icp_id=icp_id)

        winner = recent.awardee_organizations()[0].legal_name
        by_winner = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            winner=winner,
            limit=10,
        )
        by_event = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            primary_event="recent_award",
            limit=10,
        )

    assert [item.signal.signal_key for item in by_winner.items] == [recent_key]
    assert [item.signal.signal_key for item in by_event.items] == [recent_key]


def test_history_cursor_handles_equal_and_missing_dates_without_overlap(engine, account) -> None:
    account_id, icp_id = account
    dated: list[str] = []
    with engine.begin() as connection:
        for fixture in ("29997-02", "33112-02"):
            event, awards = simap_award(fixture)
            award = awards[0].model_copy(update={"award_date": dt.date(2026, 8, 12)})
            dated.append(materialize(connection, event, award, target_icp_id=icp_id).signal_key)
        event, awards = simap_award("33885-03")
        missing_event = event.model_copy(update={"published_at": None})
        missing_award = awards[0].model_copy(
            update={"award_date": None, "contract_notification_date": None}
        )
        missing_key = materialize(
            connection, missing_event, missing_award, target_icp_id=icp_id
        ).signal_key

    seen: list[str] = []
    cursor: str | None = None
    with engine.begin() as connection:
        while True:
            page = history_page(
                connection,
                account_id=account_id,
                as_of=READ_ON,
                allowed_target_icp_ids=frozenset({icp_id}),
                limit=1,
                cursor=cursor,
            )
            seen.extend(item.signal.signal_key for item in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

    assert seen[:2] == sorted(dated)
    assert seen[-1] == missing_key
    assert len(seen) == len(set(seen)) == 3


def test_history_cursor_ignores_a_newer_concurrent_insert_until_a_new_walk(
    engine, account
) -> None:
    account_id, icp_id = account
    original = _seed(engine, icp_id, count=2)
    with engine.begin() as connection:
        first = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=1,
        )
    assert first.next_cursor is not None

    with engine.begin() as connection:
        event, awards = simap_award("33885-03")
        newer_key = materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": dt.date(2026, 8, 14)}),
            target_icp_id=icp_id,
        ).signal_key
        second = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=10,
            cursor=first.next_cursor,
        )
        restarted = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=10,
        )

    walked = [item.signal.signal_key for item in first.items + second.items]
    assert walked == original
    assert newer_key not in walked
    assert next(item.signal.signal_key for item in restarted.items) == newer_key


def test_history_skips_non_renderable_batches_and_stale_icp_revisions(engine, account) -> None:
    account_id, icp_id = account
    with engine.begin() as connection:
        event, awards = simap_award("29997-02")
        hidden_key = materialize(
            connection, event, awards[0], target_icp_id=icp_id
        ).signal_key
        award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == hidden_key
            )
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == hidden_key)
            .values(winner_name=None)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == award_key)
            .values(awardee_parties=[{"members": []}])
        )

        visible_event, visible_awards = simap_award("33112-02")
        visible_key = materialize(
            connection, visible_event, visible_awards[0], target_icp_id=icp_id
        ).signal_key
        page = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=1,
            scan_cap=10,
        )

        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == icp_id)
            .values(matching_revision=target_icp.c.matching_revision + 1)
        )
        stale = history_page(
            connection,
            account_id=account_id,
            as_of=READ_ON,
            allowed_target_icp_ids=frozenset({icp_id}),
            limit=10,
        )

    assert [item.signal.signal_key for item in page.items] == [visible_key]
    assert page.excluded_without_display_name == 1
    assert stale.items == ()


def test_the_subdivision_filter_compares_the_derived_department(engine) -> None:
    """§26 — le filtre porte sur la subdivision DÉRIVÉE, pas seulement publiée.

    Un signal antérieur à ce lot ne porte aucun `subdivision_code` STOCKÉ : le
    connecteur n'écrivait alors que le code postal. La carte et le détail
    dérivent déjà `FR-92` à la lecture (`location_subdivision`) ; comparer la
    valeur brute exclurait ce même signal du filtre qui le montre pourtant.
    """
    now = dt.datetime.combine(READ_ON, dt.time(9, 0), tzinfo=dt.UTC)
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: now,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    signup = client.post(
        "/auth/signup",
        json={
            "email": "subdivision-filter@kivou.eu",
            "password": PASSWORD,
            "company_name": "Subdivision Filter",
            "locale": "fr",
        },
    )
    assert signup.status_code == 201, signup.text
    pin_session_cookie(client, signup)
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(connection, account_id=account_id, plan="scale", subscription_id="sub_hist_subdiv", now=now)

    icp_id = client.post(
        "/target-icps", json={"label": "Subdivision", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]

    with engine.begin() as connection:
        event, awards = simap_award(NAMES[0])
        award = awards[0].model_copy(
            update={
                "award_date": dt.date(2026, 8, 13),
                # Aucun `subdivision_code` publié : seul le code postal l'est,
                # exactement le cas DECP 2022 antérieur à ce lot.
                "place_of_performance": Location(country="FR", postal_code="92350"),
            }
        )
        materialize(connection, event, award, target_icp_id=icp_id)

    matched = client.get("/signals?view=history&subdivision_code=FR-92")
    assert matched.status_code == 200, matched.text
    assert len(matched.json()["items"]) == 1

    unmatched = client.get("/signals?view=history&subdivision_code=FR-75")
    assert unmatched.status_code == 200, unmatched.text
    assert unmatched.json()["items"] == []
