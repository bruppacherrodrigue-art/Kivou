"""Phase 1 — historique exhaustif, tri factuel et curseur fermé."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from feed_helpers import make_account, make_icp, materialize, simap_award

from signals.feed.history import (
    HistoryCursor,
    InvalidHistoryCursor,
    decode_history_cursor,
    encode_history_cursor,
)
from signals.feed.query import history_page
from signals.persistence.database import create_database_engine, migrate_to_latest

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
