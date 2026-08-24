"""SQLAlchemy Core persistence for selected contacts and discovery runs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.contact_discovery.contracts import (
    ContactObservation,
    ContactObservationConflict,
    ContactRecord,
    ContactRunAlreadyStarted,
    ContactRunIdentityConflict,
    ContactRunRecord,
    ContactRunStart,
    ContactRunStatus,
)
from signals.contact_discovery.identity import contact_ref_for
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_contact, contact_discovery_run


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _contact(row: RowMapping) -> ContactRecord:
    values = dict(row)
    for field in (
        "provider_observed_at",
        "email_observed_at",
        "created_at",
        "updated_at",
    ):
        values[field] = _aware(values[field])
    return ContactRecord.model_validate(values)


def _run(row: RowMapping) -> ContactRunRecord:
    values = dict(row)
    values["attempted_contact_refs"] = tuple(values["attempted_contact_refs"])
    for field in ("started_at", "completed_at", "retry_after"):
        if values[field] is not None:
            values[field] = _aware(values[field])
    return ContactRunRecord.model_validate(values)


@dataclass(frozen=True)
class ContactUpsertResult:
    contact: ContactRecord
    created: bool
    metadata_updated: bool


@dataclass(frozen=True)
class ContactRunOwnership:
    run: ContactRunRecord
    owned: bool


class ContactDiscoveryStore:
    def __init__(self, engine: Engine, *, clock: Callable[[], dt.datetime] = _utc_now) -> None:
        self._engine = engine
        self._clock = clock

    def get_run(self, run_id: str) -> ContactRunRecord:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(contact_discovery_run).where(
                        contact_discovery_run.c.contact_discovery_run_id == run_id
                    )
                )
                .mappings()
                .one()
            )
        return _run(row)

    def get_run_by_policy(self, evaluation_id: str) -> ContactRunRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(contact_discovery_run).where(
                        contact_discovery_run.c.policy_evaluation_id == evaluation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _run(row) if row is not None else None

    def start_run(self, start: ContactRunStart) -> ContactRunOwnership:
        profile = start.profile
        values = {
            "contact_discovery_run_id": start.contact_discovery_run_id,
            "acquisition_opportunity_id": start.acquisition_opportunity_id,
            "supplier_ref": start.supplier_ref,
            "policy_evaluation_id": start.policy_evaluation_id,
            "provider": "apollo",
            "search_profile_version": profile.profile_version,
            "search_profile_fingerprint": profile.profile_fingerprint,
            "search_profile": profile.model_dump(mode="json"),
            "provider_request_fingerprint": start.provider_request_fingerprint,
            "expected_post_policy_version": start.expected_post_policy_version,
            "requested_max_pages": profile.max_pages,
            "per_page": profile.per_page,
            "max_enrichment_attempts": profile.max_enrichment_attempts,
            "people_search_requests": 0,
            "provider_total_entries": None,
            "search_results_returned": 0,
            "search_results_truncated": False,
            "candidates_eligible": 0,
            "candidates_rejected": 0,
            "enrichment_attempts": 0,
            "planned_provider_credit_units": profile.max_enrichment_attempts,
            "observed_provider_credit_units": None,
            "attempted_contact_refs": [],
            "selected_contact_ref": None,
            "started_at": start.started_at,
            "completed_at": None,
            "status": ContactRunStatus.STARTED.value,
            "error_category": None,
            "error_detail": None,
            "retry_after": None,
            "correlation_id": start.correlation_id,
        }
        with self._engine.begin() as connection:
            owned = self._insert_run_if_absent(connection, values)
            by_policy = (
                connection.execute(
                    sa.select(contact_discovery_run).where(
                        contact_discovery_run.c.policy_evaluation_id == start.policy_evaluation_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            by_id = (
                connection.execute(
                    sa.select(contact_discovery_run).where(
                        contact_discovery_run.c.contact_discovery_run_id
                        == start.contact_discovery_run_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if by_policy is None:
                if by_id is not None:
                    raise ContactRunIdentityConflict(start.contact_discovery_run_id)
                raise RuntimeError("contact run conflict could not be resolved")
            if by_id is not None and by_id["policy_evaluation_id"] != start.policy_evaluation_id:
                raise ContactRunIdentityConflict(start.contact_discovery_run_id)
            if not owned and any(
                by_policy[field] != values[field]
                for field in (
                    "acquisition_opportunity_id",
                    "supplier_ref",
                    "search_profile_fingerprint",
                    "provider_request_fingerprint",
                    "expected_post_policy_version",
                )
            ):
                raise ContactRunAlreadyStarted(by_policy["contact_discovery_run_id"])
            return ContactRunOwnership(_run(by_policy), owned)

    def finish_run(
        self,
        run_id: str,
        *,
        status: ContactRunStatus,
        completed_at: dt.datetime,
        people_search_requests: int,
        provider_total_entries: int | None,
        search_results_returned: int,
        search_results_truncated: bool,
        candidates_eligible: int,
        candidates_rejected: int,
        enrichment_attempts: int,
        attempted_contact_refs: tuple[str, ...] = (),
        selected_contact_ref: str | None = None,
        observed_provider_credit_units: int | None = None,
        error_category: str | None = None,
        error_detail: str | None = None,
        retry_after: dt.datetime | None = None,
    ) -> ContactRunRecord:
        with self._engine.begin() as connection:
            return self.finish_run_in_transaction(
                connection,
                run_id,
                status=status,
                completed_at=completed_at,
                people_search_requests=people_search_requests,
                provider_total_entries=provider_total_entries,
                search_results_returned=search_results_returned,
                search_results_truncated=search_results_truncated,
                candidates_eligible=candidates_eligible,
                candidates_rejected=candidates_rejected,
                enrichment_attempts=enrichment_attempts,
                attempted_contact_refs=attempted_contact_refs,
                selected_contact_ref=selected_contact_ref,
                observed_provider_credit_units=observed_provider_credit_units,
                error_category=error_category,
                error_detail=error_detail,
                retry_after=retry_after,
            )

    def finish_run_in_transaction(
        self,
        connection: Connection,
        run_id: str,
        **values: object,
    ) -> ContactRunRecord:
        payload = dict(values)
        attempted = payload.get("attempted_contact_refs", ())
        payload["attempted_contact_refs"] = list(attempted)  # type: ignore[arg-type]
        status = payload.get("status")
        if isinstance(status, ContactRunStatus):
            payload["status"] = status.value
        result = connection.execute(
            sa.update(contact_discovery_run)
            .where(
                contact_discovery_run.c.contact_discovery_run_id == run_id,
                contact_discovery_run.c.status == ContactRunStatus.STARTED.value,
            )
            .values(**payload)
        )
        if result.rowcount != 1:
            raise ContactRunAlreadyStarted(run_id)
        row = (
            connection.execute(
                sa.select(contact_discovery_run).where(
                    contact_discovery_run.c.contact_discovery_run_id == run_id
                )
            )
            .mappings()
            .one()
        )
        return _run(row)

    @staticmethod
    def _insert_run_if_absent(connection: Connection, values: dict[str, object]) -> bool:
        if connection.dialect.name == "sqlite" or connection.dialect.name == "postgresql":
            pass
        else:
            raise RuntimeError("unsupported contact persistence dialect")
        inserted = insert_if_absent(
            connection,
            contact_discovery_run,
            values,
        )
        return inserted

    def get_contact(self, contact_ref: str) -> ContactRecord:
        with self._engine.connect() as connection:
            return self.get_contact_in_transaction(connection, contact_ref)

    @staticmethod
    def get_contact_in_transaction(
        connection: Connection, contact_ref: str, *, for_update: bool = False
    ) -> ContactRecord:
        query = sa.select(acquisition_contact).where(
            acquisition_contact.c.contact_ref == contact_ref
        )
        if for_update:
            if connection.dialect.name == "sqlite":
                # SQLite ignores SELECT FOR UPDATE. A bounded no-op write gives
                # tests and local execution the same serialization boundary.
                result = connection.execute(
                    sa.update(acquisition_contact)
                    .where(acquisition_contact.c.contact_ref == contact_ref)
                    .values(contact_ref=acquisition_contact.c.contact_ref)
                )
                if result.rowcount != 1:
                    raise sa.exc.NoResultFound(contact_ref)
            else:
                query = query.with_for_update()
        row = (
            connection.execute(query)
            .mappings()
            .one()
        )
        return _contact(row)

    def upsert_contact(self, observation: ContactObservation) -> ContactUpsertResult:
        with self._engine.begin() as connection:
            return self.upsert_contact_in_transaction(connection, observation)

    def upsert_contact_in_transaction(
        self, connection: Connection, observation: ContactObservation
    ) -> ContactUpsertResult:
        now = self._clock()
        contact_ref = contact_ref_for(
            observation.provider,
            observation.provider_person_id,
            observation.supplier_ref,
        )
        mutable = observation.model_dump(mode="python")
        values = {
            "contact_ref": contact_ref,
            **mutable,
            "created_at": now,
            "updated_at": now,
        }
        created = self._insert_contact_if_absent(connection, values)
        row = (
            connection.execute(
                sa.select(acquisition_contact)
                .where(acquisition_contact.c.contact_ref == contact_ref)
                .with_for_update()
            )
            .mappings()
            .one()
        )
        if created:
            return ContactUpsertResult(_contact(row), True, True)
        if row["provider_organization_id"] != observation.provider_organization_id:
            raise ContactObservationConflict("provider organization changed")
        stored_at = _aware(row["provider_observed_at"])
        if observation.provider_observed_at < stored_at:
            return ContactUpsertResult(_contact(row), False, False)
        if observation.provider_observed_at == stored_at:
            if row["source_fingerprint"] != observation.source_fingerprint:
                raise ContactObservationConflict("equal timestamp has different payload")
            return ContactUpsertResult(_contact(row), False, False)
        result = connection.execute(
            sa.update(acquisition_contact)
            .where(
                acquisition_contact.c.contact_ref == contact_ref,
                acquisition_contact.c.provider_observed_at < observation.provider_observed_at,
            )
            .values(**mutable, updated_at=now)
        )
        if result.rowcount != 1:
            raise ContactObservationConflict("contact observation changed concurrently")
        updated = (
            connection.execute(
                sa.select(acquisition_contact).where(
                    acquisition_contact.c.contact_ref == contact_ref
                )
            )
            .mappings()
            .one()
        )
        return ContactUpsertResult(_contact(updated), False, True)

    @staticmethod
    def _insert_contact_if_absent(connection: Connection, values: dict[str, object]) -> bool:
        if connection.dialect.name == "sqlite" or connection.dialect.name == "postgresql":
            pass
        else:
            raise RuntimeError("unsupported contact persistence dialect")
        inserted = insert_if_absent(
            connection,
            acquisition_contact,
            values,
            index_elements=[acquisition_contact.c.provider, acquisition_contact.c.provider_person_id, acquisition_contact.c.supplier_ref,],
        )
        return inserted
