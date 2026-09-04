"""Stockage borné des dossiers capturés avant l'attribution."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import sqlalchemy as sa

from signals.documents.archive import expand
from signals.documents.extract import TextBlock, extract_text, sniff_media_type
from signals.documents.fetch import DocumentFetcher
from signals.documents.model import DocumentAccessStatus
from signals.domain import ContractAward, PublicEvent, SourceSystem, TenderNotice
from signals.persistence.identity import award_key
from signals.persistence.schema import procedure_documents, source_event

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
    access_detail: str | None = None
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


@dataclass(frozen=True)
class AwardDocumentResolution:
    status: Literal["linked", "review_required", "unresolved"]
    match_mode: Literal["explicit_notice", "procedure_id", "fingerprint"] | None = None
    blocks: tuple[TextBlock, ...] = ()
    analysis: Any | None = None
    linked_award_key: str | None = None


@dataclass(frozen=True)
class HostCaptureMetric:
    host_group: str
    portal_url: str
    downloaded: int
    total: int
    blocked: int
    block_reasons: tuple[str, ...]
    average_folder_bytes: int
    classified_requirements_per_folder: float

    @property
    def download_rate(self) -> float:
        return self.downloaded / self.total if self.total else 0.0


@dataclass(frozen=True)
class EarlyCaptureReport:
    notices_ingested: int
    hosts: tuple[HostCaptureMetric, ...]
    average_folder_bytes: int
    estimated_award_coverage_at_three_months: float


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
        connection.execute(
            sa.update(procedure_documents)
            .where(procedure_documents.c.procedure_document_key == key)
            .values(
                access_status=record.access_status,
                access_detail=record.access_detail,
                captured_at=record.captured_at,
                expires_at=_plus_twelve_months(record.submission_deadline),
            )
        )
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
            access_detail=record.access_detail,
            classified_requirements_count=0,
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


def event_buyer_fingerprint(event: PublicEvent) -> str | None:
    if not event.procedure_buyers:
        return None
    payload = [buyer.model_dump(mode="json") for buyer in event.procedure_buyers]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:40]


def buyer_fingerprint(notice: TenderNotice) -> str | None:
    return event_buyer_fingerprint(notice.event)


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
                access_detail=(fetched.detail if fetched is not None else None),
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


def _stored_blocks(rows: list[sa.Row]) -> tuple[TextBlock, ...]:
    return tuple(TextBlock(**block) for row in rows for block in (row.blocks or []))


def _analyze_rows(
    rows: list[sa.Row], *, event: PublicEvent, award: ContractAward
) -> Any:
    from signals.documents.intelligence import analyze_dossier
    from signals.documents.model import TenderDocument

    items = []
    for row in rows:
        document = TenderDocument(
            source_system=row.source_system,
            source_procedure_id=row.source_procedure_id,
            source_notice_id=row.source_notice_id,
            name=urlparse(row.source_url).path.rsplit("/", 1)[-1] or "document",
            source_url=row.source_url,
            media_type=row.media_type,
            access_status=row.access_status,
            content_hash=row.content_hash,
            byte_size=row.byte_size,
            retrieved_at=row.captured_at,
        )
        items.append((document, row.archive_content))
    return analyze_dossier(
        award_ref=award.event_ref,
        source_system=event.provenance.source_system,
        tender_procedure_id=event.provenance.source_procedure_id,
        items=items,
    )


def resolve_award_documents(
    connection: sa.Connection,
    *,
    event: PublicEvent,
    award: ContractAward,
    buyer_identity: str | None = None,
    classify: Callable[[tuple[TextBlock, ...]], Any] | None = None,
) -> AwardDocumentResolution:
    """Joint dans l'ordre publié ; une empreinte faible reste entièrement quarantinée."""
    common = procedure_documents.c.source_system == event.provenance.source_system
    rows: list[sa.Row] = []
    mode: Literal["explicit_notice", "procedure_id", "fingerprint"] | None = None
    if event.source_notice_links:
        rows = connection.execute(
            sa.select(procedure_documents).where(
                common,
                procedure_documents.c.source_notice_id.in_(event.source_notice_links),
            )
        ).all()
        if rows:
            mode = "explicit_notice"
    if not rows and event.provenance.source_procedure_id:
        rows = connection.execute(
            sa.select(procedure_documents).where(
                common,
                procedure_documents.c.source_procedure_id
                == event.provenance.source_procedure_id,
            )
        ).all()
        if rows:
            mode = "procedure_id"
    if not rows:
        identity = buyer_identity or event_buyer_fingerprint(event)
        cpv = award.cpv_main.code if award.cpv_main else None
        normalized = normalize_object(award.title or award.description)
        if identity and normalized and cpv:
            rows = connection.execute(
                sa.select(procedure_documents).where(
                    common,
                    procedure_documents.c.buyer_fingerprint == identity,
                    procedure_documents.c.object_normalized == normalized,
                    procedure_documents.c.cpv_main == cpv,
                )
            ).all()
            if rows:
                mode = "fingerprint"
    if not rows or mode is None:
        return AwardDocumentResolution("unresolved")
    keys = [row.procedure_document_key for row in rows]
    reference = award_key(award)
    if mode == "fingerprint":
        connection.execute(
            sa.update(procedure_documents)
            .where(procedure_documents.c.procedure_document_key.in_(keys))
            .values(join_status="review_required", linked_award_key=reference)
        )
        return AwardDocumentResolution(
            "review_required", match_mode=mode, linked_award_key=reference
        )
    blocks = _stored_blocks(rows)
    analysis = classify(blocks) if classify is not None else _analyze_rows(
        rows, event=event, award=award
    )
    requirements_count = len(getattr(analysis, "requirements", ()))
    connection.execute(
        sa.update(procedure_documents)
        .where(procedure_documents.c.procedure_document_key.in_(keys))
        .values(
            join_status="linked",
            linked_award_key=reference,
            classified_requirements_count=requirements_count,
        )
    )
    return AwardDocumentResolution(
        "linked",
        match_mode=mode,
        blocks=blocks,
        analysis=analysis,
        linked_award_key=reference,
    )


