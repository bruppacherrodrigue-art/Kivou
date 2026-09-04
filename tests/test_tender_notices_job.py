from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import sqlalchemy as sa

from signals.documents.fetch import FetchResult
from signals.ingestion.tender_notices import (
    BoampTenderNotices,
    SimapTenderNotices,
    TedTenderNotices,
    TenderNoticeJob,
)
from signals.persistence.schema import procedure_documents, source_event

FIXTURE = Path(__file__).parent / "fixtures" / "france" / "boamp_tender_notice.json"
NOW = dt.datetime(2026, 9, 4, 8, tzinfo=dt.UTC)


class BoampClientStub:
    def __init__(self) -> None:
        self.calls = []

    def fetch_tenders_since(self, since, *, until=None, max_records=None):
        self.calls.append((since, until, max_records))
        yield json.loads(FIXTURE.read_text(encoding="utf-8"))


class ExternalFetcher:
    def fetch(self, url: str) -> FetchResult:
        return FetchResult(url=url, access_status="external", media_type="text/html")


def test_daily_job_and_replay_share_the_same_date_windowed_path() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    source_event.create(engine)
    procedure_documents.create(engine)
    client = BoampClientStub()
    job = TenderNoticeJob(
        engine,
        sources={"boamp": BoampTenderNotices(client)},
        fetcher=ExternalFetcher(),
        quota_bytes=10_000,
        clock=lambda: NOW,
    )

    result = job.run(
        source="boamp",
        since=dt.date(2026, 8, 28),
        until=dt.date(2026, 9, 3),
        max_records=50,
    )

    assert client.calls == [(dt.date(2026, 8, 28), dt.date(2026, 9, 3), 50)]
    assert result.notices_ingested == 1
    assert result.documents_created == 1
    with engine.connect() as connection:
        assert connection.execute(sa.select(source_event.c.event_type)).scalar_one() == (
            "tender_notice"
        )
        assert connection.execute(
            sa.select(procedure_documents.c.access_status)
        ).scalar_one() == "external"


def test_job_stops_cleanly_before_next_notice_when_kill_switch_is_off() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    source_event.create(engine)
    procedure_documents.create(engine)
    job = TenderNoticeJob(
        engine,
        sources={"boamp": BoampTenderNotices(BoampClientStub())},
        fetcher=ExternalFetcher(),
        quota_bytes=10_000,
        enabled=lambda: False,
        clock=lambda: NOW,
    )

    result = job.run(
        source="boamp",
        since=dt.date(2026, 9, 3),
        until=dt.date(2026, 9, 3),
    )

    assert result.stopped_reason == "kill_switch"
    assert result.notices_ingested == 0


def test_ted_source_searches_competitions_and_parses_bt15() -> None:
    class Client:
        def search_all(self, query, *, wanted):
            self.query = query
            from signals.connectors.ted import NoticeRef

            return [NoticeRef("612553-2026")]

        def fetch_notice_xml(self, publication_number):
            assert publication_number == "612553-2026"
            return (
                Path(__file__).parent / "fixtures" / "ted" / "612553-2026.tender.xml"
            ).read_bytes()

    client = Client()
    notices = list(
        TedTenderNotices(client).acquire(
            since=dt.date(2026, 9, 3),
            until=dt.date(2026, 9, 3),
            max_records=5,
            retrieved_at=NOW,
        )
    )

    assert "form-type=competition" in client.query
    assert notices[0].document_urls


def test_simap_source_records_auth_required_without_requesting_documents() -> None:
    class Client:
        def search_all_awards(self, *, wanted, published_from, pub_type_filters):
            from signals.connectors.simap import PublicationRef

            assert pub_type_filters == ("tender",)
            return [PublicationRef("project", "publication")]

        def fetch_publication(self, project_id, publication_id):
            return json.loads(
                (
                    Path(__file__).parent
                    / "fixtures"
                    / "simap"
                    / "22917-01.tender.json"
                ).read_text(encoding="utf-8")
            )

    notices = list(
        SimapTenderNotices(Client()).acquire(
            since=dt.date(2026, 2, 9),
            until=dt.date(2026, 2, 9),
            max_records=5,
            retrieved_at=NOW,
        )
    )

    assert notices[0].document_access_status == "auth_required"
