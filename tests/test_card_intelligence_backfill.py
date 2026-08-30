from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import sqlalchemy as sa

from signals.card_intelligence import backfill, cli
from signals.persistence.database import create_database_engine

NOW = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.UTC)


@dataclass(frozen=True)
class Source:
    signal_key: str

    def fingerprint(self) -> str:
        return f"fingerprint:{self.signal_key}"


def item(signal_key: str):
    return SimpleNamespace(signal=SimpleNamespace(signal_key=signal_key))


def test_explicit_next_offset_reaches_the_fifty_first_item(monkeypatch):
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    items = tuple(item(f"signal-{index:02d}") for index in range(51))
    calls: list[tuple[int, int]] = []

    def page(_connection, *, limit, offset, scan_cap, **_kwargs):
        calls.append((offset, scan_cap))
        return SimpleNamespace(
            items=items[offset : offset + limit],
            has_more=len(items) > offset + limit,
            scan_truncated=len(items) > scan_cap,
        )

    monkeypatch.setattr(backfill, "feed_page", page)
    monkeypatch.setattr(
        backfill,
        "build_presentation_input",
        lambda _connection, *, item, **_kwargs: Source(item.signal.signal_key),
    )
    monkeypatch.setattr(backfill, "current_publication_row", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        backfill,
        "publish_factual_fallback",
        lambda *_args, **_kwargs: {"qa_status": "FALLBACK", "published_at": NOW},
    )

    first = backfill.backfill_factual_presentations(
        engine,
        account_id="account-1",
        as_of=NOW.date(),
        language="fr",
        limit=50,
        now=NOW,
    )
    second = backfill.backfill_factual_presentations(
        engine,
        account_id="account-1",
        as_of=NOW.date(),
        language="fr",
        limit=50,
        offset=first.next_offset or 0,
        now=NOW,
    )

    assert (first.scanned, first.published, first.next_offset) == (50, 50, 50)
    assert (second.scanned, second.published, second.next_offset) == (1, 1, None)
    assert calls == [(0, 500), (50, 500)]


def test_full_bounded_scan_reaches_items_after_many_raw_candidates_are_excluded(
    monkeypatch,
):
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    calls: list[tuple[int, int]] = []
    selected = (item("displayable-51"),)

    def page(_connection, *, limit, offset, scan_cap, **_kwargs):
        calls.append((offset, scan_cap))
        # Models feed_page after 51 raw candidates: the first 50 have no
        # display identity, while the 51st is selectable.
        assert scan_cap == 500
        return SimpleNamespace(
            items=selected[offset : offset + limit],
            has_more=False,
            scan_truncated=False,
        )

    monkeypatch.setattr(backfill, "feed_page", page)
    monkeypatch.setattr(
        backfill,
        "build_presentation_input",
        lambda _connection, *, item, **_kwargs: Source(item.signal.signal_key),
    )
    monkeypatch.setattr(backfill, "current_publication_row", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        backfill,
        "publish_factual_fallback",
        lambda *_args, **_kwargs: {"qa_status": "FALLBACK", "published_at": NOW},
    )

    result = backfill.backfill_factual_presentations(
        engine,
        account_id="account-1",
        as_of=NOW.date(),
        language="fr",
        limit=50,
        now=NOW,
    )

    assert (result.scanned, result.published, result.next_offset) == (1, 1, None)
    assert calls == [(0, 500)]


def test_item_savepoint_preserves_valid_publications_when_a_later_item_fails(
    monkeypatch,
):
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE publication_audit (signal_key TEXT PRIMARY KEY)")

    items = (item("good-1"), item("bad"), item("good-2"))
    monkeypatch.setattr(
        backfill,
        "feed_page",
        lambda *_args, **_kwargs: SimpleNamespace(
            items=items,
            has_more=False,
            scan_truncated=False,
        ),
    )
    monkeypatch.setattr(
        backfill,
        "build_presentation_input",
        lambda _connection, *, item, **_kwargs: Source(item.signal.signal_key),
    )
    monkeypatch.setattr(backfill, "current_publication_row", lambda *_args, **_kwargs: None)

    def publish(connection, *, source, **_kwargs):
        connection.execute(
            sa.text("INSERT INTO publication_audit VALUES (:signal_key)"),
            {"signal_key": source.signal_key},
        )
        if source.signal_key == "bad":
            raise RuntimeError("malformed source")
        return {"qa_status": "FALLBACK", "published_at": NOW}

    monkeypatch.setattr(backfill, "publish_factual_fallback", publish)

    result = backfill.backfill_factual_presentations(
        engine,
        account_id="account-1",
        as_of=NOW.date(),
        language="fr",
        limit=3,
        now=NOW,
    )

    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT signal_key FROM publication_audit ORDER BY signal_key")
        ).scalars().all()
    assert rows == ["good-1", "good-2"]
    assert (result.published, result.failed) == (2, 1)
    assert result.failures == ("bad:RuntimeError",)


def test_cli_returns_nonzero_when_any_item_failed(monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_database_engine", lambda: object())
    monkeypatch.setattr(
        cli,
        "backfill_factual_presentations",
        lambda *_args, **_kwargs: backfill.BackfillResult(
            scanned=2,
            published=1,
            unchanged=0,
            failed=1,
            next_offset=2,
            failures=("signal-bad:ValueError",),
        ),
    )

    exit_code = cli.main(
        [
            "backfill-fallbacks",
            "--account-id",
            "account-1",
            "--as-of",
            "2026-08-30",
            "--language",
            "fr",
            "--limit",
            "2",
        ]
    )

    assert exit_code == 1
    assert "failed=1" in capsys.readouterr().out
