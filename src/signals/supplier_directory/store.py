"""Purpose-limited persistence and 90-day freshness for supplier facts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

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
    naf_label: str | None = None
    naf_label_observed_at: dt.datetime | None = None
    family_keys: tuple[str, ...] = Field(default=())
    family_review_keys: tuple[str, ...] = Field(default=())
    family_source: Literal["model", "naf"] | None = None
    family_confidence: Decimal | None = None
    family_confirmation_status: Literal["confirmed", "unconfirmed"] | None = None
    families_observed_at: dt.datetime
    department: str | None = None
    department_observed_at: dt.datetime | None = None
    city: str | None = None
    city_observed_at: dt.datetime | None = None
    employees: int | None = None
    employees_observed_at: dt.datetime | None = None
    domain: str | None = None
    website_url: str | None = None
    website_title: str | None = None
    website_title_observed_at: dt.datetime | None = None
    domain_source: str | None = None
    domain_confidence: Decimal | None = None
    domain_validation_method: Literal["name_word", "registration_number", "model"] | None = None
    domain_validation_evidence_url: str | None = None
    domain_observed_at: dt.datetime | None = None
    apollo_organization_id: str | None = None
    apollo_status: Literal["resolved", "unresolved"] | None = None
    apollo_observed_at: dt.datetime | None = None
    directors: tuple[dict[str, object], ...] = Field(default=())
    directors_observed_at: dt.datetime | None = None
    director_display_name: str | None = None
    director_source: Literal["model"] | None = None
    director_observed_at: dt.datetime | None = None
    professional_email: str | None = None
    email_source: Literal["apollo", "site", "manual", "model"] | None = None
    email_confidence: Decimal | None = None
    email_verification_status: str | None = None
    email_contact_name: str | None = None
    email_contact_title: str | None = None
    email_evidence_url: str | None = None
    email_observed_at: dt.datetime | None = None
    contact_form_url: str | None = None
    contact_form_observed_at: dt.datetime | None = None
    phone: str | None = None
    phone_source: Literal["model"] | None = None
    phone_observed_at: dt.datetime | None = None
    enrichment_notes: str | None = None
    enrichment_model_id: str | None = None
    enrichment_call_id: str | None = None
    enrichment_cost_usd: Decimal | None = None
    enrichment_input_tokens: int | None = None
    enrichment_output_tokens: int | None = None
    enrichment_evidence: dict[str, object] | None = None
    enrichment_decision: dict[str, object] | None = None
    enrichment_observed_at: dt.datetime | None = None
    reverification_required_at: dt.datetime | None = None
    reverification_reason: str | None = None
    website_failure_count: int = 0
    website_next_retry_at: dt.datetime | None = None
    website_unreachable_at: dt.datetime | None = None
    website_search_queries_completed: int = 0
    website_search_results_examined: int = 0
    suppressed_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_validator("family_keys", "family_review_keys", mode="before")
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
        "naf_label_observed_at",
        "families_observed_at",
        "department_observed_at",
        "city_observed_at",
        "employees_observed_at",
        "domain_observed_at",
        "website_title_observed_at",
        "apollo_observed_at",
        "directors_observed_at",
        "director_observed_at",
        "email_observed_at",
        "contact_form_observed_at",
        "phone_observed_at",
        "enrichment_observed_at",
        "reverification_required_at",
        "website_next_retry_at",
        "website_unreachable_at",
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


def _reverification_values(*, reason: str, observed_at: dt.datetime) -> dict[str, object]:
    return {
        "domain": None,
        "website_url": None,
        "website_title": None,
        "website_title_observed_at": None,
        "domain_source": None,
        "domain_confidence": None,
        "domain_validation_method": None,
        "domain_validation_evidence_url": None,
        "domain_observed_at": None,
        "apollo_organization_id": None,
        "apollo_status": None,
        "apollo_observed_at": None,
        "professional_email": None,
        "email_source": None,
        "email_confidence": None,
        "email_verification_status": None,
        "email_contact_name": None,
        "email_contact_title": None,
        "email_evidence_url": None,
        "email_observed_at": None,
        "contact_form_url": None,
        "contact_form_observed_at": None,
        "reverification_required_at": observed_at,
        "reverification_reason": reason[:128],
        "updated_at": observed_at,
    }


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
        naf_label: str | None = None,
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
            existing_family_is_fresh = bool(
                current is not None
                and current["family_source"] in {"model", "naf"}
                and current["family_keys"]
                and _fresh(current["families_observed_at"], observed_at)
            )
            families = (
                tuple(current["family_keys"] or ())
                if existing_family_is_fresh
                else ((family_key,) if family_key else ())
            )
            values = {
                "legal_name": legal_name,
                "legal_name_observed_at": observed_at,
                "naf_code": naf_code,
                "naf_observed_at": observed_at if naf_code else None,
                "naf_label": naf_label,
                "naf_label_observed_at": observed_at if naf_label else None,
                "family_keys": list(families),
                "family_source": (
                    current["family_source"]
                    if existing_family_is_fresh
                    else ("naf" if family_key else None)
                ),
                "family_confidence": (
                    current["family_confidence"] if existing_family_is_fresh else None
                ),
                "family_confirmation_status": (
                    current["family_confirmation_status"]
                    if existing_family_is_fresh
                    else ("unconfirmed" if family_key else None)
                ),
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
        validation_method: Literal["name_word", "registration_number", "model"],
        validation_evidence_url: str | None,
        observed_at: dt.datetime,
        website_title: str | None = None,
    ) -> bool:
        _require_aware(observed_at)
        normalized_domain = domain.casefold()
        trusted_values = {
            "domain": domain,
            "website_url": website_url,
            "website_title": website_title,
            "website_title_observed_at": observed_at if website_title else None,
            "domain_source": source,
            "domain_validation_method": validation_method,
            "domain_validation_evidence_url": validation_evidence_url,
            "domain_observed_at": observed_at,
            "reverification_required_at": None,
            "reverification_reason": None,
            "website_failure_count": 0,
            "website_next_retry_at": None,
            "website_unreachable_at": None,
        }
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:domain))"),
                    {"domain": normalized_domain},
                )
            conflict = connection.scalar(
                sa.select(sa.literal(1))
                .where(
                    sa.func.lower(supplier_directory.c.domain) == normalized_domain,
                    supplier_directory.c.siren != siren,
                )
                .limit(1)
            )
            if conflict:
                untrusted_values = {
                    "domain_validation_method": None,
                    "domain_validation_evidence_url": None,
                    "apollo_organization_id": None,
                    "apollo_status": None,
                    "apollo_observed_at": None,
                    "professional_email": None,
                    "email_source": None,
                    "email_verification_status": None,
                    "email_contact_name": None,
                    "email_contact_title": None,
                    "email_evidence_url": None,
                    "email_observed_at": None,
                    "reverification_required_at": observed_at,
                    "reverification_reason": "shared_domain_blocklist",
                    "updated_at": observed_at,
                }
                connection.execute(
                    sa.update(supplier_directory)
                    .where(sa.func.lower(supplier_directory.c.domain) == normalized_domain)
                    .values(**untrusted_values)
                )
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == siren)
                    .values(
                        domain=domain,
                        website_url=website_url,
                        domain_source=source,
                        domain_observed_at=observed_at,
                        **untrusted_values,
                    )
                )
                return False
            result = connection.execute(
                sa.update(supplier_directory)
                .where(supplier_directory.c.siren == siren)
                .values(**trusted_values, updated_at=observed_at)
            )
        return result.rowcount == 1

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

    def mark_without_website(
        self,
        siren: str,
        *,
        search_queries_completed: int,
        search_results_examined: int,
        observed_at: dt.datetime,
    ) -> bool:
        if search_queries_completed < 3 or search_results_examined < 30:
            return False
        return self._update(
            siren,
            {
                "domain": None,
                "website_url": None,
                "domain_source": "no_website",
                "domain_validation_method": None,
                "domain_validation_evidence_url": None,
                "domain_observed_at": observed_at,
                "reverification_required_at": None,
                "reverification_reason": "no_website",
                "website_search_queries_completed": search_queries_completed,
                "website_search_results_examined": search_results_examined,
            },
            observed_at,
        )

    def permanently_without_website(self, siren: str) -> bool:
        record = self.get(siren)
        return bool(
            record is not None
            and record.domain is None
            and record.domain_source == "no_website"
            and record.reverification_reason == "no_website"
            and record.website_search_queries_completed >= 3
            and record.website_search_results_examined >= 30
        )

    def record_website_connection_failure(self, siren: str, *, observed_at: dt.datetime) -> bool:
        _require_aware(observed_at)
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(supplier_directory.c.website_failure_count)
                .where(supplier_directory.c.siren == siren)
                .with_for_update()
            ).one_or_none()
            if row is None:
                return False
            failures = min(3, int(row.website_failure_count or 0) + 1)
            return (
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == siren)
                    .values(
                        website_failure_count=failures,
                        website_next_retry_at=(
                            observed_at + dt.timedelta(days=1) if failures <= 2 else None
                        ),
                        website_unreachable_at=observed_at if failures >= 3 else None,
                        reverification_reason=(
                            "website_unreachable" if failures >= 3 else "website_retry_pending"
                        ),
                        updated_at=observed_at,
                    )
                ).rowcount
                == 1
            )

    def website_lookup_due(self, siren: str, *, at: dt.datetime) -> bool:
        record = self.get(siren)
        if record is None or record.website_unreachable_at is not None:
            return False
        retry_at = record.website_next_retry_at
        return retry_at is None or retry_at <= at

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
        source: Literal["apollo", "site", "manual", "model"],
        verification_status: str,
        contact_name: str,
        contact_title: str,
        evidence_url: str | None = None,
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
            "email_confidence": None,
            "email_verification_status": verification_status,
            "email_contact_name": contact_name,
            "email_contact_title": contact_title,
            "email_evidence_url": evidence_url,
            "email_observed_at": observed_at,
        }
        with self._engine.begin() as connection:
            matching_site_evidence = sa.false()
            if source == "site" and evidence_url:
                evidence_domain = (
                    (urlsplit(evidence_url).hostname or "").casefold().removeprefix("www.")
                )
                if evidence_domain:
                    matching_site_evidence = (
                        sa.func.lower(supplier_directory.c.domain) == evidence_domain
                    )
            trusted_address = sa.or_(
                sa.func.lower(supplier_directory.c.domain) == email_domain,
                source == "manual",
                source == "model",
                matching_site_evidence,
            )
            result = connection.execute(
                sa.update(supplier_directory)
                .where(
                    supplier_directory.c.siren == siren,
                    trusted_address,
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

    def mark_for_reverification(
        self,
        siren: str,
        *,
        reason: str,
        observed_at: dt.datetime,
        expected_domain: str | None = None,
        connection: sa.Connection | None = None,
    ) -> bool:
        _require_aware(observed_at)
        predicate = supplier_directory.c.siren == siren
        if expected_domain is not None:
            predicate = sa.and_(
                predicate,
                sa.func.lower(supplier_directory.c.domain) == expected_domain.casefold(),
                supplier_directory.c.domain_validation_method.is_not(None),
                supplier_directory.c.suppressed_at.is_(None),
            )
        statement = (
            sa.update(supplier_directory)
            .where(predicate)
            .values(**_reverification_values(reason=reason, observed_at=observed_at))
        )
        if connection is not None:
            return connection.execute(statement).rowcount == 1
        with self._engine.begin() as owned_connection:
            return owned_connection.execute(statement).rowcount == 1

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
            and record.domain
            and record.domain_validation_method
            and record.reverification_required_at is None
            and (
                record.professional_email.rsplit("@", 1)[-1].casefold() == record.domain.casefold()
                or record.email_source == "manual"
                or record.email_source == "model"
                or (
                    record.email_source == "site"
                    and record.email_evidence_url is not None
                    and (urlsplit(record.email_evidence_url).hostname or "")
                    .casefold()
                    .removeprefix("www.")
                    == record.domain.casefold()
                )
            )
            and _fresh(record.email_observed_at, at)
            else None
        )

    def record_model_enrichment(
        self,
        siren: str,
        *,
        website: str | None,
        website_confidence: Decimal | None,
        website_evidence_url: str | None,
        email: str | None,
        email_confidence: Decimal | None,
        email_evidence_url: str | None,
        family: str | None,
        family_confidence: Decimal | None,
        family_confirmed: bool,
        director_display_name: str | None,
        director_title: str,
        phone: str | None,
        directors: tuple[Mapping[str, object], ...],
        notes: str,
        call_id: str | None,
        model: str,
        cost_usd: Decimal,
        input_tokens: int,
        output_tokens: int,
        evidence: dict[str, object],
        decision: dict[str, object],
        reverification_reason: str | None,
        observed_at: dt.datetime,
    ) -> bool:
        """Replace every model-judged field in one atomic directory write."""

        _require_aware(observed_at)
        bounded_directors: list[dict[str, str]] = []
        for item in directors[:20]:
            if not item.get("name"):
                continue
            value = {
                "name": str(item["name"])[:256],
                "title": str(item.get("title") or "Dirigeant")[:256],
                "entity_type": str(item.get("entity_type") or "personne physique")[:32],
            }
            if item.get("first_name"):
                value["first_name"] = str(item["first_name"])[:128]
            bounded_directors.append(value)
        values: dict[str, object] = {
            "domain": website,
            "website_url": f"https://{website}" if website else None,
            "website_title": None,
            "website_title_observed_at": None,
            "domain_source": "model" if website else None,
            "domain_confidence": website_confidence,
            "domain_validation_method": "model" if website else None,
            "domain_validation_evidence_url": website_evidence_url,
            "domain_observed_at": observed_at,
            "apollo_organization_id": None,
            "apollo_status": None,
            "apollo_observed_at": None,
            "family_keys": [family] if family else [],
            "family_source": "model" if family_confirmed else ("naf" if family else None),
            "family_confidence": family_confidence,
            "family_confirmation_status": (
                "confirmed" if family_confirmed else ("unconfirmed" if family else None)
            ),
            "families_observed_at": observed_at,
            "directors": bounded_directors,
            "directors_observed_at": observed_at if bounded_directors else None,
            "director_display_name": director_display_name,
            "director_source": "model" if director_display_name else None,
            "director_observed_at": observed_at if director_display_name else None,
            "professional_email": email,
            "email_source": "model" if email else None,
            "email_confidence": email_confidence,
            "email_verification_status": "mx_verified" if email else None,
            "email_contact_name": (
                director_display_name or supplier_directory.c.legal_name if email else None
            ),
            "email_contact_title": director_title if email else None,
            "email_evidence_url": email_evidence_url,
            "email_observed_at": observed_at if email else None,
            "phone": phone,
            "phone_source": "model" if phone else None,
            "phone_observed_at": observed_at if phone else None,
            "enrichment_notes": notes[:2000],
            "enrichment_call_id": call_id,
            "enrichment_model_id": model,
            "enrichment_cost_usd": cost_usd,
            "enrichment_input_tokens": input_tokens,
            "enrichment_output_tokens": output_tokens,
            "enrichment_evidence": evidence,
            "enrichment_decision": decision,
            "enrichment_observed_at": observed_at,
            "reverification_required_at": observed_at if reverification_reason else None,
            "reverification_reason": reverification_reason,
            "website_failure_count": 0,
            "website_next_retry_at": None,
            "website_unreachable_at": None,
        }
        return self._update(siren, values, observed_at, skip_if_suppressed=True)

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
                    email_evidence_url=None,
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
