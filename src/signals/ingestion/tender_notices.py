"""Job isolé de capture des dossiers au stade de l'appel d'offres."""

from __future__ import annotations

import dataclasses
import datetime as dt
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

import sqlalchemy as sa

from signals.connectors.boamp import BoampClient, parse_tender_notice, supported_tender_payload
from signals.connectors.simap import SimapClient, extract_tender
from signals.connectors.ted import TedClient
from signals.connectors.ted import parse_tender_notice as parse_ted_tender_notice
from signals.documents.early_capture import (
    StorageQuotaReached,
    capture_tender_notice,
    purge_expired_unlinked,
)
from signals.documents.fetch import DocumentFetcher
from signals.domain import TenderNotice
from signals.persistence.identity import event_key
from signals.persistence.schema import source_event


class TenderNoticeSource(Protocol):
    def acquire(
        self,
        *,
        since: dt.date,
        until: dt.date,
        max_records: int | None,
        retrieved_at: dt.datetime,
    ) -> Iterable[TenderNotice]: ...


class BoampTenderNotices:
    def __init__(self, client: BoampClient) -> None:
        self.client = client

    def acquire(
        self,
        *,
        since: dt.date,
        until: dt.date,
        max_records: int | None,
        retrieved_at: dt.datetime,
    ) -> Iterable[TenderNotice]:
        for record in self.client.fetch_tenders_since(
            since, until=until, max_records=max_records
        ):
            if supported_tender_payload(record):
                yield parse_tender_notice(record, retrieved_at=retrieved_at)


class TedTenderNotices:
    def __init__(self, client: TedClient) -> None:
        self.client = client

    def acquire(
        self,
        *,
        since: dt.date,
        until: dt.date,
        max_records: int | None,
        retrieved_at: dt.datetime,
    ) -> Iterable[TenderNotice]:
        query = (
            f"form-type=competition AND publication-date>={since:%Y%m%d} "
            f"AND publication-date<={until:%Y%m%d} SORT BY publication-number DESC"
        )
        for reference in self.client.search_all(query, wanted=max_records or 500):
            yield parse_ted_tender_notice(
                self.client.fetch_notice_xml(reference.publication_number),
                publication_number=reference.publication_number,
                retrieved_at=retrieved_at,
            )


class SimapTenderNotices:
    def __init__(self, client: SimapClient) -> None:
        self.client = client

    def acquire(
        self,
        *,
        since: dt.date,
        until: dt.date,
        max_records: int | None,
        retrieved_at: dt.datetime,
    ) -> Iterable[TenderNotice]:
        references = self.client.search_all_awards(
            wanted=max_records or 500,
            published_from=since.isoformat(),
            pub_type_filters=("tender",),
        )
        for reference in references:
            notice = extract_tender(
                self.client.fetch_publication(
                    reference.project_id, reference.publication_id
                ),
                retrieved_at=retrieved_at,
            )
            published = notice.event.published_at
            published_on = published.date() if isinstance(published, dt.datetime) else published
            if published_on is None or published_on <= until:
                yield notice


@dataclasses.dataclass(frozen=True)
class TenderNoticeRunResult:
    notices_ingested: int = 0
    documents_created: int = 0
    stopped_reason: str | None = None


def _persist_event(connection: sa.Connection, notice: TenderNotice, *, now: dt.datetime) -> None:
    event = notice.event
    key = event_key(event)
    exists = connection.execute(
        sa.select(sa.literal(1)).where(source_event.c.event_key == key)
    ).scalar()
    if exists:
        return
    published = event.published_at
    published_on = published.date() if isinstance(published, dt.datetime) else published
    connection.execute(
        sa.insert(source_event).values(
            event_key=key,
            source_system=event.provenance.source_system,
            source_notice_id=event.provenance.source_notice_id,
            notice_version=event.provenance.notice_version,
            source_country=event.provenance.source_country,
            source_procedure_id=event.provenance.source_procedure_id,
            source_url=event.provenance.source_url,
            event_type=event.event_type,
            published_at_raw=published.isoformat() if published else None,
            published_on=published_on,
            published_precision=event.published_precision(),
            discovered_at=event.provenance.retrieved_at,
            procedure_buyers=[buyer.model_dump(mode="json") for buyer in event.procedure_buyers],
            created_at=now,
        )
    )


class TenderNoticeJob:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        sources: Mapping[str, TenderNoticeSource],
        fetcher: DocumentFetcher,
        quota_bytes: int,
        request_interval_seconds: float = 1.0,
        enabled: Callable[[], bool] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.engine = engine
        self.sources = sources
        self.fetcher = fetcher
        self.quota_bytes = quota_bytes
        self.request_interval_seconds = request_interval_seconds
        self.enabled = enabled or (lambda: True)
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.sleep = sleep

    def run(
        self,
        *,
        source: str,
        since: dt.date,
        until: dt.date,
        max_records: int | None = None,
    ) -> TenderNoticeRunResult:
        if until < since:
            raise ValueError("tender notice window ends before it starts")
        adapter = self.sources[source]
        started = self.clock()
        ingested = created = 0
        with self.engine.begin() as connection:
            purge_expired_unlinked(connection, now=started)
        for notice in adapter.acquire(
            since=since,
            until=until,
            max_records=max_records,
            retrieved_at=started,
        ):
            if not self.enabled():
                return TenderNoticeRunResult(ingested, created, "kill_switch")
            if ingested:
                self.sleep(self.request_interval_seconds)
            try:
                with self.engine.begin() as connection:
                    _persist_event(connection, notice, now=started)
                    result = capture_tender_notice(
                        connection,
                        notice,
                        fetcher=self.fetcher,
                        quota_bytes=self.quota_bytes,
                    )
            except StorageQuotaReached:
                return TenderNoticeRunResult(ingested, created, "storage_quota")
            ingested += 1
            created += result.documents_created
        return TenderNoticeRunResult(ingested, created)
