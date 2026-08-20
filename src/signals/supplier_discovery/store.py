"""SQLAlchemy Core persistence for supplier identities and discovery runs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.persistence.schema import acquisition_supplier, supplier_discovery_run
from signals.supplier_discovery.contracts import (
    ApolloOrganizationCandidate,
    DiscoveryAlreadyStarted,
    DiscoveryRunIdentityConflict,
    DiscoveryRunRecord,
    DiscoveryRunStart,
    DiscoveryRunStatus,
    SupplierIdentityStatus,
    SupplierRecord,
)
from signals.supplier_discovery.identity import (
    domain_conflict_fingerprint,
    supplier_ref_for,
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _domain_lock_key(domain: str) -> int:
    digest = domain_conflict_fingerprint(f"supplier-domain-lock:{domain}")
    return int.from_bytes(bytes.fromhex(digest[:16]), byteorder="big", signed=True)


def _record(row: RowMapping) -> SupplierRecord:
    values = dict(row)
    for field in ("provider_observed_at", "created_at", "updated_at"):
        values[field] = _aware(values[field])
    return SupplierRecord.model_validate(values)


@dataclass(frozen=True)
class SupplierUpsertResult:
    supplier: SupplierRecord
    created: bool
    metadata_updated: bool


@dataclass(frozen=True)
class RunOwnership:
    run: DiscoveryRunRecord
    owned: bool


def _run_record(row: RowMapping) -> DiscoveryRunRecord:
    values = dict(row)
    for field in ("started_at", "completed_at", "retry_after"):
        if values[field] is not None:
            values[field] = _aware(values[field])
    return DiscoveryRunRecord.model_validate(values)


class SupplierDiscoveryStore:
    def __init__(
        self, engine: Engine, *, clock: Callable[[], dt.datetime] = _utc_now
    ) -> None:
        self._engine = engine
        self._clock = clock

    def get_run(self, discovery_run_id: str) -> DiscoveryRunRecord:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(supplier_discovery_run).where(
                    supplier_discovery_run.c.discovery_run_id == discovery_run_id
                )
            ).mappings().one()
        return _run_record(row)

    def start_run(self, start: DiscoveryRunStart) -> RunOwnership:
        profile = start.profile
        values = {
            "discovery_run_id": start.discovery_run_id,
            "signal_ref": profile.signal_ref,
            "policy_evaluation_id": start.policy_evaluation_id,
            "provider": "apollo",
            "search_profile_version": profile.profile_version,
            "search_profile_fingerprint": profile.profile_fingerprint,
            "search_profile": profile.model_dump(mode="json"),
            "provider_request_fingerprint": start.provider_request_fingerprint,
            "requested_max_pages": profile.max_pages,
            "per_page": profile.per_page,
            "candidate_cap": profile.candidate_cap,
            "planned_provider_credit_units": profile.max_pages,
            "pages_requested": 0,
            "provider_credit_units_observed": None,
            "provider_total_entries": None,
            "partial_results_only": None,
            "records_returned": 0,
            "records_accepted": 0,
            "records_rejected": 0,
            "rejection_reason_counts": {},
            "duplicates": 0,
            "opportunities_created": 0,
            "started_at": start.started_at,
            "completed_at": None,
            "status": DiscoveryRunStatus.STARTED.value,
            "error_category": None,
            "error_detail": None,
            "retry_after": None,
            "correlation_id": start.correlation_id,
        }
        with self._engine.begin() as connection:
            owned = self._insert_run_if_absent(connection, values)
            policy_row = connection.execute(
                sa.select(supplier_discovery_run).where(
                    supplier_discovery_run.c.policy_evaluation_id
                    == start.policy_evaluation_id
                )
            ).mappings().one_or_none()
            run_row = connection.execute(
                sa.select(supplier_discovery_run).where(
                    supplier_discovery_run.c.discovery_run_id
                    == start.discovery_run_id
                )
            ).mappings().one_or_none()
            if policy_row is None:
                if run_row is None:
                    raise RuntimeError("discovery run conflict could not be resolved")
                raise DiscoveryRunIdentityConflict(
                    "discovery_run_id belongs to another policy evaluation"
                )
            row = policy_row
            if run_row is not None and (
                run_row["policy_evaluation_id"] != start.policy_evaluation_id
            ):
                raise DiscoveryRunIdentityConflict(
                    "discovery_run_id belongs to another policy evaluation"
                )
            if not owned and any(
                row[field] != values[field]
                for field in (
                    "signal_ref",
                    "search_profile_version",
                    "search_profile_fingerprint",
                    "provider_request_fingerprint",
                )
            ):
                raise DiscoveryAlreadyStarted(row["discovery_run_id"])
            return RunOwnership(_run_record(row), owned)

    def finish_run(
        self,
        discovery_run_id: str,
        *,
        status: DiscoveryRunStatus,
        completed_at: dt.datetime,
        pages_requested: int,
        provider_total_entries: int | None,
        partial_results_only: bool | None,
        records_returned: int,
        records_accepted: int,
        records_rejected: int,
        rejection_reason_counts: dict[str, int],
        duplicates: int,
        opportunities_created: int,
        provider_credit_units_observed: int | None = None,
        error_category: str | None = None,
        error_detail: str | None = None,
        retry_after: dt.datetime | None = None,
    ) -> DiscoveryRunRecord:
        if status is DiscoveryRunStatus.STARTED:
            raise ValueError("finish_run requires a terminal status")
        with self._engine.begin() as connection:
            result = connection.execute(
                sa.update(supplier_discovery_run)
                .where(
                    supplier_discovery_run.c.discovery_run_id == discovery_run_id,
                    supplier_discovery_run.c.status == DiscoveryRunStatus.STARTED.value,
                )
                .values(
                    status=status.value,
                    completed_at=completed_at,
                    pages_requested=pages_requested,
                    provider_credit_units_observed=provider_credit_units_observed,
                    provider_total_entries=provider_total_entries,
                    partial_results_only=partial_results_only,
                    records_returned=records_returned,
                    records_accepted=records_accepted,
                    records_rejected=records_rejected,
                    rejection_reason_counts=rejection_reason_counts,
                    duplicates=duplicates,
                    opportunities_created=opportunities_created,
                    error_category=error_category,
                    error_detail=error_detail[:512] if error_detail else None,
                    retry_after=retry_after,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("discovery run is not an owned STARTED run")
            row = connection.execute(
                sa.select(supplier_discovery_run).where(
                    supplier_discovery_run.c.discovery_run_id == discovery_run_id
                )
            ).mappings().one()
        return _run_record(row)

    @staticmethod
    def _insert_run_if_absent(
        connection: Connection, values: dict[str, object]
    ) -> bool:
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported discovery persistence dialect")
        result = connection.execute(
            insert(supplier_discovery_run)
            .values(values)
            .on_conflict_do_nothing()
        )
        if result.rowcount not in {0, 1}:
            raise RuntimeError("indeterminate discovery-run ownership")
        return result.rowcount == 1

    def get_supplier(self, supplier_ref: str) -> SupplierRecord:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_supplier).where(
                    acquisition_supplier.c.supplier_ref == supplier_ref
                )
            ).mappings().one()
        return _record(row)

    def upsert_supplier(
        self, candidate: ApolloOrganizationCandidate
    ) -> SupplierUpsertResult:
        with self._engine.begin() as connection:
            return self.upsert_supplier_in_transaction(connection, candidate)

    def upsert_supplier_in_transaction(
        self,
        connection: Connection,
        candidate: ApolloOrganizationCandidate,
    ) -> SupplierUpsertResult:
        now = self._clock()
        supplier_ref = supplier_ref_for(
            candidate.provider, candidate.provider_organization_id
        )
        insert_values = {
            "supplier_ref": supplier_ref,
            "provider": candidate.provider,
            "provider_organization_id": candidate.provider_organization_id,
            "display_name": candidate.display_name,
            "normalized_name": candidate.normalized_name,
            "primary_domain": candidate.primary_domain,
            "website_url": candidate.website_url,
            "linkedin_company_url": candidate.linkedin_company_url,
            "country_code": candidate.country_code,
            "location": candidate.location,
            "industry": candidate.industry,
            "identity_status": SupplierIdentityStatus.PROVIDER_IDENTIFIED.value,
            "identity_conflict_fingerprint": None,
            "provider_observed_at": candidate.provider_observed_at,
            "source_fingerprint": candidate.source_fingerprint,
            "created_at": now,
            "updated_at": now,
        }
        created = self._insert_supplier_if_absent(connection, insert_values)
        existing_row = connection.execute(
            sa.select(acquisition_supplier).where(
                acquisition_supplier.c.provider == candidate.provider,
                acquisition_supplier.c.provider_organization_id
                == candidate.provider_organization_id,
            )
        ).mappings().one()
        old_domain = None if created else existing_row["primary_domain"]
        metadata_updated = created
        if not created and candidate.provider_observed_at >= _aware(
            existing_row["provider_observed_at"]
        ):
            update = connection.execute(
                sa.update(acquisition_supplier)
                .where(
                    acquisition_supplier.c.supplier_ref == supplier_ref,
                    acquisition_supplier.c.provider_observed_at
                    <= candidate.provider_observed_at,
                )
                .values(
                    display_name=candidate.display_name,
                    normalized_name=candidate.normalized_name,
                    primary_domain=candidate.primary_domain,
                    website_url=candidate.website_url,
                    linkedin_company_url=candidate.linkedin_company_url,
                    country_code=candidate.country_code,
                    location=candidate.location,
                    industry=candidate.industry,
                    provider_observed_at=candidate.provider_observed_at,
                    source_fingerprint=candidate.source_fingerprint,
                    updated_at=now,
                )
            )
            metadata_updated = update.rowcount == 1
        if metadata_updated and candidate.primary_domain is None:
            connection.execute(
                sa.update(acquisition_supplier)
                .where(acquisition_supplier.c.supplier_ref == supplier_ref)
                .values(
                    identity_status=SupplierIdentityStatus.PROVIDER_IDENTIFIED.value,
                    identity_conflict_fingerprint=None,
                    updated_at=now,
                )
            )
        domains = tuple(sorted({old_domain, candidate.primary_domain} - {None}))
        self._lock_domains(connection, domains)
        for domain in domains:
            self._reconcile_domain(connection, domain, updated_at=now)
        row = connection.execute(
            sa.select(acquisition_supplier).where(
                acquisition_supplier.c.supplier_ref == supplier_ref
            )
        ).mappings().one()
        return SupplierUpsertResult(_record(row), created, metadata_updated)

    @staticmethod
    def _insert_supplier_if_absent(
        connection: Connection, values: dict[str, object]
    ) -> bool:
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported supplier persistence dialect")
        result = connection.execute(
            insert(acquisition_supplier)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[
                    acquisition_supplier.c.provider,
                    acquisition_supplier.c.provider_organization_id,
                ]
            )
        )
        if result.rowcount not in {0, 1}:
            raise RuntimeError("indeterminate supplier identity ownership")
        return result.rowcount == 1

    @staticmethod
    def _lock_domains(connection: Connection, domains: tuple[str, ...]) -> None:
        if connection.dialect.name == "postgresql":
            for domain in domains:
                connection.execute(
                    sa.select(sa.func.pg_advisory_xact_lock(_domain_lock_key(domain)))
                )
        elif connection.dialect.name != "sqlite":
            raise RuntimeError("unsupported supplier persistence dialect")

    @staticmethod
    def _reconcile_domain(
        connection: Connection, domain: str, *, updated_at: dt.datetime
    ) -> None:
        refs = tuple(
            connection.execute(
                sa.select(acquisition_supplier.c.supplier_ref).where(
                    acquisition_supplier.c.primary_domain == domain
                )
            ).scalars()
        )
        if len(refs) > 1:
            status = SupplierIdentityStatus.DOMAIN_CONFLICT.value
            fingerprint = domain_conflict_fingerprint(domain)
        else:
            status = SupplierIdentityStatus.PROVIDER_IDENTIFIED.value
            fingerprint = None
        if refs:
            connection.execute(
                sa.update(acquisition_supplier)
                .where(acquisition_supplier.c.supplier_ref.in_(refs))
                .values(
                    identity_status=status,
                    identity_conflict_fingerprint=fingerprint,
                    updated_at=updated_at,
                )
            )
