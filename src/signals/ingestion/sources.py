from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Protocol

from signals.connectors.boamp import BoampClient, BoampUnsupportedPayload, parse_award_notice
from signals.connectors.decp import DecpClient, parse_contract
from signals.connectors.simap import SimapClient
from signals.connectors.simap import extract as extract_simap
from signals.connectors.simap.client import AWARD_PUB_TYPE_FILTERS
from signals.connectors.ted import TedClient
from signals.connectors.ted import extract as extract_ted
from signals.ingestion.model import SourceName

OVERLAP_DAYS: dict[SourceName, int] = {
    "simap": 3,
    "boamp": 7,
    "decp": 30,
    "ted": 3,
}
INITIAL_LOOKBACK_DAYS: dict[SourceName, int] = {
    "simap": 7,
    "boamp": 14,
    "decp": 30,
    "ted": 3,
}


@dataclasses.dataclass(frozen=True)
class SourceWindow:
    since: dt.date
    until: dt.date

    def __post_init__(self) -> None:
        if self.until < self.since:
            raise ValueError("source window ends before it starts")


@dataclasses.dataclass(frozen=True)
class AcquiredPublication:
    event: Any
    awards: tuple[Any, ...]


@dataclasses.dataclass(frozen=True)
class AcquisitionResult:
    source: SourceName
    publications: tuple[AcquiredPublication, ...]
    fetched: int
    accepted: int
    rejected: int
    complete: bool
    cursor_after: dict[str, Any]


class AcquisitionFailure(RuntimeError):
    """A source failure carrying acquisition progress for durable audit."""

    def __init__(self, cause: Exception, *, partial: AcquisitionResult) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.partial = partial

    @property
    def category(self) -> Any:
        return getattr(self.cause, "category", None)

    @property
    def status_code(self) -> Any:
        return getattr(self.cause, "status_code", None)


class ProductionSource(Protocol):
    source: SourceName

    def acquire(
        self,
        window: SourceWindow,
        *,
        retrieved_at: dt.datetime,
        max_records: int | None = None,
    ) -> AcquisitionResult: ...


def checkpoint_window(
    source: SourceName,
    *,
    checkpoint_end: dt.datetime | None,
    until: dt.datetime,
    explicit_since: dt.date | None = None,
) -> SourceWindow:
    if explicit_since is not None:
        since = explicit_since
    elif checkpoint_end is not None:
        since = checkpoint_end.date() - dt.timedelta(days=OVERLAP_DAYS[source])
    else:
        since = until.date() - dt.timedelta(days=INITIAL_LOOKBACK_DAYS[source])
    return SourceWindow(since=since, until=until.date())


def _result(
    source: SourceName,
    publications: list[AcquiredPublication],
    *,
    fetched: int,
    rejected: int,
    complete: bool,
    window: SourceWindow,
) -> AcquisitionResult:
    return AcquisitionResult(
        source=source,
        publications=tuple(publications),
        fetched=fetched,
        accepted=len(publications),
        rejected=rejected,
        complete=complete,
        cursor_after={"window_end": window.until.isoformat()},
    )


class BoampSource:
    source: SourceName = "boamp"

    def __init__(self, client: BoampClient) -> None:
        self.client = client

    def acquire(
        self,
        window: SourceWindow,
        *,
        retrieved_at: dt.datetime,
        max_records: int | None = None,
    ) -> AcquisitionResult:
        probe = max_records + 1 if max_records is not None else None
        publications: list[AcquiredPublication] = []
        fetched = 0
        rejected = 0
        complete = True
        try:
            for record in self.client.fetch_awards_since(
                window.since, until=window.until, max_records=probe
            ):
                if max_records is not None and fetched >= max_records:
                    complete = False
                    break
                fetched += 1
                try:
                    event, awards = parse_award_notice(record, retrieved_at=retrieved_at)
                except BoampUnsupportedPayload:
                    rejected += 1
                    continue
                publications.append(AcquiredPublication(event, awards))
        except Exception as error:
            raise AcquisitionFailure(
                error,
                partial=_result(
                    self.source,
                    publications,
                    fetched=fetched,
                    rejected=rejected,
                    complete=False,
                    window=window,
                ),
            ) from error
        return _result(
            self.source,
            publications,
            fetched=fetched,
            rejected=rejected,
            complete=complete,
            window=window,
        )


class DecpSource:
    source: SourceName = "decp"

    def __init__(self, client: DecpClient) -> None:
        self.client = client

    def acquire(
        self,
        window: SourceWindow,
        *,
        retrieved_at: dt.datetime,
        max_records: int | None = None,
    ) -> AcquisitionResult:
        probe = max_records + 1 if max_records is not None else None
        publications: list[AcquiredPublication] = []
        fetched = 0
        complete = True
        try:
            for record in self.client.fetch_contracts_since(
                window.since, until=window.until, max_records=probe
            ):
                if max_records is not None and fetched >= max_records:
                    complete = False
                    break
                fetched += 1
                event, award = parse_contract(record, retrieved_at=retrieved_at)
                publications.append(AcquiredPublication(event, (award,)))
        except Exception as error:
            raise AcquisitionFailure(
                error,
                partial=_result(
                    self.source,
                    publications,
                    fetched=fetched,
                    rejected=0,
                    complete=False,
                    window=window,
                ),
            ) from error
        return _result(
            self.source,
            publications,
            fetched=fetched,
            rejected=0,
            complete=complete,
            window=window,
        )