def confirm_document_join(
    connection: sa.Connection, *, linked_award_key: str | None
) -> int:
    if not linked_award_key:
        return 0
    result = connection.execute(
        sa.update(procedure_documents)
        .where(
            procedure_documents.c.linked_award_key == linked_award_key,
            procedure_documents.c.join_status == "review_required",
        )
        .values(join_status="linked")
    )
    return int(result.rowcount or 0)


def capture_report(
    connection: sa.Connection,
    *,
    source: SourceSystem,
    since: dt.date,
    until: dt.date,
) -> EarlyCaptureReport:
    """Mesures reproductibles calculées depuis les lignes persistées."""
    notice_in_window = sa.exists(
        sa.select(1).where(
            source_event.c.source_system == procedure_documents.c.source_system,
            source_event.c.source_notice_id == procedure_documents.c.source_notice_id,
            source_event.c.event_type == "tender_notice",
            source_event.c.published_on >= since,
            source_event.c.published_on <= until,
        )
    )
    notices = int(
        connection.execute(
            sa.select(sa.func.count()).select_from(source_event).where(
                source_event.c.source_system == source,
                source_event.c.event_type == "tender_notice",
                source_event.c.published_on >= since,
                source_event.c.published_on <= until,
            )
        ).scalar_one()
    )
    report_columns = (
        procedure_documents.c.source_notice_id,
        procedure_documents.c.source_procedure_id,
        procedure_documents.c.source_url,
        procedure_documents.c.host,
        procedure_documents.c.access_status,
        procedure_documents.c.access_detail,
        procedure_documents.c.classified_requirements_count,
        procedure_documents.c.byte_size,
        procedure_documents.c.captured_at,
    )
    persisted_rows = connection.execute(
        sa.select(*report_columns).where(
            procedure_documents.c.source_system == source,
            notice_in_window,
        )
    ).mappings().all()
    latest_by_url: dict[tuple[str, str], sa.RowMapping] = {}
    for row in persisted_rows:
        key = (row["source_notice_id"], row["source_url"])
        previous = latest_by_url.get(key)
        if previous is None or row["captured_at"] > previous["captured_at"]:
            latest_by_url[key] = row
    persisted = tuple(latest_by_url.values())

    def display_host(host: str) -> str:
        aliases = (
            ("marches-publics.gouv.fr", "PLACE"),
            ("achatpublic", "achatpublic"),
            ("maximilien", "Maximilien"),
            ("marches-publics.info", "marches-publics.info"),
            ("marches-securises", "Marchés Sécurisés"),
            ("megalis.bretagne", "Mégalis Bretagne"),
            ("demat-ampa", "DEMAT AMPA"),
            ("xmarches", "XMarchés"),
        )
        return next((label for marker, label in aliases if marker in host), "Autres")

    grouped: dict[str, list[sa.RowMapping]] = {}
    for row in persisted:
        grouped.setdefault(display_host(row["host"]), []).append(row)
    preferred = {
        name: index
        for index, name in enumerate(
            (
                "PLACE",
                "achatpublic",
                "Maximilien",
                "marches-publics.info",
                "Marchés Sécurisés",
                "Mégalis Bretagne",
                "DEMAT AMPA",
                "XMarchés",
                "Autres",
            )
        )
    }
    metrics: list[HostCaptureMetric] = []
    for name, rows in grouped.items():
        folders: dict[str, dict[str, int]] = {}
        for row in rows:
            folder = row["source_procedure_id"] or row["source_notice_id"]
            values = folders.setdefault(folder, {"bytes": 0, "requirements": 0})
            values["bytes"] += int(row["byte_size"] or 0)
            values["requirements"] = max(
                values["requirements"],
                int(row["classified_requirements_count"] or 0),
            )
        host = rows[0]["host"]
        reasons = tuple(
            sorted(
                {
                    row["access_detail"]
                    for row in rows
                    if row["access_detail"]
                    and row["access_status"] in {"portal_blocked", "cgu_restricted"}
                }
            )
        )
        non_empty_folder_sizes = tuple(
            values["bytes"] for values in folders.values() if values["bytes"] > 0
        )
        metrics.append(
            HostCaptureMetric(
                host_group=name,
                portal_url=f"https://{host}",
                downloaded=sum(row["access_status"] == "available" for row in rows),
                total=len(rows),
                blocked=sum(
                    row["access_status"] in {"portal_blocked", "cgu_restricted"}
                    for row in rows
                ),
                block_reasons=reasons,
                average_folder_bytes=(
                    round(sum(non_empty_folder_sizes) / len(non_empty_folder_sizes))
                    if non_empty_folder_sizes
                    else 0
                ),
                classified_requirements_per_folder=(
                    sum(item["requirements"] for item in folders.values()) / len(folders)
                ),
            )
        )
    hosts = tuple(
        sorted(metrics, key=lambda row: (preferred.get(row.host_group, 99), row.host_group))
    )
    folder_sizes: dict[str, int] = {}
    available_notices: set[str] = set()
    for row in persisted:
        folder = row["source_procedure_id"] or row["source_notice_id"]
        folder_sizes[folder] = folder_sizes.get(folder, 0) + int(row["byte_size"] or 0)
        if row["access_status"] == "available":
            available_notices.add(row["source_notice_id"])
    non_empty_sizes = tuple(size for size in folder_sizes.values() if size > 0)
    average = sum(non_empty_sizes) / len(non_empty_sizes) if non_empty_sizes else 0
    return EarlyCaptureReport(
        notices_ingested=notices,
        hosts=hosts,
        average_folder_bytes=round(float(average or 0)),
        estimated_award_coverage_at_three_months=(
            len(available_notices) / notices if notices else 0.0
        ),
    )
