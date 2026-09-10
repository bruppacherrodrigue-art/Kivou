"""Purpose-limited persistence and 90-day freshness for supplier facts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Annotated, Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy.engine import Engine

from signals.persistence.schema import supplier_directory

FRESHNESS = dt.timedelta(days=90)


class SupplierDirectoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    siren: Annotated[str, StringConstraints(pattern=r"^\d{9}$")]
    legal_name: str
    legal_name_observed_at: dt.datetime
    naf_code: str | None = None
    naf_observed_at: dt.datetime | None = None
    family_keys: tuple[str, ...] = Field(default=())
    families_observed_at: dt.datetime
    department: str | None = None
    department_observed_at: dt.datetime | None = None
    city: str | None = None
    city_observed_at: dt.datetime | None = None
    employees: int | None = None
    employees_observed_at: dt.datetime | None = None
    domain: str | None = None
    website_url: str | None = None
    domain_source: str | None = None
    domain_validation_method: Literal["name_word", "registration_number"] | None = None
    domain_validation_evidence_url: str | None = None
    domain_observed_at: dt.datetime | None = None
    apollo_organization_id: str | None = None
    apollo_status: Literal["resolved", "unresolved"] | None = None
    apollo_observed_at: dt.datetime | None = None
    directors: tuple[dict[str, object], ...] = Field(default=())
    directors_observed_at: dt.datetime | None = None
    professional_email: str | None = None
    email_source: Literal["apollo", "site", "manual"] | None = None
    email_verification_status: str | None = None
    email_contact_name: str | None = None
    email_contact_title: str | None = None
    email_observed_at: dt.datetime | None = None
    contact_form_url: str | None = None
    contact_form_observed_at: dt.datetime | None = None
    reverification_required_at: dt.datetime | None = None
    reverification_reason: str | None = None
    suppressed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_validator("family_keys", mode="before")
    @classmethod
    def tuple_families(cls, value):
        return tuple(value or ())

    @field_validator("directors", mode="before")
    @classmethod
    def tuple_directors(cls, value):
        return tuple(value or ())

    @field_validator(
        "legal_name_observed_at",
        "naf_observed_at",
        "families_observed_at",
        "department_observed_at",
        "city_observed_at",
        "employees_observed_at",
        "domain_observed_at",
        "apollo_observed_at",
        "directors_observed_at",
        "email_observed_at",
        "contact_form_observed_at",
        "reverification_required_at",
        "suppressed_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value


def _record(row) -> SupplierDirectoryRecord:
    return SupplierDirectoryRecord.model_validate(dict(row))


def _require_aware(value: dt.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")


def _fresh(observed_at: dt.datetime | None, at: dt.datetime) -> bool:
    _require_aware(at)
    if observed_at is None:
        return False
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=dt.UTC)
    return at - observed_at <= FRESHNESS


class SupplierDirectoryStore:
    def __init__(self, engine: Engine, *, clock=lambda: dt.datetime.now(dt.UTC)) -> None:
        self._engine = engine
        self._clock = clock

    def get(self, siren: str) -> SupplierDirectoryRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _record(row)

    def upsert_identity(
        self,
        *,
        siren: str,
        legal_name: str,
        naf_code: str | None,
        family_key: str,
        department: str | None,
        city: str | None,
        employees: int | None,
        observed_at: dt.datetime,
    ) -> SupplierDirectoryRecord:
        _require_aware(observed_at)
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
                )
                .mappings()
                .one_or_none()
            )
            families = sorted(
                set((current["family_keys"] if current is not None else ()) or ()) | {family_key}
            )
            values = {
                "legal_name": legal_name,
                "legal_name_observed_at": observed_at,
                "naf_code": naf_code,
                "naf_observed_at": observed_at if naf_code else None,
                "family_keys": families,
                "families_observed_at": observed_at,
                "department": department,
                "department_observed_at": observed_at if department else None,
                "city": city,
                "city_observed_at": observed_at if city else None,
                "employees": employees,
                "employees_observed_at": observed_at if employees is not None else None,
                "updated_at": observed_at,
            }
            if current is None:
                connection.execute(
                    sa.insert(supplier_directory).values(
                        siren=siren,
                        directors=[],
                        created_at=observed_at,
                        **values,
                    )
                )
            else:
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == siren)
                    .values(**values)
                )
            row = (
                connection.execute(
                    sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
                )
                .mappings()
                .one()
            )
        return _record(row)

    def record_domain(
        self,
        siren: str,
        *,
        domain: str,
        website_url: str,
        source: str,
        validation_method: Literal["name_word", "registration_number"],
        validation_evidence_url: str | None,
        observed_at: dt.datetime,
    ) -> None:
        self._update(
            siren,
            {
                "domain": domain,
                "website_url": website_url,
                "domain_source": source,
                "domain_validation_method": validation_method,
                "domain_validation_evidence_url": validation_evidence_url,
                "domain_observed_at": observed_at,
                "reverification_required_at": None,
                "reverification_reason": None,
            },
            observed_at,
        )

    def record_apollo(
        self,
        siren: str,
        *,
        organization_id: str | None,
        status: Literal["resolved", "unresolved"],
        observed_at: dt.datetime,
    ) -> None:
        self._update(
            siren,
            {
                "apollo_organization_id": organization_id,
                "apollo_status": status,
                "apollo_observed_at": observed_at,
            },
            observed_at,
        )

    def record_directors(
        self,
        siren: str,
        *,
        directors: tuple[Mapping[str, object], ...],
        observed_at: dt.datetime,
    ) -> None:
        bounded = []
        for item in directors[:20]:
            value = {
                "name": str(item["name"])[:256],
                "title": str(item["title"])[:256],
                "entity_type": str(item.get("entity_type") or "personne physique")[:32],
            }
            if item.get("first_name"):
                value["first_name"] = str(item["first_name"])[:128]
            bounded.append(value)
        self._update(
            siren,
            {"directors": bounded, "directors_observed_at": observed_at},
            observed_at,
            skip_if_suppressed=True,
        )

    def record_email(
        self,
        siren: str,
        *,
        email: str,
        source: Literal["apollo", "site", "manual"],
        verification_status: str,
        contact_name: str,
        contact_title: str,
        observed_at: dt.datetime,
    ) -> bool:
        _require_aware(observed_at)
        normalized_email = email.casefold()
        if "@" not in normalized_email:
            return False
        email_domain = normalized_email.rsplit("@", 1)[1]
        values = {
            "professional_email": email.casefold(),
            "email_source": source,
            "email_verification_status": verification_status,
            "email_contact_name": contact_name,
            "email_contact_title": contact_title,
            "email_observed_at": observed_at,
        }
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(supplier_directory)
                .where(
                    supplier_directory.c.siren == siren,
                    sa.func.lower(supplier_directory.c.domain) == email_domain,
                    supplier_directory.c.domain_validation_method.is_not(None),
                    supplier_directory.c.reverification_required_at.is_(None),
                    supplier_directory.c.suppressed_at.is_(None),
                )
                .values(**values, updated_at=observed_at)
            )
        return result.rowcount == 1

    def record_contact_form(
        self,
        siren: str,
        *,
        url: str,
        observed_at: dt.datetime,
    ) -> bool:
        return self._update(
            siren,
            {
                "contact_form_url": url[:2048],
                "contact_form_observed_at": observed_at,
            },
            observed_at,
        )

    def fresh_domain(self, siren: str, *, at: dt.datetime) -> SupplierDirectoryRecord | None:
        record = self.get(siren)
        return (
            record
            if record is not None
            and record.domain
            and record.domain_validation_method
            and record.reverification_required_at is None
            and _fresh(record.domain_observed_at, at)
            else None
        )

    def mark_for_reverification(self, siren: str, *, reason: str, observed_at: dt.datetime) -> bool:
        return self._update(
            siren,
            {
                "domain": None,
                "website_url": None,
                "domain_source": None,
                "domain_validation_method": None,
                "domain_validation_evidence_url": None,
                "domain_observed_at": None,
                "apollo_organization_id": None,
                "apollo_status": None,
                "apollo_observed_at": None,
                "professional_email": None,
                "email_source": None,
                "email_verification_status": None,
                "email_contact_name": None,
                "email_contact_title": None,
                "email_observed_at": None,
                "contact_form_url": None,
                "contact_form_observed_at": None,
                "reverification_required_at": observed_at,
                "reverification_reason": reason[:128],
            },
            observed_at,
        )

    def fresh_apollo(self, siren: str, *, at: dt.datetime) -> SupplierDirectoryRecord | None:
        record = self.get(siren)
        return record if record is not None and _fresh(record.apollo_observed_at, at) else None

    def fresh_email(self, siren: str, *, at: dt.datetime) -> SupplierDirectoryRecord | None:
        record = self.get(siren)
        return (
            record
            if record is not None
            and record.suppressed_at is None
            and record.professional_email
            and _fresh(record.email_observed_at, at)
            else None
        )

    def fresh_directors(self, siren: str, *, at: dt.datetime) -> SupplierDirectoryRecord | None:
        record = self.get(siren)
        return (
            record
            if record is not None
            and record.suppressed_at is None
            and record.directors
            and _fresh(record.directors_observed_at, at)
            else None
        )

    def suppress_personal_data(self, siren: str, *, at: dt.datetime) -> str | None:
        _require_aware(at)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
                )
                .mappings()
                .one()
            )
            email = row["professional_email"]
            connection.execute(
                sa.update(supplier_directory)
                .where(supplier_directory.c.siren == siren)
                .values(
                    directors=[],
                    directors_observed_at=at,
                    professional_email=None,
                    email_source=None,
                    email_verification_status=None,
                    email_contact_name=None,
                    email_contact_title=None,
                    email_observed_at=at,
                    suppressed_at=at,
                    updated_at=at,
                )
            )
        return email

    def _update(
        self,
        siren: str,
        values: dict[str, object],
        observed_at: dt.datetime,
        *,
        skip_if_suppressed: bool = False,
    ) -> bool:
        _require_aware(observed_at)
        with self._engine.begin() as connection:
            predicate = supplier_directory.c.siren == siren
            if skip_if_suppressed:
                predicate = sa.and_(predicate, supplier_directory.c.suppressed_at.is_(None))
            result = connection.execute(
                sa.update(supplier_directory)
                .where(predicate)
                .values(**values, updated_at=observed_at)
            )
        return result.rowcount == 1


__all__ = ["FRESHNESS", "SupplierDirectoryRecord", "SupplierDirectoryStore"]
