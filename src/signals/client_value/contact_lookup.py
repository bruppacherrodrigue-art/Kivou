"""Account-scoped, on-demand decision-maker lookup for the client app."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.companies.contracts import CompanyDecisionMaker, safe_https_url
from signals.companies.schema import (
    company_contact_lookup,
    company_contact_lookup_attempt,
)
from signals.company_research.contracts import CompanyResearchProviderError
from signals.company_research.profile import build_company_research_profile
from signals.company_research.provider import CompanyResearchProvider
from signals.contact_discovery.contracts import (
    ApolloContactProviderError,
    ContactObservation,
)
from signals.contact_discovery.profile import build_decision_maker_profile
from signals.contact_discovery.provider import ContactDiscoveryProvider
from signals.contact_discovery.ranking import classify_title, rank_candidates
from signals.persistence.schema import supplier_directory

PLAN_MONTHLY_QUOTAS: dict[str, int] = {
    "discovery": 0,
    "essential": 20,
    "pro": 100,
}
REFRESH_AFTER = dt.timedelta(days=90)
RUN_LEASE = dt.timedelta(minutes=5)
PLANNED_MAX_CREDITS = 4
_SIREN = re.compile(r"^\d{9}$")


class ContactLookupQuotaExceeded(RuntimeError):
    pass


class ContactLookupProviderFailure(RuntimeError):
    pass


class ContactLookupSuppressed(RuntimeError):
    pass


class ContactLookupIdentityUnavailable(RuntimeError):
    pass


class _ContactLookupLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class CompanyLookupIdentity:
    company_key: str
    siren: str | None
    name: str
    city: str | None
    website_url: str | None


@dataclass(frozen=True)
class _Reservation:
    attempt_id: str | None
    row: Any | None
    directory: Any


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("lookup time must be timezone-aware")
    return value


def _database_time(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _safe_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return safe_https_url(value)
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _lookup_id(account_id: str, company_key: str) -> str:
    return hashlib.sha256(f"company-contact\0{account_id}\0{company_key}".encode()).hexdigest()


def _month_floor(now: dt.datetime) -> dt.datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(now: dt.datetime) -> dt.datetime:
    if now.month == 12:
        return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


class CompanyContactLookupService:
    """Reserve quota, call the bounded Apollo chain, and persist safe output."""

    def __init__(
        self,
        engine: Engine,
        *,
        company_research: CompanyResearchProvider,
        contact_discovery: ContactDiscoveryProvider,
    ) -> None:
        self._engine = engine
        self._company_research = company_research
        self._contact_discovery = contact_discovery

    def view(
        self,
        *,
        account_id: str,
        company_key: str,
        plan_code: str,
        now: dt.datetime,
        siren: str | None = None,
    ) -> dict[str, Any] | None:
        now = _aware(now)
        with self._engine.begin() as connection:
            directory = None
            if siren is not None and _SIREN.fullmatch(siren):
                directory = self._directory_row(connection, siren=siren)
                if directory is not None and directory["suppressed_at"] is not None:
                    self._purge_cache(connection, siren=siren)
                    return None
            row = self._row(connection, account_id=account_id, company_key=company_key)
            if row is not None and not self._row_matches_directory(row, directory):
                self._purge_company_cache(
                    connection,
                    row=row,
                    now=now,
                )
                row = None
            used = self._used_this_month(connection, account_id=account_id, now=now)
        return self._render(
            row,
            plan_code=plan_code,
            quota=self._quota(plan_code),
            used=used,
            now=now,
            identity_available=self._directory_is_actionable(directory),
        )

    def research(
        self,
        *,
        account_id: str,
        plan_code: str,
        identity: CompanyLookupIdentity,
        now: dt.datetime,
    ) -> dict[str, Any]:
        now = _aware(now)
        quota = self._quota(plan_code)
        if quota == 0:
            raise ContactLookupQuotaExceeded(plan_code)

        reservation = self._reserve(
            account_id=account_id,
            identity=identity,
            quota=quota,
            now=now,
        )
        if reservation.attempt_id is None:
            with self._engine.connect() as connection:
                used = self._used_this_month(connection, account_id=account_id, now=now)
            return self._render(
                reservation.row,
                plan_code=plan_code,
                quota=quota,
                used=used,
                now=now,
            )

        attempt_id = reservation.attempt_id
        try:
            organization_profile = self._company_profile(identity, reservation.directory)
            self._record_request(
                attempt_id=attempt_id,
                account_id=account_id,
                company_key=identity.company_key,
                provider_organization_id=reservation.directory["apollo_organization_id"],
                counter="organization_enrichment_requests",
                credits=1,
            )
            organization = self._company_research.fetch_organization(organization_profile)
            if (
                organization.provider != "apollo"
                or organization.provider_organization_id
                != reservation.directory["apollo_organization_id"]
            ):
                raise CompanyResearchProviderError("provider_identity_mismatch")
            organization_view = self._organization_view(organization)

            contact_profile = build_decision_maker_profile(
                acquisition_opportunity_id=f"client-company:{identity.company_key}",
                supplier_ref=f"client-company:{identity.company_key}",
                provider_organization_id=organization.provider_organization_id,
                supplier_siren=identity.siren,
                binding_resolution_method=organization.resolution_method,
                organization_name=organization.provider_company_name,
                organization_city=_optional_text(reservation.directory["city"]),
                organization_domain=organization.provider_primary_domain,
            )
            self._record_request(
                attempt_id=attempt_id,
                account_id=account_id,
                company_key=identity.company_key,
                provider_organization_id=reservation.directory[
                    "apollo_organization_id"
                ],
                counter="people_search_requests",
                credits=0,
            )
            page = self._contact_discovery.search_people(contact_profile, observed_at=now)
            ranked = rank_candidates(
                tuple(candidate for candidate in page.candidates if candidate.has_email)
            )
            contacts: list[dict[str, str]] = []
            for candidate in ranked[:3]:
                self._record_request(
                    attempt_id=attempt_id,
                    account_id=account_id,
                    company_key=identity.company_key,
                    provider_organization_id=reservation.directory[
                        "apollo_organization_id"
                    ],
                    counter="people_match_requests",
                    credits=1,
                )
                person = self._contact_discovery.enrich_person(
                    candidate.candidate.provider_person_id,
                    observed_at=now,
                )
                contact = self._contact_view(
                    person,
                    expected_person_id=candidate.candidate.provider_person_id,
                    expected_organization_id=organization.provider_organization_id,
                    candidate=candidate,
                    supplier_ref=f"client-company:{identity.company_key}",
                    role_profile_version=contact_profile.profile_version,
                )
                if contact is not None:
                    contacts.append(contact)
        except _ContactLookupLeaseLost as error:
            raise ContactLookupProviderFailure("lookup_superseded") from error
        except (CompanyResearchProviderError, ApolloContactProviderError) as error:
            try:
                self._finish_failure(
                    attempt_id=attempt_id,
                    account_id=account_id,
                    company_key=identity.company_key,
                    provider_organization_id=reservation.directory[
                        "apollo_organization_id"
                    ],
                    now=now,
                    error_code=error.category,
                )
            except _ContactLookupLeaseLost as lease_error:
                raise ContactLookupProviderFailure("lookup_superseded") from lease_error
            raise ContactLookupProviderFailure(error.category) from error

        try:
            self._finish_success(
                attempt_id=attempt_id,
                account_id=account_id,
                company_key=identity.company_key,
                provider_organization_id=reservation.directory[
                    "apollo_organization_id"
                ],
                now=now,
                organization=organization_view,
                contacts=contacts,
            )
        except _ContactLookupLeaseLost as error:
            raise ContactLookupProviderFailure("lookup_superseded") from error
        result = self.view(
            account_id=account_id,
            company_key=identity.company_key,
            plan_code=plan_code,
            now=now,
            siren=identity.siren,
        )
        if result is None:
            raise ContactLookupSuppressed(identity.siren)
        return result

    @staticmethod
    def _quota(plan_code: str) -> int:
        return PLAN_MONTHLY_QUOTAS.get(plan_code, 0)

    @staticmethod
    def _row(connection, *, account_id: str, company_key: str):
        return (
            connection.execute(
                sa.select(company_contact_lookup).where(
                    company_contact_lookup.c.account_id == account_id,
                    company_contact_lookup.c.company_key == company_key,
                )
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _directory_row(connection, *, siren: str, for_update: bool = False):
        statement = sa.select(
            supplier_directory.c.siren,
            supplier_directory.c.city,
            supplier_directory.c.apollo_organization_id,
            supplier_directory.c.apollo_status,
            supplier_directory.c.suppressed_at,
        ).where(supplier_directory.c.siren == siren)
        if for_update:
            statement = statement.with_for_update()
        return (
            connection.execute(statement)
            .mappings()
            .first()
        )

    @staticmethod
    def _used_this_month(connection, *, account_id: str, now: dt.datetime) -> int:
        return int(
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(company_contact_lookup_attempt)
                .where(
                    company_contact_lookup_attempt.c.account_id == account_id,
                    company_contact_lookup_attempt.c.requested_at >= _month_floor(now),
                    company_contact_lookup_attempt.c.requested_at < _next_month(now),
                )
            )
            or 0
        )

    @staticmethod
    def _purge_cache(connection, *, siren: str) -> None:
        connection.execute(
            sa.delete(company_contact_lookup).where(
                company_contact_lookup.c.directory_siren == siren
            )
        )

    @staticmethod
    def _purge_company_cache(connection, *, row, now: dt.datetime) -> None:
        if row["status"] == "running" and row["lease_id"]:
            connection.execute(
                sa.update(company_contact_lookup_attempt)
                .where(
                    company_contact_lookup_attempt.c.attempt_id == row["lease_id"],
                    company_contact_lookup_attempt.c.status == "running",
                )
                .values(
                    status="expired",
                    completed_at=now,
                    error_code="directory_identity_changed",
                )
            )
        connection.execute(
            sa.delete(company_contact_lookup).where(
                company_contact_lookup.c.lookup_id == row["lookup_id"],
            )
        )

    @staticmethod
    def _row_matches_directory(row, directory) -> bool:
        if directory is None or directory["suppressed_at"] is not None:
            return False
        return bool(
            row["directory_siren"] == directory["siren"]
            and row["provider_organization_id"]
            == directory["apollo_organization_id"]
            and directory["apollo_status"] == "resolved"
        )

    def _verified_directory(self, connection, *, identity: CompanyLookupIdentity):
        if identity.siren is None or _SIREN.fullmatch(identity.siren) is None:
            raise ContactLookupIdentityUnavailable(identity.company_key)
        directory = self._directory_row(connection, siren=identity.siren, for_update=True)
        if directory is None:
            raise ContactLookupIdentityUnavailable(identity.siren)
        if directory["suppressed_at"] is not None:
            self._purge_cache(connection, siren=identity.siren)
            raise ContactLookupSuppressed(identity.siren)
        if not self._directory_is_actionable(directory):
            raise ContactLookupIdentityUnavailable(identity.siren)
        return directory

    @staticmethod
    def _directory_is_actionable(directory) -> bool:
        if directory is None:
            return False
        return bool(
            _optional_text(directory["apollo_organization_id"])
            and directory["apollo_status"] == "resolved"
        )

    def _reserve(
        self,
        *,
        account_id: str,
        identity: CompanyLookupIdentity,
        quota: int,
        now: dt.datetime,
    ) -> _Reservation:
        with self._engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"contact-quota:{account_id}:{_month_floor(now).date()}"},
                )
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                    {"key": f"contact-company:{account_id}:{identity.company_key}"},
                )
            # Hold the directory row through the cache reservation. A concurrent
            # suppression then runs strictly before or strictly after this
            # transaction; in the latter case its trigger purges the reservation
            # before the first following provider step can be recorded.
            directory = self._verified_directory(connection, identity=identity)
            row = self._row(
                connection,
                account_id=account_id,
                company_key=identity.company_key,
            )
            if row is not None and not self._row_matches_directory(row, directory):
                self._purge_company_cache(
                    connection,
                    row=row,
                    now=now,
                )
                row = None
            if row is not None:
                refresh_after = _database_time(row["refresh_after"])
                lease_expires_at = _database_time(row["lease_expires_at"])
                if row["status"] in {"ready", "no_contact"} and (
                    refresh_after is None or now < refresh_after
                ):
                    return _Reservation(None, row, directory)
                if (
                    row["status"] == "running"
                    and lease_expires_at is not None
                    and now < lease_expires_at
                ):
                    return _Reservation(None, row, directory)
                if row["status"] == "running" and row["lease_id"]:
                    connection.execute(
                        sa.update(company_contact_lookup_attempt)
                        .where(
                            company_contact_lookup_attempt.c.attempt_id == row["lease_id"],
                            company_contact_lookup_attempt.c.status == "running",
                        )
                        .values(
                            status="expired",
                            completed_at=now,
                            error_code="lease_expired",
                        )
                    )

            used = self._used_this_month(connection, account_id=account_id, now=now)
            if used >= quota:
                raise ContactLookupQuotaExceeded(str(quota))

            attempt_id = uuid.uuid4().hex
            lease_expires_at = now + RUN_LEASE
            connection.execute(
                sa.insert(company_contact_lookup_attempt).values(
                    attempt_id=attempt_id,
                    account_id=account_id,
                    company_key=identity.company_key,
                    directory_siren=directory["siren"],
                    provider_organization_id=directory["apollo_organization_id"],
                    status="running",
                    requested_at=now,
                    completed_at=None,
                    lease_expires_at=lease_expires_at,
                    organization_enrichment_requests=0,
                    people_search_requests=0,
                    people_match_requests=0,
                    planned_credit_units=PLANNED_MAX_CREDITS,
                    attempted_credit_units=0,
                    observed_credit_units=None,
                    error_code=None,
                )
            )
            values = {
                "directory_siren": directory["siren"],
                "provider_organization_id": directory["apollo_organization_id"],
                "status": "running",
                "organization": None,
                "contacts": [],
                "requested_at": now,
                "researched_at": None,
                "refresh_after": None,
                "lease_id": attempt_id,
                "lease_expires_at": lease_expires_at,
                "error_code": None,
                "updated_at": now,
            }
            if row is None:
                connection.execute(
                    sa.insert(company_contact_lookup).values(
                        lookup_id=_lookup_id(account_id, identity.company_key),
                        account_id=account_id,
                        company_key=identity.company_key,
                        created_at=now,
                        **values,
                    )
                )
            else:
                connection.execute(
                    sa.update(company_contact_lookup)
                    .where(company_contact_lookup.c.lookup_id == row["lookup_id"])
                    .values(**values)
                )
            return _Reservation(attempt_id, None, directory)

    def _record_request(
        self,
        *,
        attempt_id: str,
        account_id: str,
        company_key: str,
        provider_organization_id: str,
        counter: str,
        credits: int,
    ) -> None:
        if counter not in {
            "organization_enrichment_requests",
            "people_search_requests",
            "people_match_requests",
        }:
            raise ValueError("unknown contact lookup counter")
        counter_column = company_contact_lookup_attempt.c[counter]
        valid_lease = sa.exists(
            sa.select(1).where(
                company_contact_lookup.c.account_id == account_id,
                company_contact_lookup.c.company_key == company_key,
                company_contact_lookup.c.lease_id == attempt_id,
                company_contact_lookup.c.status == "running",
                company_contact_lookup.c.provider_organization_id
                == provider_organization_id,
                sa.exists(
                    sa.select(1).where(
                        supplier_directory.c.siren
                        == company_contact_lookup.c.directory_siren,
                        supplier_directory.c.apollo_organization_id
                        == provider_organization_id,
                        supplier_directory.c.apollo_status == "resolved",
                        supplier_directory.c.suppressed_at.is_(None),
                    )
                ),
            )
        )
        with self._engine.begin() as connection:
            updated = connection.execute(
                sa.update(company_contact_lookup_attempt)
                .where(
                    company_contact_lookup_attempt.c.attempt_id == attempt_id,
                    company_contact_lookup_attempt.c.status == "running",
                    valid_lease,
                )
                .values(
                    {
                        counter_column: counter_column + 1,
                        company_contact_lookup_attempt.c.attempted_credit_units: (
                            company_contact_lookup_attempt.c.attempted_credit_units + credits
                        ),
                    }
                )
            )
            if updated.rowcount != 1:
                raise _ContactLookupLeaseLost(attempt_id)

    def _company_profile(self, identity: CompanyLookupIdentity, directory):
        apollo_id = _optional_text(directory["apollo_organization_id"])
        if apollo_id is None:  # guarded transactionally by `_verified_directory`
            raise ContactLookupIdentityUnavailable(identity.company_key)
        return build_company_research_profile(
            apollo_id,
            # Leaving SIREN off keeps the merged exact-ID adapter's own
            # provider-ID mismatch guard enabled. Our durable rows remain
            # bound to the directory SIREN.
            siren=None,
            organization_name=None,
            organization_city=None,
            organization_domain=None,
        )

    @staticmethod
    def _organization_view(observation) -> dict[str, Any]:
        values = {
            "employees": observation.provider_employee_count,
            "website_url": _safe_url(observation.provider_website_url),
            "phone": _optional_text(getattr(observation, "provider_phone", None)),
            "linkedin_url": _safe_url(getattr(observation, "provider_linkedin_url", None)),
        }
        return {key: value for key, value in values.items() if value is not None}

    @staticmethod
    def _contact_view(
        person,
        *,
        expected_person_id: str,
        expected_organization_id: str,
        candidate,
        supplier_ref: str,
        role_profile_version: str,
    ) -> dict[str, str] | None:
        if person is None or (
            person.provider_person_id != expected_person_id
            or person.provider_organization_id != expected_organization_id
        ):
            return None
        name = _optional_text(person.display_name) or " ".join(
            value
            for value in (
                _optional_text(person.first_name),
                _optional_text(person.last_name),
            )
            if value
        )
        enriched_title = _optional_text(person.title)
        classification = classify_title(enriched_title) if enriched_title else None
        if enriched_title and classification is None:
            return None
        title = enriched_title or candidate.candidate.title
        classification = classification or candidate
        if not name or not title:
            return None
        try:
            contact = ContactObservation(
                supplier_ref=supplier_ref,
                provider_person_id=person.provider_person_id,
                provider_organization_id=person.provider_organization_id,
                first_name=person.first_name,
                last_name=person.last_name,
                display_name=person.display_name,
                title=title,
                normalized_title=classification.normalized_title,
                role_profile_version=role_profile_version,
                role_tier=classification.role_tier,
                business_email=person.business_email,
                provider_email_status=person.provider_email_status,
                provider_observed_at=person.provider_observed_at,
                email_observed_at=person.provider_observed_at,
                source_fingerprint=person.source_fingerprint,
            )
            browser_contact = CompanyDecisionMaker(
                name=name,
                title=title,
                email=contact.business_email,
                email_status="verified",
            )
        except ValidationError:
            return None
        result = browser_contact.model_dump(mode="json", exclude_none=True)
        linkedin = _safe_url(getattr(person, "linkedin_url", None))
        if linkedin is not None:
            result["linkedin_url"] = linkedin
        return result

    def _finish_success(
        self,
        *,
        attempt_id: str,
        account_id: str,
        company_key: str,
        provider_organization_id: str,
        now: dt.datetime,
        organization: dict[str, Any],
        contacts: list[dict[str, str]],
    ) -> None:
        self._finish(
            attempt_id=attempt_id,
            account_id=account_id,
            company_key=company_key,
            provider_organization_id=provider_organization_id,
            cache_values={
                "status": "ready" if contacts else "no_contact",
                "organization": organization or None,
                "contacts": contacts,
                "researched_at": now,
                "refresh_after": now + REFRESH_AFTER,
                "error_code": None,
            },
            attempt_status="success" if contacts else "no_contact",
            now=now,
        )

    def _finish_failure(
        self,
        *,
        attempt_id: str,
        account_id: str,
        company_key: str,
        provider_organization_id: str,
        now: dt.datetime,
        error_code: str,
    ) -> None:
        self._finish(
            attempt_id=attempt_id,
            account_id=account_id,
            company_key=company_key,
            provider_organization_id=provider_organization_id,
            cache_values={"status": "failed", "error_code": error_code},
            attempt_status="failed",
            now=now,
        )

    def _finish(
        self,
        *,
        attempt_id: str,
        account_id: str,
        company_key: str,
        provider_organization_id: str,
        cache_values: dict[str, Any],
        attempt_status: str,
        now: dt.datetime,
    ) -> None:
        with self._engine.begin() as connection:
            # The directory-change trigger terminalizes the attempt before it
            # deletes the cache. Keep the same attempt -> cache lock order here
            # so concurrent rebinding cannot deadlock PostgreSQL.
            updated_attempt = connection.execute(
                sa.update(company_contact_lookup_attempt)
                .where(
                    company_contact_lookup_attempt.c.attempt_id == attempt_id,
                    company_contact_lookup_attempt.c.status == "running",
                )
                .values(
                    status=attempt_status,
                    completed_at=now,
                    error_code=cache_values.get("error_code"),
                )
            )
            if updated_attempt.rowcount != 1:
                raise _ContactLookupLeaseLost(attempt_id)
            updated_cache = connection.execute(
                sa.update(company_contact_lookup)
                .where(
                    company_contact_lookup.c.account_id == account_id,
                    company_contact_lookup.c.company_key == company_key,
                    company_contact_lookup.c.lease_id == attempt_id,
                    company_contact_lookup.c.status == "running",
                    company_contact_lookup.c.provider_organization_id
                    == provider_organization_id,
                    sa.exists(
                        sa.select(1).where(
                            supplier_directory.c.siren
                            == company_contact_lookup.c.directory_siren,
                            supplier_directory.c.apollo_organization_id
                            == provider_organization_id,
                            supplier_directory.c.apollo_status == "resolved",
                            supplier_directory.c.suppressed_at.is_(None),
                        )
                    ),
                )
                .values(
                    **cache_values,
                    lease_id=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            if updated_cache.rowcount != 1:
                raise _ContactLookupLeaseLost(attempt_id)

    @staticmethod
    def _render(
        row,
        *,
        plan_code: str,
        quota: int,
        used: int,
        now: dt.datetime,
        identity_available: bool = True,
    ) -> dict[str, Any]:
        remaining = max(0, quota - used)
        result: dict[str, Any] = {
            "state": "locked" if plan_code == "discovery" else "available",
            "remaining": remaining,
            "monthly_quota": quota,
            "source": "apollo",
            "removal_path": "/contact",
        }
        if plan_code == "discovery":
            return result
        if not identity_available:
            result["state"] = "identity_unavailable"
            return result
        if remaining == 0:
            result["next_reset_at"] = _next_month(now).isoformat()
        if row is None:
            if remaining == 0:
                result["state"] = "quota_exhausted"
            return result

        status = row["status"]
        lease_expires_at = _database_time(row["lease_expires_at"])
        if status == "running" and (lease_expires_at is None or now >= lease_expires_at):
            result["state"] = "available" if remaining > 0 else "quota_exhausted"
            return result
        result["state"] = {
            "running": "researching",
            "ready": "ready",
            "no_contact": "no_contact",
            "failed": "failed" if remaining > 0 else "quota_exhausted",
        }[status]
        researched_at = _database_time(row["researched_at"])
        refresh_after = _database_time(row["refresh_after"])
        if researched_at is not None:
            result["researched_at"] = researched_at.isoformat()
        if refresh_after is not None:
            result["refresh_after"] = refresh_after.isoformat()
            result["can_refresh"] = now >= refresh_after and remaining > 0
        if status in {"ready", "no_contact"}:
            if row["organization"]:
                result["organization"] = row["organization"]
            if row["contacts"]:
                result["contacts"] = row["contacts"]
        return result


__all__ = [
    "PLAN_MONTHLY_QUOTAS",
    "CompanyContactLookupService",
    "CompanyLookupIdentity",
    "ContactLookupIdentityUnavailable",
    "ContactLookupProviderFailure",
    "ContactLookupQuotaExceeded",
    "ContactLookupSuppressed",
]
