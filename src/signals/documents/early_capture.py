"""Stockage borné des dossiers capturés avant l'attribution."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import sqlalchemy as sa

from signals.documents.archive import expand
from signals.documents.extract import TextBlock, extract_text, sniff_media_type
from signals.documents.fetch import DocumentFetcher
from signals.documents.model import DocumentAccessStatus
from signals.domain import SourceSystem, TenderNotice
from signals.persistence.schema import procedure_documents

JoinStatus = Literal["unlinked", "linked", "review_required"]


class StorageQuotaReached(RuntimeError):
    """Le quota est atteint avant l'écriture ; le job peut s'arrêter proprement."""


@dataclass(frozen=True)
class ProcedureDocumentRecord:
    source_system: SourceSystem
    source_notice_id: str
    source_procedure_id: str | None
    buyer_fingerprint: str | None
    object_normalized: str | None
    cpv_main: str | None
    submission_deadline: dt.datetime | None
    source_url: str
    access_status: DocumentAccessStatus
    content: bytes | None
    content_hash: str | None
    media_type: str | None
    blocks: tuple[TextBlock, ...]
    captured_at: dt.datetime
    join_status: JoinStatus = "unlinked"
    linked_award_key: str | None = None


@dataclass(frozen=True)
class StoreResult:
    procedure_document_key: str
    created: bool


@dataclass(frozen=True)
class CaptureResult:
    documents_created: int = 0
    documents_seen: int = 0


def _plus_twelve_months(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    try:
        return value.replace(year=value.year + 1)
    except ValueError:  # 29 février
        return value.replace(year=value.year + 1, day=28)


def _key(record: ProcedureDocumentRecord) -> str:
    identity = json.dumps(
        [
            record.source_system,
            record.source_notice_id,
            record.source_url,
            record.content_hash,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()[:40]


def stored_bytes(connection: sa.Connection) -> int:
    value = connection.execute(
        sa.select(sa.func.coalesce(sa.func.sum(procedure_documents.c.byte_size), 0))
    ).scalar_one()
    return int(value)


def store_procedure_document(
    connection: sa.Connection,
    record: ProcedureDocumentRecord,
    *,
    quota_bytes: int,
) -> StoreResult:
    if quota_bytes < 0:
        raise ValueError("storage quota cannot be negative")
    key = _key(record)
    exists = connection.execute(
        sa.select(sa.literal(1)).where(
            procedure_documents.c.procedure_document_key == key
        )
    ).scalar()
    if exists:
        return StoreResult(key, False)
    size = len(record.content or b"")
    if stored_bytes(connection) + size > quota_bytes:
        raise StorageQuotaReached("procedure document storage quota reached")
    connection.execute(
        sa.insert(procedure_documents).values(
            procedure_document_key=key,
            source_system=record.source_system,
            source_notice_id=record.source_notice_id,
            source_procedure_id=record.source_procedure_id,
            buyer_fingerprint=record.buyer_fingerprint,
            object_normalized=record.object_normalized,
            cpv_main=record.cpv_main,
            submission_deadline=record.submission_deadline,
            source_url=record.source_url,
            host=(urlparse(record.source_url).hostname or "").casefold(),
            access_status=record.access_status,
            content_hash=record.content_hash,
            media_type=record.media_type,
            byte_size=size,
            archive_content=record.content,
            blocks=[dataclasses.asdict(block) for block in record.blocks],
            join_status=record.join_status,
            linked_award_key=record.linked_award_key,
            captured_at=record.captured_at,
            expires_at=_plus_twelve_months(record.submission_deadline),
            created_at=record.captured_at,
        )
    )
    return StoreResult(key, True)


def purge_expired_unlinked(connection: sa.Connection, *, now: dt.datetime) -> int:
    result = connection.execute(
        sa.delete(procedure_documents).where(
            procedure_documents.c.join_status == "unlinked",
            procedure_documents.c.expires_at.is_not(None),
            procedure_documents.c.expires_at <= now,
        )
    )
    return int(result.rowcount or 0)


def normalize_object(value: str | None) -> str | None:
    if not value:
        return None
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text)) or None


def buyer_fingerprint(notice: TenderNotice) -> str | None:
    if not notice.event.procedure_buyers:
        return None
    payload = [buyer.model_dump(mode="json") for buyer in notice.event.procedure_buyers]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:40]


def _blocks(content: bytes, *, name: str, media_type: str | None) -> tuple[TextBlock, ...]:
    if media_type == "text/plain":
        name = f"{name}.txt"
    if sniff_media_type(name, content) != "application/zip":
        return extract_text(content, name=name).blocks
    blocks: list[TextBlock] = []
    for entry in expand(content).accepted:
        if entry.content is None:
            continue
        extraction = extract_text(entry.content, name=entry.path)
        blocks.extend(
            dataclasses.replace(block, locator=f"{entry.path} — {block.locator}")
            for block in extraction.blocks
        )
    return tuple(blocks)


def capture_tender_notice(
    connection: sa.Connection,
    notice: TenderNotice,
    *,
    fetcher: DocumentFetcher,
    quota_bytes: int,
) -> CaptureResult:
    """Télécharge et extrait un AAPC, sans appeler aucun moteur de classification."""
    created = 0
    for url in notice.document_urls:
        fetched = None if notice.document_access_status else fetcher.fetch(url)
        access_status = notice.document_access_status or fetched.access_status  # type: ignore[union-attr]
        content = fetched.content if fetched is not None else None
        name = urlparse(url).path.rsplit("/", 1)[-1] or "document"
        blocks = (
            _blocks(
                content,
                name=name,
                media_type=fetched.media_type if fetched is not None else None,
            )
            if content is not None
            else ()
        )
        captured_at = (
            (fetched.retrieved_at if fetched is not None else None)
            or notice.event.provenance.retrieved_at
            or dt.datetime.now(dt.UTC)
        )
        stored = store_procedure_document(
            connection,
            ProcedureDocumentRecord(
                source_system=notice.event.provenance.source_system,
                source_notice_id=notice.event.provenance.source_notice_id,
                source_procedure_id=notice.event.provenance.source_procedure_id,
                buyer_fingerprint=buyer_fingerprint(notice),
                object_normalized=normalize_object(notice.title),
                cpv_main=notice.cpv_main,
                submission_deadline=notice.submission_deadline,
                source_url=url,
                access_status=access_status,
                content=content,
                content_hash=fetched.content_hash if fetched is not None else None,
                media_type=fetched.media_type if fetched is not None else None,
                blocks=blocks,
                captured_at=captured_at,
            ),
            quota_bytes=quota_bytes,
        )
        created += stored.created
    return CaptureResult(documents_created=created, documents_seen=len(notice.document_urls))
