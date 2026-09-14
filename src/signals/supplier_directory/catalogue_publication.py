"""Closed public-company snapshot; never serialize a database record wholesale."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, model_validator

from signals.client_value.directory import _clean_directors, published_email_evidence
from signals.companies.contracts import safe_https_url
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.store import SupplierDirectoryRecord

MAX_COMPANIES = 25_000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
PUBLIC_URLS = (
    "website_url",
    "contact_form_url",
    "domain_validation_evidence_url",
    "email_evidence_url",
)
PUBLIC_COLUMNS = frozenset(
    {
        "siren",
        "legal_name",
        "legal_name_observed_at",
        "naf_code",
        "naf_observed_at",
        "naf_label",
        "naf_label_observed_at",
        "family_keys",
        "family_review_keys",
        "family_source",
        "family_confidence",
        "family_confirmation_status",
        "families_observed_at",
        "department",
        "department_observed_at",
        "city",
        "city_observed_at",
        "employees",
        "employees_observed_at",
        "domain",
        "website_url",
        "domain_source",
        "domain_observed_at",
        "domain_validation_method",
        "domain_validation_evidence_url",
        "directors",
        "directors_observed_at",
        "director_display_name",
        "director_source",
        "director_observed_at",
        "professional_email",
        "email_source",
        "email_evidence_url",
        "email_observed_at",
        "phone",
        "phone_source",
        "phone_observed_at",
        "contact_form_url",
        "contact_form_observed_at",
        "enrichment_observed_at",
        "created_at",
        "updated_at",
    }
)


def aware(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _json_default(value: object) -> object:
    if isinstance(value, dt.datetime):
        return aware(value).isoformat()
    if isinstance(value, Decimal):
        return str(value.normalize())
    raise TypeError("unsupported catalogue value")


def _encoded(value: object) -> bytes:
    return json.dumps(
        value, default=_json_default, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(rows: tuple[dict[str, Any], ...], at: dt.datetime) -> str:
    return hashlib.sha256(_encoded({"rows": rows, "generated_at": at})).hexdigest()


def validated_record(row: Mapping[str, Any]) -> dict[str, Any]:
    if set(row) != PUBLIC_COLUMNS:
        raise ValueError("catalogue columns invalid")
    if len(_encoded(row)) > 32_768:
        raise ValueError("catalogue row too large")
    if not isinstance(row["legal_name"], str) or not 1 <= len(row["legal_name"]) <= 512:
        raise ValueError("catalogue identity invalid")
    values = dict(row)
    for key in PUBLIC_URLS:
        if values[key] is not None and not isinstance(values[key], str):
            raise ValueError("catalogue URL type invalid")
        safe_https_url(values[key])
    if not isinstance(values["directors"], list):
        raise ValueError("catalogue directors type invalid")  # noqa: TRY004 - Pydantic validation
    for director in values["directors"]:
        if (
            not isinstance(director, dict)
            or set(director) - {"name", "title"}
            or not all(isinstance(value, str) and len(value) <= 512 for value in director.values())
        ):
            raise ValueError("catalogue director fields invalid")
    if values["professional_email"] is not None:
        if values["email_source"] != "site" or published_email_evidence(values) is None:
            raise ValueError("catalogue email publication invalid")
    elif values["email_source"] is not None or values["email_evidence_url"] is not None:
        raise ValueError("catalogue email provenance without address")
    for key, value in row.items():
        if key.endswith("_at") and value is not None:
            parsed = dt.datetime.fromisoformat(value) if isinstance(value, str) else value
            if not isinstance(parsed, dt.datetime) or parsed.tzinfo is None:
                raise ValueError("catalogue timestamp invalid")
            values[key] = parsed
    record = SupplierDirectoryRecord.model_validate(values)
    return record.model_dump(mode="python", include=PUBLIC_COLUMNS)


class CatalogueSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = 1
    source: Literal["production"] = "production"
    complete: Literal[True] = True
    generated_at: dt.datetime
    total: int = Field(ge=0, le=MAX_COMPANIES)
    rows: tuple[dict[str, Any], ...] = Field(max_length=MAX_COMPANIES)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.generated_at.tzinfo is None or self.total != len(self.rows):
            raise ValueError("catalogue completeness invalid")
        if len(_encoded(self.model_dump())) > MAX_SNAPSHOT_BYTES:
            raise ValueError("catalogue snapshot too large")
        identities = set()
        for row in self.rows:
            validated_record(row)
            if row["siren"] in identities:
                raise ValueError("catalogue duplicate identity")
            identities.add(row["siren"])
        if _digest(self.rows, self.generated_at) != self.digest:
            raise ValueError("catalogue digest invalid")
        return self


def make_snapshot(rows: tuple[dict[str, Any], ...], *, now: dt.datetime) -> CatalogueSnapshot:
    normalized = tuple(json.loads(_encoded(row)) for row in rows)
    return CatalogueSnapshot(
        generated_at=aware(now),
        rows=normalized,
        total=len(normalized),
        digest=_digest(normalized, aware(now)),
    )


def build_snapshot(connection: sa.Connection, *, now: dt.datetime) -> CatalogueSnapshot:
    # Evidence is read inside the production boundary solely to decide publication.
    # It never enters the output, and no other table is read.
    records = connection.execute(
        sa.select(supplier_directory)
        .where(supplier_directory.c.suppressed_at.is_(None))
        .order_by(supplier_directory.c.siren)
        .limit(MAX_COMPANIES + 1)
    ).mappings()
    rows = []
    for record in records:
        if len(rows) == MAX_COMPANIES:
            raise ValueError("catalogue publication capacity exceeded")
        row = {key: record[key] for key in PUBLIC_COLUMNS}
        for key in PUBLIC_URLS:
            try:
                row[key] = safe_https_url(row[key])
            except ValueError:
                row[key] = None
        row["domain"] = urlsplit(row["website_url"]).hostname if row["website_url"] else None
        row["directors"] = _clean_directors(
            record["directors"], preferred_name=record["director_display_name"]
        )
        email = published_email_evidence(record)
        row.update(
            professional_email=email[0] if email else None,
            email_evidence_url=email[1] if email else None,
            email_source="site" if email else None,
            email_observed_at=record["email_observed_at"] if email else None,
        )
        rows.append(row)
    return make_snapshot(tuple(rows), now=now)
