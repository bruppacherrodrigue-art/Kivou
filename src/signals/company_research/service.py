"""Permissioned, bounded Apollo company research orchestration."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import (
    AcquisitionState,
    ActorType,
    EventType,
    OpportunityConcurrencyConflict,
)
from signals.acquisition.store import AcquisitionStore
from signals.company_research.contracts import (
    CompanyResearchAuthorizationInput,
    CompanyResearchEvaluationRequiresFreshAttempt,
    CompanyResearchNotActionable,
    CompanyResearchObservationConflict,
    CompanyResearchProviderError,
    CompanyResearchRunIdentityConflict,
    CompanyResearchRunStart,
    CompanyResearchRunStatus,
    CompanyResearchServiceResult,
    ResearchCompleteness,
)
from signals.company_research.prebuild import build_acquisition_prospect_prebuild
from signals.company_research.profile import (
    build_company_research_profile,
    policy_action_fingerprint,
    provider_request_fingerprint,
)
from signals.company_research.provider import CompanyResearchProvider
from signals.company_research.store import CompanyResearchStore
from signals.persistence.schema import acquisition_supplier
from signals.policy.contracts import BudgetUsage, PolicyRequest
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row
from signals.supplier_discovery.contracts import SupplierRecord
from signals.supplier_discovery.store import SupplierDiscoveryStore


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


class CompanyResearchService:
    def __init__(
        self,
        engine: Engine,
        *,
        provider: CompanyResearchProvider,
        policy_gateway: PolicyGateway | None = None,
        company_store: CompanyResearchStore | None = None,
        acquisition_store: AcquisitionStore | None = None,
        supplier_store: SupplierDiscoveryStore | None = None,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._policy = policy_gateway or PolicyGateway(engine)
        self._companies = company_store or CompanyResearchStore(engine, clock=clock)
        self._acquisition = acquisition_store or AcquisitionStore(engine, clock=clock)
        self._suppliers = supplier_store or SupplierDiscoveryStore(engine, clock=clock)
        self._policy_store = PolicyStore(engine)
        self._clock = clock

    def research(
        self,
        opportunity_id: str,
        authorization: CompanyResearchAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        company_research_run_id: str,
        correlation_id: str,
    ) -> CompanyResearchServiceResult:
        existing_run = self._companies.get_run_by_policy(authorization.evaluation_id)
        if existing_run is not None:
            self._require_existing_run_binding(
                existing_run,
                opportunity_id=opportunity_id,
                authorization=authorization,
            )
            return CompanyResearchServiceResult(run=existing_run)
        with self._engine.connect() as connection:
            if (
                self._policy_store.evaluation_row(connection, authorization.evaluation_id)
                is not None
            ):
                raise CompanyResearchEvaluationRequiresFreshAttempt(authorization.evaluation_id)

        opportunity = self._acquisition.get_opportunity(opportunity_id)
        self._require_actionable(opportunity)
        assert opportunity.supplier_ref is not None
        assert opportunity.contact_ref is not None
        supplier = self._suppliers.get_supplier(opportunity.supplier_ref)
        contact = self._companies.get_contact_binding(opportunity.contact_ref)
        self._require_bindings(opportunity, supplier, contact)
        profile = build_company_research_profile(supplier.provider_organization_id)
        action_fingerprint = policy_action_fingerprint(
            profile,
            acquisition_opportunity_id=opportunity_id,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
        )
        arguments = _canonical_json(
            {
                "profile": profile.model_dump(mode="json"),
                "supplier_ref": supplier.supplier_ref,
                "contact_ref": contact.contact_ref,
            }
        )
        decision = self._policy.evaluate_and_record(
            self._policy_request(
                authorization,
                opportunity_id=opportunity_id,
                expected_version=opportunity.stream_version,
                arguments=arguments,
                action_fingerprint=action_fingerprint,
            ),
            evaluated_at=evaluated_at,
            budget_usage=budget_usage,
        )
        if not decision.executable:
            return CompanyResearchServiceResult(decision=decision)

        ownership = self._companies.start_run(
            CompanyResearchRunStart(
                company_research_run_id=company_research_run_id,
                acquisition_opportunity_id=opportunity_id,
                supplier_ref=supplier.supplier_ref,
                contact_ref=contact.contact_ref,
                policy_evaluation_id=decision.evaluation_id,
                profile=profile,
                provider_request_fingerprint=provider_request_fingerprint(profile),
                expected_post_policy_version=opportunity.stream_version + 1,
                started_at=self._now(),
                correlation_id=correlation_id,
            )
        )
        if not ownership.owned:
            return CompanyResearchServiceResult(decision=decision, run=ownership.run)
        return self._execute(ownership.run, supplier, contact, decision)

    def resume_started(
        self,
        run_id: str,
        *,
        authorize_recovery: Callable[[], None],
    ) -> CompanyResearchServiceResult | None:
        """Replay one indeterminate exact-ID lookup from durable Policy truth."""

        try:
            run = self._companies.get_run(run_id)
        except sa.exc.NoResultFound:
            return None
        decision = self._durable_decision(run)
        if run.status is not CompanyResearchRunStatus.STARTED:
            return CompanyResearchServiceResult(decision=decision, run=run)
        authorize_recovery()
        ownership = self._companies.claim_recovery(run_id)
        if not ownership.owned:
            return CompanyResearchServiceResult(
                decision=decision,
                run=ownership.run,
            )
        opportunity = self._acquisition.get_opportunity(
            ownership.run.acquisition_opportunity_id
        )
        supplier = self._suppliers.get_supplier(ownership.run.supplier_ref)
        contact = self._companies.get_contact_binding(ownership.run.contact_ref)
        self._require_post_policy(opportunity, ownership.run)
        self._require_bindings(opportunity, supplier, contact)
        return self._execute(ownership.run, supplier, contact, decision)

    def _durable_decision(self, run):
        profile = build_company_research_profile(
            str(run.research_profile["provider_organization_id"])
        )
        expected_action = policy_action_fingerprint(
            profile,
            acquisition_opportunity_id=run.acquisition_opportunity_id,
            supplier_ref=run.supplier_ref,
            contact_ref=run.contact_ref,
        )
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(
                connection, run.policy_evaluation_id
            )
        if row is None or not (
            row["acquisition_opportunity_id"] == run.acquisition_opportunity_id
            and row["command"] == "enrich_company"
            and row["target_ref"]
            == self._expected_target(run.acquisition_opportunity_id)
            and row["action_fingerprint"] == expected_action
            and run.research_profile_fingerprint == profile.profile_fingerprint
        ):
            raise CompanyResearchRunIdentityConflict(run.policy_evaluation_id)
        decision = decision_from_row(row)
        if not decision.executable:
            raise CompanyResearchRunIdentityConflict(run.policy_evaluation_id)
        return decision

    def _execute(self, run, supplier, contact, decision) -> CompanyResearchServiceResult:
        profile = build_company_research_profile(supplier.provider_organization_id)
        try:
            observation = self._provider.fetch_organization(profile)
            if observation.provider_organization_id != supplier.provider_organization_id:
                raise CompanyResearchProviderError("provider_identity_mismatch")
            if observation.provider_observed_at < run.started_at:
                raise CompanyResearchProviderError(
                    "malformed_response", detail="provider_observation_precedes_run"
                )
        except CompanyResearchProviderError as error:
            finished = self._finish_provider_failure(run, error)
            return CompanyResearchServiceResult(
                decision=decision, run=finished, provider_called=True
            )

        try:
            persisted, finished = self._commit_success(run, observation)
        except (
            CompanyResearchObservationConflict,
            CompanyResearchNotActionable,
            OpportunityConcurrencyConflict,
            sa.exc.SQLAlchemyError,
            RuntimeError,
        ) as error:
            finished = self._finish_persistence_failure(run, error)
            return CompanyResearchServiceResult(
                decision=decision, run=finished, provider_called=True
            )
        return CompanyResearchServiceResult(
            decision=decision,
            run=finished,
            profile=persisted,
            provider_called=True,
        )

    def _commit_success(self, run, observation):
        with self._engine.begin() as connection:
            current = self._acquisition.get_opportunity_in_transaction(
                connection, run.acquisition_opportunity_id, for_update=True
            )
            self._require_post_policy(current, run)
            supplier = self._supplier_in_transaction(connection, run.supplier_ref)
            contact = self._companies.get_contact_binding_in_transaction(
                connection, run.contact_ref
            )
            self._require_bindings(current, supplier, contact)
            if supplier.provider_organization_id != observation.provider_organization_id:
                raise CompanyResearchObservationConflict("research binding changed")
            prebuild = build_acquisition_prospect_prebuild(
                acquisition_opportunity_id=current.acquisition_opportunity_id,
                signal_ref=current.signal_ref,
                supplier_ref=supplier.supplier_ref,
                contact_ref=contact.contact_ref,
                supplier_identity_status=supplier.identity_status,
                contact_role_profile_version=contact.role_profile_version,
                contact_role_tier=contact.role_tier,
                observation=observation,
            )
            upserted = self._companies.upsert_profile_in_transaction(connection, prebuild)
            transitioned = self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.STATE_TRANSITIONED,
                expected_version=run.expected_post_policy_version,
                idempotency_key=f"company_ready:{run.company_research_run_id}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-company-research",
                payload={"target_state": AcquisitionState.READY_FOR_DECISION.value},
                correlation_id=run.correlation_id,
            )
            self._acquisition.append_in_transaction(
                connection,
                current.acquisition_opportunity_id,
                event_type=EventType.NEXT_ACTION_SET,
                expected_version=transitioned.projection.stream_version,
                idempotency_key=f"company_next_action:{run.company_research_run_id}",
                actor_type=ActorType.SYSTEM,
                actor_ref="kivou-company-research",
                payload={"next_action": "evaluate_opportunity"},
                correlation_id=run.correlation_id,
            )
            status = (
                CompanyResearchRunStatus.SUCCESS
                if prebuild.research_completeness is ResearchCompleteness.COMPLETE
                else CompanyResearchRunStatus.LIMITED
            )
            finished = self._companies.finish_run_in_transaction(
                connection,
                run.company_research_run_id,
                status=status,
                completed_at=self._now(),
                provider_calls=1,
            )
        return upserted.profile, finished

    def _finish_provider_failure(self, run, error):
        return self._companies.finish_run(
            run.company_research_run_id,
            status=CompanyResearchRunStatus.FAILED,
            completed_at=self._now(),
            provider_calls=1,
            error_category=error.category,
            error_detail=error.detail,
            retry_after=error.retry_after,
        )

    def _finish_persistence_failure(self, run, error):
        if isinstance(error, CompanyResearchObservationConflict):
            category = "company_observation_conflict"
        elif isinstance(error, (OpportunityConcurrencyConflict, CompanyResearchNotActionable)):
            category = "opportunity_concurrency_conflict"
        else:
            category = "persistence_error"
        return self._companies.finish_run(
            run.company_research_run_id,
            status=CompanyResearchRunStatus.FAILED,
            completed_at=self._now(),
            provider_calls=1,
            error_category=category,
            error_detail=type(error).__name__,
        )

    @staticmethod
    def _require_actionable(opportunity) -> None:
        if not (
            opportunity.state is AcquisitionState.ENRICHING
            and opportunity.supplier_ref is not None
            and opportunity.contact_ref is not None
            and opportunity.next_action == "enrich_company"
        ):
            raise CompanyResearchNotActionable(opportunity.acquisition_opportunity_id)

    @classmethod
    def _require_post_policy(cls, opportunity, run) -> None:
        cls._require_actionable(opportunity)
        if (
            opportunity.stream_version != run.expected_post_policy_version
            or opportunity.supplier_ref != run.supplier_ref
            or opportunity.contact_ref != run.contact_ref
        ):
            raise OpportunityConcurrencyConflict(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _require_bindings(opportunity, supplier, contact) -> None:
        if not (
            supplier.provider == "apollo"
            and supplier.provider_organization_id
            and opportunity.supplier_ref == supplier.supplier_ref
            and opportunity.contact_ref == contact.contact_ref
            and contact.supplier_ref == supplier.supplier_ref
            and contact.verification_state == "PROVIDER_VERIFIED"
            and contact.verification_provider == "apollo"
            and contact.provider_email_status == "verified"
        ):
            raise CompanyResearchNotActionable(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _expected_target(opportunity_id: str) -> str:
        return f"acquisition-opportunity:{opportunity_id}"

    def _require_existing_run_binding(
        self,
        run,
        *,
        opportunity_id: str,
        authorization: CompanyResearchAuthorizationInput,
    ) -> None:
        with self._engine.connect() as connection:
            evaluation = self._policy_store.evaluation_row(connection, authorization.evaluation_id)
        profile = build_company_research_profile(
            str(run.research_profile["provider_organization_id"])
        )
        expected_action = policy_action_fingerprint(
            profile,
            acquisition_opportunity_id=run.acquisition_opportunity_id,
            supplier_ref=run.supplier_ref,
            contact_ref=run.contact_ref,
        )
        if evaluation is None or not (
            run.acquisition_opportunity_id == opportunity_id
            and evaluation["acquisition_opportunity_id"] == opportunity_id
            and evaluation["request_id"] == authorization.request_id
            and evaluation["command"] == "enrich_company"
            and evaluation["target_ref"] == self._expected_target(opportunity_id)
            and evaluation["action_fingerprint"] == expected_action
        ):
            raise CompanyResearchRunIdentityConflict(authorization.evaluation_id)

    @staticmethod
    def _policy_request(
        authorization,
        *,
        opportunity_id,
        expected_version,
        arguments,
        action_fingerprint,
    ) -> PolicyRequest:
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="enrich_company",
            target_ref=CompanyResearchService._expected_target(opportunity_id),
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=arguments,
            action_fingerprint=action_fingerprint,
            scope=authorization.scope,
            proposed_cost=authorization.proposed_cost,
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=authorization.reason_codes,
            evidence_refs=authorization.evidence_refs,
            evidence=authorization.evidence,
            compliance=authorization.compliance,
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )

    @staticmethod
    def _supplier_from_row(row) -> SupplierRecord:
        values = dict(row)
        for field in ("provider_observed_at", "created_at", "updated_at"):
            value = values[field]
            if value.tzinfo is None:
                values[field] = value.replace(tzinfo=dt.UTC)
        return SupplierRecord.model_validate(values)

    def _supplier_in_transaction(self, connection, supplier_ref: str) -> SupplierRecord:
        row = (
            connection.execute(
                sa.select(acquisition_supplier).where(
                    acquisition_supplier.c.supplier_ref == supplier_ref
                )
            )
            .mappings()
            .one()
        )
        return self._supplier_from_row(row)

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("company research clock must be timezone-aware")
        return value


__all__ = ["CompanyResearchService"]
