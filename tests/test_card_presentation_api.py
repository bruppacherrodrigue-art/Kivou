from __future__ import annotations

import datetime as dt
import json
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from feed_helpers import COMPLETE_ICP_INPUT, ORIGIN, PASSWORD, SIMAP_RICH, materialize_simap
from sqlalchemy.engine import Engine

from signals.api import ApiConfig, create_app, routes_signals
from signals.billing import discovery
from signals.card_intelligence import service as card_intelligence_service
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import publish_factual_fallback
from signals.card_intelligence.store import published_for_signals
from signals.feed.query import owned_signal
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path: pathlib.Path) -> Engine:
    database = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'presentation-api.db'}")
    migrate_to_latest(database)
    return database


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app(
        engine,
        ApiConfig(
            cookie_secure=False,
            allowed_origin=ORIGIN,
            session_ttl=dt.timedelta(days=30),
        ),
        now_override=lambda: NOW,
    )
    with TestClient(app, headers={"Origin": ORIGIN}) as test_client:
        response = test_client.post(
            "/auth/signup",
            json={
                "email": "presentation-api@negoce-romand.ch",
                "password": PASSWORD,
                "company_name": "Kivou Presentation Test",
                "locale": "fr",
            },
        )
        assert response.status_code == 201, response.text
        yield test_client


def _publish_presentation(
    engine: Engine,
    client: TestClient,
    *,
    unlock: bool,
) -> tuple[str, dict[str, object]]:
    account_id = client.get("/me").json()["account_id"]
    response = client.post(
        "/target-icps",
        json={"label": "Matériaux", "customer_input": COMPLETE_ICP_INPUT},
    )
    assert response.status_code == 201, response.text
    target_icp_id = response.json()["target_icp_id"]

    with engine.begin() as connection:
        materialized = materialize_simap(
            connection,
            SIMAP_RICH,
            target_icp_id=target_icp_id,
        )
        item = owned_signal(
            connection,
            account_id=account_id,
            signal_key=materialized.signal_key,
            as_of=NOW.date(),
            allowed_target_icp_ids=frozenset({target_icp_id}),
        )
        assert item is not None
        source = build_presentation_input(
            connection,
            item=item,
            account_id=account_id,
            language="fr",
        )
        publish_factual_fallback(connection, source=source, now=NOW)
        published = published_for_signals(
            connection,
            account_id=account_id,
            bindings={
                materialized.signal_key: (
                    materialized.revision,
                    source.target_icp_revision,
                )
            },
            language="fr",
        )[materialized.signal_key]
        if unlock:
            granted = discovery.grant_up_to_limit(
                connection,
                account_id=account_id,
                candidates=[item],
                now=NOW,
            )
            assert granted == (materialized.signal_key,)
    return materialized.signal_key, published


def _card_selects(engine: Engine) -> tuple[list[str], Any]:
    statements: list[str] = []

    def record_query(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = statement.lstrip().lower()
        if normalized.startswith("select") and "card_presentation_artifact" in normalized:
            statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", record_query)
    return statements, record_query


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for child in value.values()
            for nested in _all_keys(child)
        }
    if isinstance(value, list | tuple):
        return {nested for child in value for nested in _all_keys(child)}
    return set()


def test_feed_and_detail_expose_the_same_published_artifact_without_generation(
    engine: Engine,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_key, expected = _publish_presentation(engine, client, unlock=True)

    def generation_is_forbidden(*_args, **_kwargs):
        raise AssertionError("a GET request must never call Card Intelligence")

    monkeypatch.setattr(
        card_intelligence_service,
        "generate_and_publish",
        generation_is_forbidden,
    )

    statements, listener = _card_selects(engine)
    try:
        feed_response = client.get("/signals?freshness=all")
    finally:
        sa.event.remove(engine, "before_cursor_execute", listener)
    assert feed_response.status_code == 200, feed_response.text
    assert len(statements) == 1, "the feed must batch-load presentations in one SELECT"

    feed_item = next(
        item for item in feed_response.json()["items"] if item["signal_id"] == signal_key
    )
    assert feed_item["locked"] is False
    assert feed_item["presentation"] == expected

    detail_response = client.get(f"/signals/{signal_key}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["locked"] is False
    assert detail["presentation"] == expected
    assert detail["presentation"] == feed_item["presentation"]


def test_locked_feed_and_detail_never_expose_presentation_or_its_content(
    engine: Engine,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_key, published = _publish_presentation(engine, client, unlock=False)

    def do_not_grant_discovery(_connection, _account_id, access, _allowed, _now):
        return access

    monkeypatch.setattr(routes_signals, "_grant_discovery", do_not_grant_discovery)

    statements, listener = _card_selects(engine)
    try:
        feed_response = client.get("/signals?freshness=all")
        detail_response = client.get(f"/signals/{signal_key}")
    finally:
        sa.event.remove(engine, "before_cursor_execute", listener)

    assert feed_response.status_code == 200, feed_response.text
    teaser = next(
        item for item in feed_response.json()["items"] if item["signal_id"] == signal_key
    )
    assert detail_response.status_code == 200, detail_response.text
    locked_detail = detail_response.json()
    assert teaser["locked"] is True
    assert locked_detail["locked"] is True
    assert statements == [], "locked cards must not even read presentation artifacts"

    leaked_strings = json.dumps((teaser, locked_detail), ensure_ascii=False)
    for locked_payload in (teaser, locked_detail):
        keys = _all_keys(locked_payload)
        assert "presentation" not in keys
        assert "content" not in keys
    assert str(published["artifact_id"]) not in leaked_strings
    content = published["content"]
    assert isinstance(content, dict)
    assert str(content["headline"]) not in leaked_strings
    assert str(content["award_summary"]) not in leaked_strings
    assert "Egli Gartenbau AG Sursee" not in leaked_strings