class SimapSource:
    source: SourceName = "simap"

    def __init__(self, client: SimapClient, *, max_pages_per_filter: int = 20) -> None:
        self.client = client
        self.max_pages_per_filter = max_pages_per_filter

    def acquire(
        self,
        window: SourceWindow,
        *,
        retrieved_at: dt.datetime,
        max_records: int | None = None,
    ) -> AcquisitionResult:
        refs: dict[str, Any] = {}
        selected: list[Any] = []
        publications: list[AcquiredPublication] = []
        complete = True
        wanted = max_records + 1 if max_records is not None else None
        try:
            for pub_type in AWARD_PUB_TYPE_FILTERS:
                cursor = None
                for page in range(self.max_pages_per_filter):
                    rows, cursor = self.client.search_awards(
                        pub_type_filter=pub_type,
                        published_from=window.since.isoformat(),
                        last_item=cursor,
                    )
                    for ref in rows:
                        if (
                            ref.publication_date
                            and ref.publication_date[:10] > window.until.isoformat()
                        ):
                            continue
                        refs.setdefault(ref.publication_id, ref)
                    if not rows or not cursor:
                        break
                    if wanted is not None and len(refs) >= wanted:
                        complete = False
                        break
                else:
                    complete = False
                if wanted is not None and len(refs) >= wanted:
                    complete = False
                    break
            selected = list(refs.values())
            if max_records is not None:
                selected = selected[:max_records]
            for ref in selected:
                payload = self.client.fetch_publication(ref.project_id, ref.publication_id)
                extraction = extract_simap(
                    payload, search_entry=ref.search_entry, retrieved_at=retrieved_at
                )
                publications.append(AcquiredPublication(extraction.event, extraction.awards))
        except Exception as error:
            raise AcquisitionFailure(
                error,
                partial=_result(
                    self.source,
                    publications,
                    fetched=len(selected) if selected else len(refs),
                    rejected=0,
                    complete=False,
                    window=window,
                ),
            ) from error
        return _result(
            self.source,
            publications,
            fetched=len(selected),
            rejected=0,
            complete=complete,
            window=window,
        )


class TedSource:
    source: SourceName = "ted"

    def __init__(self, client: TedClient, *, page_size: int = 250, max_pages: int = 20) -> None:
        self.client = client
        self.page_size = page_size
        self.max_pages = max_pages

    def acquire(
        self,
        window: SourceWindow,
        *,
        retrieved_at: dt.datetime,
        max_records: int | None = None,
    ) -> AcquisitionResult:
        query = (
            "form-type=result "
            f"AND publication-date>={window.since.strftime('%Y%m%d')} "
            f"AND publication-date<={window.until.strftime('%Y%m%d')} "
            "SORT BY publication-number DESC"
        )
        refs = []
        publications: list[AcquiredPublication] = []
        complete = True
        total = 0
        wanted = max_records + 1 if max_records is not None else None
        try:
            for page in range(1, self.max_pages + 1):
                limit = (
                    self.page_size
                    if wanted is None
                    else min(self.page_size, wanted - len(refs))
                )
                rows, total = self.client.search(query, limit=limit, page=page)
                refs.extend(rows)
                if len(refs) >= total:
                    break
                if not rows:
                    complete = False
                    break
                if wanted is not None and len(refs) >= wanted:
                    complete = False
                    break
            else:
                complete = len(refs) >= total
            if max_records is not None and len(refs) > max_records:
                complete = False
                refs = refs[:max_records]
            for ref in refs:
                extraction = extract_ted(
                    self.client.fetch_notice_xml(ref.publication_number),
                    retrieved_at=retrieved_at,
                )
                publications.append(AcquiredPublication(extraction.event, extraction.awards))
        except Exception as error:
            raise AcquisitionFailure(
                error,
                partial=_result(
                    self.source,
                    publications,
                    fetched=len(refs),
                    rejected=0,
                    complete=False,
                    window=window,
                ),
            ) from error
        return _result(
            self.source,
            publications,
            fetched=len(refs),
            rejected=0,
            complete=complete,
            window=window,
        )


def production_sources() -> dict[SourceName, ProductionSource]:
    return {
        "simap": SimapSource(SimapClient()),
        "boamp": BoampSource(BoampClient()),
        "decp": DecpSource(DecpClient()),
        "ted": TedSource(TedClient()),
    }
