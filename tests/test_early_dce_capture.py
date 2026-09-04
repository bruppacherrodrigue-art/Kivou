from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import sqlalchemy as sa

from signals.connectors.boamp import parse_tender_notice
from signals.connectors.simap import extract_tender as extract_simap_tender
from signals.connectors.ted import parse_tender_notice as parse_ted_tender_notice
from signals.documents.early_capture import capture_tender_notice
from signals.documents.fetch import FetchResult
from signals.persistence.schema import procedure_documents

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED = dt.datetime(2026, 9, 4, 8, tzinfo=dt.UTC)


def test_real_boamp_eforms_call_for_tenders_is_a_tender_notice() -> None:
    record = json.loads(
        (FIXTURES / "france" / "boamp_tender_notice.json").read_text(encoding="utf-8")
    )

    notice = parse_tender_notice(record, retrieved_at=RETRIEVED)

    assert notice.event.event_type == "tender_notice"
    assert notice.event.provenance.source_notice_id == "26-85090"
    assert notice.event.provenance.source_procedure_id == (
        "29a62cc4-71b7-4acd-bb4a-2f3755e09919"
    )
    assert notice.event.procedure_buyers[0].legal_name == (
        "Communauté de communes LE GRESIVAUDAN"
    )
    assert notice.title == "Prestations de transport de personnes en autocar avec chauffeur"
    assert notice.cpv_main == "60112000"
    assert notice.submission_deadline == dt.datetime(
        2026, 10, 2, 10, tzinfo=dt.UTC
    )
    assert notice.document_urls == (
        (
            "https://www.marches-publics.info/mpiaws/index.cfm?fuseaction=dematEnt.login"
            "&type=DCE&IDM=1866888"
        ),
    )


def test_capture_fetches_archives_and_stores_located_blocks_without_classifying() -> None:
    record = json.loads(
        (FIXTURES / "france" / "boamp_tender_notice.json").read_text(encoding="utf-8")
    )
    notice = parse_tender_notice(record, retrieved_at=RETRIEVED)
    content = b"Le titulaire doit assurer une permanence quotidienne."

    class Fetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def fetch(self, url: str) -> FetchResult:
            self.calls.append(url)
            return FetchResult(
                url=url,
                access_status="available",
                content=content,
                media_type="text/plain",
                byte_size=len(content),
                content_hash=hashlib.sha256(content).hexdigest(),
                retrieved_at=RETRIEVED,
            )

    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    procedure_documents.create(engine)
    fetcher = Fetcher()
    with engine.begin() as connection:
        result = capture_tender_notice(
            connection,
            notice,
            fetcher=fetcher,
            quota_bytes=10_000,
        )
        row = connection.execute(sa.select(procedure_documents)).one()

    assert result.documents_created == 1
    assert fetcher.calls == list(notice.document_urls)
    assert row.access_status == "available"
    assert row.archive_content == content
    assert row.blocks == [
        {
            "locator": "ligne 1",
            "text": "Le titulaire doit assurer une permanence quotidienne.",
            "method": "plain_text",
            "page": None,
        }
    ]


def test_real_ted_competition_notice_exposes_bt15_without_an_award() -> None:
    xml = (FIXTURES / "ted" / "612553-2026.tender.xml").read_bytes()

    notice = parse_ted_tender_notice(
        xml,
        publication_number="612553-2026",
        retrieved_at=RETRIEVED,
    )

    assert notice.event.event_type == "tender_notice"
    assert notice.event.provenance.source_notice_id == "612553-2026"
    assert notice.event.provenance.source_procedure_id == (
        "e938be39-0ade-4a92-b03a-82f844ffc565"
    )
    assert notice.event.procedure_buyers[0].legal_name == (
        "CENTRE NATIONAL D'ETUDES SPATIALES"
    )
    assert notice.title == "Assistance à maîtrise d’ouvrage sur le logiciel SAP"
    assert notice.cpv_main == "72261000"
    assert notice.document_urls == (
        "https://marches.cnes.fr/entreprise/consultation/510067?orgAcronyme=t5y",
    )


def test_real_simap_tender_records_auth_required_without_fetching() -> None:
    payload = json.loads(
        (FIXTURES / "simap" / "22917-01.tender.json").read_text(encoding="utf-8")
    )

    notice = extract_simap_tender(payload, retrieved_at=RETRIEVED)

    assert notice.event.event_type == "tender_notice"
    assert notice.event.provenance.source_notice_id == (
        "dcd4957b-e97b-471a-9a82-b95c02aa50d9"
    )
    assert notice.event.provenance.source_procedure_id == (
        "44c48094-2868-41c1-b154-6d15769dd355"
    )
    assert notice.title.startswith("Beschaffung einer Verwaltungssoftware")
    assert notice.cpv_main == "72268000"
    assert notice.submission_deadline == dt.datetime(
        2026, 3, 25, 17, tzinfo=dt.timezone(dt.timedelta(hours=1))
    )
    assert notice.document_access_status == "auth_required"
