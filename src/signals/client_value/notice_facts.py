"""Typed public-notice facts and bounded source archives, never API raw payloads."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import zlib
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

import sqlalchemy as sa
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from signals.persistence.notice_schema import notice_award_facts, notice_source_snapshot
from signals.persistence.schema import contract_award, source_event

MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024
MAX_SNAPSHOT_TTL_DAYS = 365


def _decimal_string(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError("a nonnegative exact decimal string is required")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("invalid decimal") from error
    if not number.is_finite() or number < 0 or len(value) > 128:
        raise ValueError("decimal is not finite, nonnegative and bounded")
    return value


DecimalString = Annotated[str, BeforeValidator(_decimal_string)]


class FactModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TextFact(FactModel):
    value: str = Field(min_length=1)
    source_path: str = Field(min_length=1)


class DateFact(FactModel):
    value: dt.date
    source_path: str = Field(min_length=1)


class DecimalFact(FactModel):
    value: DecimalString
    source_path: str = Field(min_length=1)
    source_notice_id: str | None = None
    source_url: str | None = None
    notice_kind: Literal["contract_award_notice", "contract_notice"] = "contract_award_notice"
    source_snapshot_key: str | None = None
    source_excerpt: str | None = Field(default=None, max_length=1024)


class MoneyFact(DecimalFact):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    currency_source_path: str


class DurationFact(DecimalFact):
    unit: Literal["DAY", "WEEK", "MONTH", "YEAR"]
    unit_source_path: str
    scope: Literal["contract", "works", "purchase_order"]
    period_kind: Literal["initial", "maximum", "unspecified"] = "unspecified"


class IdentifierFact(TextFact):
    scheme: str


class OrganizationFacts(FactModel):
    organization_ref: str
    identity_source_path: str
    name: TextFact
    identifiers: tuple[IdentifierFact, ...] = ()
    contact_name: TextFact | None = None
    email: TextFact | None = None
    phone: TextFact | None = None
    website: TextFact | None = None


class WinningPartyFacts(FactModel):
    party_ref: str
    source_path: str
    members: tuple[OrganizationFacts, ...] = Field(min_length=1)


class NoticeFactSource(FactModel):
    source_system: Literal["boamp"] = "boamp"
    source_notice_id: str
    notice_version: str | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_url: str | None = None
    collected_at: AwareDatetime
    extractor_version: str


class NoticeAwardFacts(FactModel):
    snapshot_key: str
    event_key: str
    award_key: str
    source: NoticeFactSource
    source_award_id: str
    lot_identifier: str
    result_source_path: str
    title: TextFact | None = None
    lot_title: TextFact | None = None
    lot_description: TextFact | None = None
    published_on: DateFact | None = None
    buyers: tuple[OrganizationFacts, ...] = ()
    winning_parties: tuple[WinningPartyFacts, ...] = Field(min_length=1)
    awarded_value: MoneyFact | None = None
    minimum_value: MoneyFact | None = None
    maximum_value: MoneyFact | None = None
    duration: DurationFact | None = None
    initial_duration: DurationFact | None = None
    maximum_duration: DurationFact | None = None
    maximum_renewals: DecimalFact | None = None
    coverage_gaps: tuple[str, ...] = ()
    related_notice_ids: tuple[str, ...] = ()
    related_notices_checked: bool = False
    notice_status: Literal["published", "notice_cancelled", "corrected"] = "published"
    notice_change_reason: TextFact | None = None


class NoticeFactRejection(FactModel):
    award_key: str
    reason: str


@dataclasses.dataclass(frozen=True)
class SnapshotPolicy:
    max_bytes: int = MAX_SNAPSHOT_BYTES
    ttl_days: int = MAX_SNAPSHOT_TTL_DAYS

    def __post_init__(self) -> None:
        if type(self.max_bytes) is not int or not 1 <= self.max_bytes <= MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot limit must be between 1 byte and 10 MiB")
        if type(self.ttl_days) is not int or not 1 <= self.ttl_days <= MAX_SNAPSHOT_TTL_DAYS:
            raise ValueError("snapshot TTL must be between 1 and 365 days")


DEFAULT_SNAPSHOT_POLICY = SnapshotPolicy()


@dataclasses.dataclass(frozen=True)
class NoticeSourceSnapshot:
    snapshot_key: str
    source_system: str
    source_notice_id: str
    notice_version: str | None
    source_url: str | None
    content_hash: str
    byte_size: int
    payload_compressed: bytes = dataclasses.field(repr=False)
    collected_at: dt.datetime
    expires_at: dt.datetime


@dataclasses.dataclass(frozen=True)
class NoticeFactsExtraction:
    snapshot: NoticeSourceSnapshot
    awards: tuple[NoticeAwardFacts, ...]
    rejections: tuple[NoticeFactRejection, ...] = ()
    related_snapshots: tuple[NoticeSourceSnapshot, ...] = ()


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware")
    return value.astimezone(dt.UTC)


def prepare_notice_snapshot(
    record: dict,
    *,
    source_notice_id: str,
    notice_version: str | None,
    source_url: str | None,
    collected_at: dt.datetime,
    policy: SnapshotPolicy = DEFAULT_SNAPSHOT_POLICY,
) -> NoticeSourceSnapshot:
    """Canonical JSON hash; collection time never changes the source identity."""
    collected_at = _aware(collected_at)
    if not source_notice_id or record.get("idweb") != source_notice_id:
        raise ValueError("snapshot notice identity must match the acquired record")
    content = bytearray()
    encoder = json.JSONEncoder(
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    for chunk in encoder.iterencode(record):
        encoded = chunk.encode("utf-8")
        if len(content) + len(encoded) > policy.max_bytes:
            raise ValueError("snapshot exceeds decompressed byte limit")
        content.extend(encoded)
    digest = hashlib.sha256(content).hexdigest()
    key = hashlib.sha256(
        json.dumps(
            ["boamp", source_notice_id, notice_version or "", digest], separators=(",", ":")
        ).encode()
    ).hexdigest()
    return NoticeSourceSnapshot(
        snapshot_key=key,
        source_system="boamp",
        source_notice_id=source_notice_id,
        notice_version=notice_version,
        source_url=source_url,
        content_hash=digest,
        byte_size=len(content),
        payload_compressed=zlib.compress(content),
        collected_at=collected_at,
        expires_at=collected_at + dt.timedelta(days=policy.ttl_days),
    )


def decode_notice_snapshot(
    snapshot: NoticeSourceSnapshot, *, policy: SnapshotPolicy = DEFAULT_SNAPSHOT_POLICY
) -> dict:
    """Bound zlib output before allocation; reject damaged or appended payloads."""
    if not 0 < snapshot.byte_size <= policy.max_bytes:
        raise ValueError("snapshot exceeds decompressed byte limit")
    if len(snapshot.payload_compressed) > MAX_SNAPSHOT_BYTES + 65536:
        raise ValueError("compressed snapshot exceeds byte limit")
    decoder = zlib.decompressobj()
    try:
        content = decoder.decompress(snapshot.payload_compressed, policy.max_bytes + 1)
    except zlib.error as error:
        raise ValueError("invalid snapshot compression") from error
    if len(content) > policy.max_bytes or decoder.unconsumed_tail:
        raise ValueError("snapshot exceeds decompressed byte limit")
    if not decoder.eof or decoder.unused_data or len(content) != snapshot.byte_size:
        raise ValueError("invalid snapshot size or compressed stream")
    if hashlib.sha256(content).hexdigest() != snapshot.content_hash:
        raise ValueError("snapshot content hash mismatch")
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise TypeError("snapshot must decode to an object")
    return payload


@dataclasses.dataclass(frozen=True)
class NoticeFactsStored:
    snapshot_key: str
    snapshot_created: bool
    facts_created: int
    related_snapshots_created: int = 0


def _holder_identifier_identity(scheme: str, value: str) -> tuple[str, str]:
    """Compare legacy BOAMP CompanyID spacing without merging establishments.

    The parser now labels fourteen-digit CompanyIDs as SIRET. Preserve every
    digit (including the NIC), unknown scheme, identifier and party grouping;
    this comparison does not rewrite the canonical award or its source.
    """
    if scheme.casefold() in {"siret", "boamp-company-id"}:
        compact = re.sub(r"\s+", "", value)
        if re.fullmatch(r"[0-9]{14}", compact):
            return "SIRET", compact
    return scheme, value


def _holder_identity(parties: tuple[WinningPartyFacts, ...]) -> list:
    return sorted(
        sorted(
            (
                member.name.value,
                tuple(
                    sorted(
                        _holder_identifier_identity(item.scheme, item.value)
                        for item in member.identifiers
                    )
                ),
            )
            for member in party.members
        )
        for party in parties
    )


def _stored_holder_identity(parties: list[dict]) -> list:
    return sorted(
        sorted(
            (
                member["organization"]["legal_name"],
                tuple(
                    sorted(
                        _holder_identifier_identity(item["scheme"], item["value"])
                        for item in member["organization"].get("identifiers", [])
                    )
                ),
            )
            for member in party["members"]
        )
        for party in parties
    )


def _insert_version(connection: sa.Connection, table: sa.Table, key: str, values: dict) -> bool:
    if connection.execute(sa.select(table.c[key]).where(table.c[key] == values[key])).first():
        return False
    try:
        with connection.begin_nested():
            connection.execute(table.insert().values(**values))
    except sa.exc.IntegrityError:
        if not connection.execute(
            sa.select(table.c[key]).where(table.c[key] == values[key])
        ).first():
            raise
        return False
    return True


def store_notice_facts(
    connection: sa.Connection, extraction: NoticeFactsExtraction
) -> NoticeFactsStored:
    """Persist within the caller's transaction, after canonical awards exist.

    Validate every attachment before writing any row. An expired archive is
    never silently refilled by a replay; versioned facts remain independently readable.
    """
    snapshot = extraction.snapshot
    if len(extraction.related_snapshots) > 3:
        raise ValueError("at most three related snapshots are supported")
    snapshots = {item.snapshot_key: item for item in (snapshot, *extraction.related_snapshots)}
    for archived in snapshots.values():
        _aware(archived.collected_at)
        _aware(archived.expires_at)
        if (
            not dt.timedelta(0)
            < archived.expires_at - archived.collected_at
            <= dt.timedelta(days=365)
        ):
            raise ValueError("snapshot retention exceeds 365 days")
        raw = decode_notice_snapshot(archived)
        expected = prepare_notice_snapshot(
            raw,
            source_notice_id=archived.source_notice_id,
            notice_version=archived.notice_version,
            source_url=archived.source_url,
            collected_at=archived.collected_at,
        )
        if expected.snapshot_key != archived.snapshot_key:
            raise ValueError("snapshot identity/hash alignment mismatch")
    for facts in extraction.awards:
        # Revalidate callers using model_copy, which intentionally bypasses Pydantic.
        NoticeAwardFacts.model_validate(facts.model_dump())
        for field in ("duration", "initial_duration", "maximum_duration", "maximum_renewals"):
            fact = getattr(facts, field)
            if fact is not None:
                origin = snapshots.get(fact.source_snapshot_key)
                if (
                    origin is None
                    or fact.source_notice_id != origin.source_notice_id
                    or fact.source_url != origin.source_url
                ):
                    raise ValueError("duration source provenance alignment mismatch")
        row = connection.execute(
            sa.select(
                contract_award.c.event_key,
                contract_award.c.source_award_id,
                contract_award.c.lot_identifier,
                contract_award.c.awardee_parties,
                source_event.c.source_system,
                source_event.c.source_notice_id,
                source_event.c.notice_version,
            )
            .join(source_event, source_event.c.event_key == contract_award.c.event_key)
            .where(contract_award.c.award_key == facts.award_key)
        ).first()
        if (
            row is None
            or row.event_key != facts.event_key
            or row.source_award_id != facts.source_award_id
            or row.lot_identifier != facts.lot_identifier
            or row.source_system != snapshot.source_system
            or row.source_notice_id != snapshot.source_notice_id
            or (row.notice_version is not None and row.notice_version != snapshot.notice_version)
            or facts.snapshot_key != snapshot.snapshot_key
            or facts.source.source_notice_id != snapshot.source_notice_id
            or facts.source.notice_version != snapshot.notice_version
            or facts.source.content_hash != snapshot.content_hash
            or facts.source.source_url != snapshot.source_url
            or facts.source.collected_at != snapshot.collected_at
            or _holder_identity(facts.winning_parties)
            != _stored_holder_identity(row.awardee_parties)
        ):
            raise ValueError("notice facts event/award/lot/holder/source alignment mismatch")
    created_snapshots = {}
    for archived in snapshots.values():
        values = dataclasses.asdict(archived)
        values.update(
            notice_version=archived.notice_version or "",
            payload_purged_at=None,
            created_at=archived.collected_at,
        )
        created_snapshots[archived.snapshot_key] = _insert_version(
            connection, notice_source_snapshot, "snapshot_key", values
        )
    count = 0
    source_set_hash = hashlib.sha256(
        json.dumps(sorted(snapshots), separators=(",", ":")).encode()
    ).hexdigest()
    inputs_observed_at = max(item.collected_at for item in snapshots.values())
    for facts in extraction.awards:
        key = hashlib.sha256(
            json.dumps(
                [
                    facts.snapshot_key,
                    facts.award_key,
                    facts.source.extractor_version,
                    source_set_hash,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        count += _insert_version(
            connection,
            notice_award_facts,
            "facts_key",
            {
                "facts_key": key,
                "snapshot_key": facts.snapshot_key,
                "event_key": facts.event_key,
                "award_key": facts.award_key,
                "extractor_version": facts.source.extractor_version,
                "source_set_hash": source_set_hash,
                "needs_related_enrichment": bool(
                    facts.duration is None
                    and facts.related_notice_ids
                    and not facts.related_notices_checked
                ),
                "facts": facts.model_dump(mode="json"),
                "collected_at": facts.source.collected_at,
                "created_at": inputs_observed_at,
            },
        )
    return NoticeFactsStored(
        snapshot.snapshot_key,
        created_snapshots[snapshot.snapshot_key],
        count,
        sum(created for key, created in created_snapshots.items() if key != snapshot.snapshot_key),
    )


def load_award_notice_facts(
    connection: sa.Connection, award_reference: str, *, extractor_version: str | None = None
) -> NoticeAwardFacts | None:
    """Select typed facts only. Raw archive bytes never enter the client projection."""
    query = sa.select(notice_award_facts.c.facts).where(
        notice_award_facts.c.award_key == award_reference
    )
    if extractor_version is not None:
        query = query.where(notice_award_facts.c.extractor_version == extractor_version)
    payload = connection.execute(
        query.order_by(
            notice_award_facts.c.collected_at.desc(),
            notice_award_facts.c.created_at.desc(),
            notice_award_facts.c.needs_related_enrichment.asc(),
            notice_award_facts.c.facts_key.desc(),
        ).limit(1)
    ).scalar_one_or_none()
    return NoticeAwardFacts.model_validate(payload) if payload else None


def purge_expired_notice_payloads(connection: sa.Connection, *, now: dt.datetime) -> int:
    """Erase expired source bytes while preserving provenance and all extracted facts."""
    now = _aware(now)
    result = connection.execute(
        notice_source_snapshot.update()
        .where(
            notice_source_snapshot.c.expires_at <= now,
            notice_source_snapshot.c.payload_compressed.is_not(None),
        )
        .values(payload_compressed=None, payload_purged_at=now)
    )
    return result.rowcount
