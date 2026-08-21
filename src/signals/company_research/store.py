"""SQLAlchemy Core persistence for company research profiles and runs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.company_research.contracts import (
    AcquisitionCompanyProfile,
    AcquisitionProspectPrebuild,
    CompanyResearchContactBinding,
    CompanyResearchObservationConflict,
    CompanyResearchRunAlreadyStarted,
    CompanyResearchRunIdentityConflict,
    CompanyResearchRunRecord,
    CompanyResearchRunStart,
    CompanyResearchRunStatus,
)
from signals.persistence.schema import (
    acquisition_company_profile,
    acquisition_contact,
    company_research_run,
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _profile(row: RowMapping) -> AcquisitionCompanyProfile:
    values = dict(row)
    values["provider_keywords"] = tuple(values["provider_keywords"])
    values["research_gaps"] = tuple(values["research_gaps"])
    for field in ("provider_observed_at", "created_at", "updated_at"):
        values[field] = _aware(values[field])
    return AcquisitionCompanyProfile.model_validate(values)


def _run(row: RowMapping) -> CompanyResearchRunRecord:
    values = dict(row)
    for field in ("started_at", "completed_at", "retry_after"):
        if values[field] is not None:
            values[field] = _aware(values[field])
    return CompanyResearchRunRecord.model_validate(values)


@dataclass(frozen=True)
class CompanyProfileUpsertResult:
    profile: AcquisitionCompanyProfile
    created: bool
    metadata_updated: bool


@dataclass(frozen=True)
class CompanyResearchRunOwnership:
    run: CompanyResearchRunRecord
    owned: bool


class CompanyResearchStore:
    def __init__(self, engine: Engine, *, clock: Callable[[], dt.datetime] = _utc_now) -> None:
        self._engine = engine
        self._clock = clock

    def get_run(self, run_id: str) -> CompanyResearchRunRecord:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(company_research_run).where(
                        company_research_run.c.company_research_run_id == run_id
                    )
                )
                .mappings()
                .one()
            )
        return _run(row)

    def get_run_by_policy(self, evaluation_id: str) -> CompanyResearchRunRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(company_research_run).where(
                        company_research_run.c.policy_evaluation_id == evaluation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _run(row) if row is not None else None

    def start_run(self, start: CompanyResearchRunStart) -> CompanyResearchRunOwnership:
        profile = start.profile
        values: dict[str, object] = {
            "company_research_run_id": start.company_research_run_id,
            "acquisition_opportunity_id": start.acquisition_opportunity_id,
            "supplier_ref": start.supplier_ref,
            "contact_ref": start.contact_ref,
            "policy_evaluation_id": start.policy_evaluation_id,
            "research_profile_version": profile.profile_version,
            "research_profile_fingerprint": profile.profile_fingerprint,
            "research_profile": profile.model_dump(mode="json"),
            "provider": profile.provider,
            "provider_endpoint_kind": profile.endpoint_kind,
            "provider_request_fingerprint": start.provider_request_fingerprint,
            "expected_post_policy_version": start.expected_post_policy_version,
            "planned_provider_credit_units": 1,
            "observed_provider_credit_units": None,
            "provider_calls": 0,
            "started_at": start.started_at,
            "completed_at": None,
            "status": CompanyResearchRunStatus.STARTED.value,
            "error_category": None,
            "error_detail": None,
            "retry_after": None,
            "correlation_id": start.correlation_id,
        }
        with self._engine.begin() as connection:
            existing_id = (
                connection.execute(
                    sa.select(company_research_run).where(
                        company_research_run.c.company_research_run_id
                        == start.company_research_run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing_id is not None and (
                existing_id["policy_evaluation_id"] != start.policy_evaluation_id
            ):
                raise CompanyResearchRunIdentityConflict(start.company_research_run_id)
            owned = self._insert_run_if_absent(connection, values)
            by_policy = (
                connection.execute(
                    sa.select(company_research_run).where(
                        company_research_run.c.policy_evaluation_id == start.policy_evaluation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            by_id = (
                connection.execute(
                    sa.select(company_research_run).where(
                        company_research_run.c.company_research_run_id
                        == start.company_research_run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if by_policy is None:
                if by_id is not None:
                    raise CompanyResearchRunIdentityConflict(start.company_research_run_id)
                raise RuntimeError("company research run conflict could not be resolved")
            if by_id is not None and by_id["policy_evaluation_id"] != start.policy_evaluation_id:
                raise CompanyResearchRunIdentityConflict(start.company_research_run_id)
            if not owned and any(
                by_policy[field] != values[field]
                for field in (
                    "acquisition_opportunity_id",
                    "supplier_ref",
                    "contact_ref",
                    "research_profile_fingerprint",
                    "provider_request_fingerprint",
                    "expected_post_policy_version",
                )
            ):
                raise CompanyResearchRunAlreadyStarted(by_policy["company_research_run_id"])
            return CompanyResearchRunOwnership(_run(by_policy), owned)

    @staticmethod
    def _insert_run_if_absent(connection: Connection, values: dict[str, object]) -> bool:
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported company research persistence dialect")
        result = connection.execute(
            insert(company_research_run).values(values).on_conflict_do_nothing()
        )
        if result.rowcount not in {0, 1}:
            raise RuntimeError("indeterminate company-research-run ownership")
        return result.rowcount == 1

    def finish_run(
        self,
        run_id: str,
        *,
        status: CompanyResearchRunStatus,
        completed_at: dt.datetime,
        provider_calls: int,
        observed_provider_credit_units: int | None = None,
        error_category: str | None = None,
        error_detail: str | None = None,
        retry_after: dt.datetime | None = None,
    ) -> CompanyResearchRunRecord:
        with self._engine.begin() as connection:
            return self.finish_run_in_transaction(
                connection,
                run_id,
                status=status,
                completed_at=completed_at,
                provider_calls=provider_calls,
                observed_provider_credit_units=observed_provider_credit_units,
                error_category=error_category,
                error_detail=error_detail,
                retry_after=retry_after,
            )

    def finish_run_in_transaction(
        self, connection: Connection, run_id: str, **values: object
    ) -> CompanyResearchRunRecord:
        payload = dict(values)
        status = payload.get("status")
        if isinstance(status, CompanyResearchRunStatus):
            payload["status"] = status.value
        result = connection.execute(
            sa.update(company_research_run)
            .where(
                company_research_run.c.company_research_run_id == run_id,
                company_research_run.c.status == CompanyResearchRunStatus.STARTED.value,
            )
            .values(**payload)
        )
        if result.rowcount != 1:
            raise CompanyResearchRunAlreadyStarted(run_id)
        row = (
            connection.execute(
                sa.select(company_research_run).where(
                    company_research_run.c.company_research_run_id == run_id
                )
            )
            .mappings()
            .one()
        )
        return _run(row)

    def get_profile(self, opportunity_id: str) -> AcquisitionCompanyProfile:
        with self._engine.connect() as connection:
            return self.get_profile_in_transaction(connection, opportunity_id)

    @staticmethod
    def get_profile_in_transaction(
        connection: Connection, opportunity_id: str
    ) -> AcquisitionCompanyProfile:
        row = (
            connection.execute(
                sa.select(acquisition_company_profile).where(
                    acquisition_company_profile.c.acquisition_opportunity_id == opportunity_id
                )
            )
            .mappings()
            .one()
        )
        return _profile(row)

    def get_contact_binding(self, contact_ref: str) -> CompanyResearchContactBinding:
        with self._engine.connect() as connection:
            return self.get_contact_binding_in_transaction(connection, contact_ref)

    @staticmethod
    def get_contact_binding_in_transaction(
        connection: Connection, contact_ref: str
    ) -> CompanyResearchContactBinding:
        row = (
            connection.execute(
                sa.select(
                    acquisition_contact.c.contact_ref,
                    acquisition_contact.c.supplier_ref,
                    acquisition_contact.c.verification_state,
                    acquisition_contact.c.verification_provider,
                    acquisition_contact.c.provider_email_status,
                    acquisition_contact.c.role_profile_version,
                    acquisition_contact.c.role_tier,
                ).where(acquisition_contact.c.contact_ref == contact_ref)
            )
            .mappings()
            .one()
        )
        return CompanyResearchContactBinding.model_validate(dict(row))

    def upsert_profile(self, prebuild: AcquisitionProspectPrebuild) -> CompanyProfileUpsertResult:
        with self._engine.begin() as connection:
            return self.upsert_profile_in_transaction(connection, prebuild)

    def upsert_profile_in_transaction(
        self, connection: Connection, prebuild: AcquisitionProspectPrebuild
    ) -> CompanyProfileUpsertResult:
        now = self._clock()
        mutable = prebuild.model_dump(mode="python")
        mutable["provider_keywords"] = list(prebuild.provider_keywords)
        mutable["research_gaps"] = [gap.value for gap in prebuild.research_gaps]
        for field in (
            "supplier_identity_status",
            "provider_research_status",
            "research_completeness",
            "size_band",
        ):
            mutable[field] = getattr(prebuild, field).value
        values = {**mutable, "created_at": now, "updated_at": now}
        created = self._insert_profile_if_absent(connection, values)
        row = (
            connection.execute(
                sa.select(acquisition_company_profile)
                .where(
                    acquisition_company_profile.c.acquisition_opportunity_id
                    == prebuild.acquisition_opportunity_id
                )
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if created:
            return CompanyProfileUpsertResult(_profile(row), True, True)
        for field in ("supplier_ref", "contact_ref", "signal_ref"):
            if row[field] != getattr(prebuild, field):
                raise CompanyResearchObservationConflict(f"immutable {field} changed")
        stored_at = _aware(row["provider_observed_at"])
        if prebuild.provider_observed_at < stored_at:
            return CompanyProfileUpsertResult(_profile(row), False, False)
        if prebuild.provider_observed_at == stored_at:
            if not (
                row["provider_source_fingerprint"] == prebuild.provider_source_fingerprint
                and row["prebuild_fingerprint"] == prebuild.prebuild_fingerprint
            ):
                raise CompanyResearchObservationConflict(
                    "equal timestamp has different company research semantics"
                )
            return CompanyProfileUpsertResult(_profile(row), False, False)
        update_values = dict(mutable)
        for immutable in (
            "acquisition_opportunity_id",
            "supplier_ref",
            "contact_ref",
            "signal_ref",
        ):
            update_values.pop(immutable)
        result = connection.execute(
            sa.update(acquisition_company_profile)
            .where(
                acquisition_company_profile.c.acquisition_opportunity_id
                == prebuild.acquisition_opportunity_id,
                acquisition_company_profile.c.provider_observed_at < prebuild.provider_observed_at,
            )
            .values(**update_values, updated_at=now)
        )
        if result.rowcount != 1:
            raise CompanyResearchObservationConflict(
                "company research observation changed concurrently"
            )
        updated = (
            connection.execute(
                sa.select(acquisition_company_profile).where(
                    acquisition_company_profile.c.acquisition_opportunity_id
                    == prebuild.acquisition_opportunity_id
                )
            )
            .mappings()
            .one()
        )
        return CompanyProfileUpsertResult(_profile(updated), False, True)

    @staticmethod
    def _insert_profile_if_absent(connection: Connection, values: dict[str, object]) -> bool:
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported company research persistence dialect")
        result = connection.execute(
            insert(acquisition_company_profile)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[acquisition_company_profile.c.acquisition_opportunity_id]
            )
        )
        if result.rowcount not in {0, 1}:
            raise RuntimeError("indeterminate company-profile ownership")
        return result.rowcount == 1


__all__ = [
    "CompanyProfileUpsertResult",
    "CompanyResearchRunOwnership",
    "CompanyResearchStore",
]
