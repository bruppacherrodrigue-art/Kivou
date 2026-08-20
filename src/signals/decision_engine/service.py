"""Authoritative-clock orchestration for deterministic acquisition decisions."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from signals.acquisition.contracts import (
    AcquisitionState,
    ActorType,
    EventType,
    OpportunityConcurrencyConflict,
)
from signals.acquisition.store import AcquisitionStore
from signals.company_research.contracts import PREBUILD_VERSION, SIZE_BAND_VERSION
from signals.company_research.store import CompanyResearchStore
from signals.decision_engine.contracts import (
    AcquisitionDecisionInput,
    AcquisitionDecisionProposal,
    DecisionAuditDisposition,
    DecisionAuthorizationInput,
    DecisionBindingConflict,
    DecisionCompanyProfileMissing,
    DecisionEvaluationIdempotencyConflict,
    DecisionEvaluationRequiresFreshAttempt,
    DecisionEvaluationWrite,
    DecisionInputChanged,
    DecisionInputVersionUnsupported,
    DecisionNotActionable,
    DecisionPublicContextNotResolvable,
    DecisionServiceResult,
)
from signals.decision_engine.evaluator import evaluate_decision
from signals.decision_engine.input import (
    build_acquisition_decision_input,
    build_public_decision_context,
)
from signals.decision_engine.policy import DECISION_POLICY_V1, semantic_fingerprint
from signals.decision_engine.store import DecisionEvaluationStore, decision_evaluation_id
from signals.persistence.schema import policy_evaluation
from signals.policy.contracts import BudgetUsage, PolicyRequest
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row
from signals.supplier_discovery.seed import (
    AcquisitionSeedNotFound,
    PublicAcquisitionContext,
    resolve_public_acquisition_context,
    resolve_public_acquisition_context_in_transaction,
)
from signals.supplier_discovery.store import SupplierDiscoveryStore


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def policy_action_fingerprint(
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    contact_ref: str,
    proposal_fingerprint: str,
) -> str:
    return semantic_fingerprint(
        {
            "fingerprint_kind": "decision-policy-action-v1",
            "command": "evaluate_opportunity",
            "acquisition_opportunity_id": acquisition_opportunity_id,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "proposal_fingerprint": proposal_fingerprint,
        }
    )


def _publication_date(value: dt.date | dt.datetime | None) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
        return aware.astimezone(dt.UTC).date()
    return value


def _proposal_from_audit(audit) -> AcquisitionDecisionProposal:
    return AcquisitionDecisionProposal(
        proposed_decision=audit.proposed_decision,
        reason_codes=audit.reason_codes,
        evidence_refs=audit.evidence_refs,
        next_action=audit.proposed_next_action,
        next_review_at=audit.proposed_next_review_at,
        decision_input_fingerprint=audit.decision_input_fingerprint,
        decision_policy_version=audit.decision_policy_version,
        proposal_fingerprint=audit.proposal_fingerprint,
        confidence=None,
    )


class DecisionEngineService:
    def __init__(
        self,
        engine: Engine,
        *,
        policy_gateway: PolicyGateway | None = None,
        acquisition_store: AcquisitionStore | None = None,
        company_store: CompanyResearchStore | None = None,
        supplier_store: SupplierDiscoveryStore | None = None,
        decision_store: DecisionEvaluationStore | None = None,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        self._engine = engine
        self._acquisition = acquisition_store or AcquisitionStore(engine)
        self._companies = company_store or CompanyResearchStore(engine)
        self._suppliers = supplier_store or SupplierDiscoveryStore(engine)
        self._decisions = decision_store or DecisionEvaluationStore(engine)
        self._policy_store = PolicyStore(engine)
        self._policy = policy_gateway or PolicyGateway(
            engine, acquisition_store=self._acquisition
        )
        self._clock = clock
        self._after_policy_hook: Callable[[], None] = lambda: None

    def evaluate(
        self,
        opportunity_id: str,
        authorization: DecisionAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> DecisionServiceResult:
        existing = self._decisions.get_by_policy(authorization.evaluation_id)
        if existing is not None:
            self._require_existing_binding(
                existing,
                opportunity_id,
                authorization,
                budget_usage=budget_usage,
            )
            return DecisionServiceResult(
                decision=self._policy_decision(authorization.evaluation_id),
                audit=existing,
                proposal=_proposal_from_audit(existing),
            )
        with self._engine.connect() as connection:
            if self._policy_store.evaluation_row(connection, authorization.evaluation_id):
                raise DecisionEvaluationRequiresFreshAttempt(authorization.evaluation_id)

        decision_evaluated_at = self._now()
        as_of_date = decision_evaluated_at.astimezone(dt.UTC).date()
        opportunity, supplier, contact, profile, public = self._load_inputs(opportunity_id)
        decision_input = self._build_input(
            opportunity, supplier, contact, profile, public, as_of_date
        )
        proposal = evaluate_decision(decision_input, DECISION_POLICY_V1)
        action_fingerprint = policy_action_fingerprint(
            acquisition_opportunity_id=opportunity_id,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
            proposal_fingerprint=proposal.proposal_fingerprint,
        )
        decision = self._policy.evaluate_and_record(
            self._policy_request(
                authorization,
                opportunity_id=opportunity_id,
                expected_version=opportunity.stream_version,
                decision_input=decision_input,
                proposal=proposal,
                action_fingerprint=action_fingerprint,
            ),
            evaluated_at=decision_evaluated_at,
            budget_usage=budget_usage,
        )
        self._after_policy_hook()
        expected_post_policy_version = opportunity.stream_version + 1
        if not decision.executable:
            audit = self._commit_policy_blocked(
                decision_input=decision_input,
                proposal=proposal,
                decision=decision,
                expected_post_policy_version=expected_post_policy_version,
                created_at=decision_evaluated_at,
            )
            return DecisionServiceResult(decision=decision, audit=audit, proposal=proposal)

        try:
            audit = self._commit_recorded(
                opportunity_id=opportunity_id,
                decision_input=decision_input,
                proposal=proposal,
                decision=decision,
                expected_post_policy_version=expected_post_policy_version,
                as_of_date=as_of_date,
                created_at=decision_evaluated_at,
            )
        except DecisionInputChanged:
            concurrent = self._decisions.get_by_policy(authorization.evaluation_id)
            if concurrent is None:
                raise
            self._require_existing_binding(
                concurrent,
                opportunity_id,
                authorization,
                budget_usage=budget_usage,
            )
            return DecisionServiceResult(
                decision=self._policy_decision(authorization.evaluation_id),
                audit=concurrent,
                proposal=_proposal_from_audit(concurrent),
            )
        return DecisionServiceResult(decision=decision, audit=audit, proposal=proposal)

    def _commit_recorded(
        self,
        *,
        opportunity_id: str,
        decision_input: AcquisitionDecisionInput,
        proposal: AcquisitionDecisionProposal,
        decision,
        expected_post_policy_version: int,
        as_of_date: dt.date,
        created_at: dt.datetime,
    ):
        try:
            with self._engine.begin() as connection:
                current = self._acquisition.get_opportunity_in_transaction(
                    connection, opportunity_id, for_update=True
                )
                if current.stream_version != expected_post_policy_version:
                    raise OpportunityConcurrencyConflict(opportunity_id)
                current, supplier, contact, profile, public = self._load_inputs_in_transaction(
                    connection, opportunity_id, current=current
                )
                rebuilt = self._build_input(
                    current, supplier, contact, profile, public, as_of_date
                )
                reproposal = evaluate_decision(rebuilt, DECISION_POLICY_V1)
                if (
                    rebuilt.decision_input_fingerprint
                    != decision_input.decision_input_fingerprint
                    or reproposal.proposal_fingerprint != proposal.proposal_fingerprint
                ):
                    raise DecisionInputChanged(opportunity_id)
                mutation = self._acquisition.append_in_transaction(
                    connection,
                    opportunity_id,
                    event_type=EventType.DECISION_RECORDED,
                    expected_version=expected_post_policy_version,
                    idempotency_key=f"decision_recorded:{decision.evaluation_id}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-decision-engine",
                    reason_codes=proposal.reason_codes,
                    evidence_refs=proposal.evidence_refs,
                    policy_version=decision.policy_version,
                    skill_version=DECISION_POLICY_V1.policy_version,
                    confidence=None,
                    payload={
                        "decision": proposal.proposed_decision.value,
                        "next_action": proposal.next_action,
                        "next_review_at": None,
                    },
                    causation_id=decision.evaluation_id,
                    occurred_at=created_at,
                )
                return self._decisions.append_in_transaction(
                    connection,
                    self._audit_write(
                        rebuilt,
                        reproposal,
                        decision,
                        expected_post_policy_version=expected_post_policy_version,
                        disposition=DecisionAuditDisposition.RECORDED,
                        recorded_event_id=mutation.event.event_id,
                        created_at=created_at,
                    ),
                )
        except DecisionInputChanged:
            raise
        except (
            OpportunityConcurrencyConflict,
            DecisionNotActionable,
            DecisionCompanyProfileMissing,
            DecisionInputVersionUnsupported,
            DecisionBindingConflict,
            DecisionPublicContextNotResolvable,
            sa.exc.NoResultFound,
        ) as error:
            raise DecisionInputChanged(opportunity_id) from error

    def _commit_policy_blocked(
        self,
        *,
        decision_input: AcquisitionDecisionInput,
        proposal: AcquisitionDecisionProposal,
        decision,
        expected_post_policy_version: int,
        created_at: dt.datetime,
    ):
        with self._engine.begin() as connection:
            row = self._policy_store.evaluation_row(connection, decision.evaluation_id)
            expected_counterfactual = (
                decision.counterfactual_status.value
                if decision.counterfactual_status is not None
                else None
            )
            if row is None or not (
                row["request_id"] == decision.request_id
                and row["acquisition_opportunity_id"]
                == decision_input.acquisition_opportunity_id
                and row["command"] == "evaluate_opportunity"
                and row["target_ref"]
                == f"acquisition-opportunity:{decision_input.acquisition_opportunity_id}"
                and row["action_fingerprint"] == decision.action_fingerprint
                and row["status"] == decision.status.value
                and row["counterfactual_status"] == expected_counterfactual
                and row["executable"] is False
            ):
                raise DecisionEvaluationIdempotencyConflict(decision.evaluation_id)
            return self._decisions.append_in_transaction(
                connection,
                self._audit_write(
                    decision_input,
                    proposal,
                    decision,
                    expected_post_policy_version=expected_post_policy_version,
                    disposition=DecisionAuditDisposition.POLICY_BLOCKED,
                    recorded_event_id=None,
                    created_at=created_at,
                ),
            )

    def _load_inputs(self, opportunity_id: str):
        opportunity = self._acquisition.get_opportunity(opportunity_id)
        self._require_actionable(opportunity)
        try:
            profile = self._companies.get_profile(opportunity_id)
        except sa.exc.NoResultFound as error:
            raise DecisionCompanyProfileMissing(opportunity_id) from error
        assert opportunity.supplier_ref is not None
        assert opportunity.contact_ref is not None
        supplier = self._suppliers.get_supplier(opportunity.supplier_ref)
        contact = self._companies.get_contact_binding(opportunity.contact_ref)
        self._require_bindings(opportunity, supplier, contact, profile)
        public = self._resolve_public(opportunity.signal_ref)
        return opportunity, supplier, contact, profile, public

    def _load_inputs_in_transaction(self, connection: Connection, opportunity_id: str, *, current):
        self._require_actionable(current)
        try:
            profile = self._companies.get_profile_in_transaction(connection, opportunity_id)
        except sa.exc.NoResultFound as error:
            raise DecisionCompanyProfileMissing(opportunity_id) from error
        assert current.supplier_ref is not None
        assert current.contact_ref is not None
        supplier = self._suppliers.get_supplier_in_transaction(
            connection, current.supplier_ref
        )
        contact = self._companies.get_contact_binding_in_transaction(
            connection, current.contact_ref
        )
        self._require_bindings(current, supplier, contact, profile)
        opportunity_key = self._opportunity_key(current.signal_ref)
        try:
            public = resolve_public_acquisition_context_in_transaction(
                connection, opportunity_key
            )
        except AcquisitionSeedNotFound as error:
            raise DecisionPublicContextNotResolvable(current.signal_ref) from error
        return current, supplier, contact, profile, public

    def _resolve_public(self, signal_ref: str) -> PublicAcquisitionContext:
        opportunity_key = self._opportunity_key(signal_ref)
        try:
            return resolve_public_acquisition_context(self._engine, opportunity_key)
        except AcquisitionSeedNotFound as error:
            raise DecisionPublicContextNotResolvable(signal_ref) from error

    @staticmethod
    def _opportunity_key(signal_ref: str) -> str:
        prefix = "procurement-opportunity:"
        if not signal_ref.startswith(prefix) or not signal_ref[len(prefix) :]:
            raise DecisionPublicContextNotResolvable(signal_ref)
        return signal_ref[len(prefix) :]

    @staticmethod
    def _require_actionable(opportunity) -> None:
        if not (
            opportunity.state is AcquisitionState.READY_FOR_DECISION
            and opportunity.next_action == "evaluate_opportunity"
            and opportunity.supplier_ref is not None
            and opportunity.contact_ref is not None
        ):
            raise DecisionNotActionable(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _require_bindings(opportunity, supplier, contact, profile) -> None:
        if profile.prebuild_version != PREBUILD_VERSION or profile.size_band_version != SIZE_BAND_VERSION:
            raise DecisionInputVersionUnsupported(opportunity.acquisition_opportunity_id)
        if not (
            profile.acquisition_opportunity_id == opportunity.acquisition_opportunity_id
            and profile.supplier_ref == opportunity.supplier_ref == supplier.supplier_ref
            and profile.contact_ref == opportunity.contact_ref == contact.contact_ref
            and profile.signal_ref == opportunity.signal_ref
            and contact.supplier_ref == supplier.supplier_ref
            and contact.verification_state == "PROVIDER_VERIFIED"
            and contact.verification_provider == "apollo"
            and contact.provider_email_status == "verified"
        ):
            raise DecisionBindingConflict(opportunity.acquisition_opportunity_id)

    @staticmethod
    def _build_input(opportunity, supplier, contact, profile, public, as_of_date):
        public_context = build_public_decision_context(
            opportunity_key=public.opportunity_key,
            representative_award_key=public.representative_award_key,
            source_event_key=public.event.ref().key(),
            award_date=public.award.award_date,
            contract_notification_date=public.award.contract_notification_date,
            publication_date=_publication_date(public.event.published_at),
            public_evidence_refs=public.public_evidence_refs,
        )
        return build_acquisition_decision_input(
            acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
            signal_ref=opportunity.signal_ref,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
            company_prebuild_version=profile.prebuild_version,
            company_prebuild_fingerprint=profile.prebuild_fingerprint,
            size_band_version=profile.size_band_version,
            profile_supplier_identity_status=profile.supplier_identity_status,
            current_supplier_identity_status=supplier.identity_status,
            profile_contact_role_profile_version=profile.contact_role_profile_version,
            profile_contact_role_tier=profile.contact_role_tier,
            current_contact_role_profile_version=contact.role_profile_version,
            current_contact_role_tier=contact.role_tier,
            current_contact_verification_state=contact.verification_state,
            current_contact_verification_provider=contact.verification_provider,
            current_contact_provider_email_status=contact.provider_email_status,
            research_completeness=profile.research_completeness,
            research_gaps=tuple(gap.value for gap in profile.research_gaps),
            size_band=profile.size_band,
            public_context=public_context,
            as_of_date=as_of_date,
            policy_config=DECISION_POLICY_V1,
        )

    @staticmethod
    def _policy_request(
        authorization,
        *,
        opportunity_id,
        expected_version,
        decision_input,
        proposal,
        action_fingerprint,
    ) -> PolicyRequest:
        arguments = _canonical_json(
            {
                "decision_input_fingerprint": decision_input.decision_input_fingerprint,
                "proposal_fingerprint": proposal.proposal_fingerprint,
                "supplier_ref": decision_input.supplier_ref,
                "contact_ref": decision_input.contact_ref,
            }
        )
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="evaluate_opportunity",
            target_ref=f"acquisition-opportunity:{opportunity_id}",
            acquisition_opportunity_id=opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            canonical_arguments=arguments,
            action_fingerprint=action_fingerprint,
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=proposal.reason_codes,
            evidence_refs=proposal.evidence_refs,
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
    def _audit_write(
        decision_input,
        proposal,
        decision,
        *,
        expected_post_policy_version,
        disposition,
        recorded_event_id,
        created_at,
    ) -> DecisionEvaluationWrite:
        return DecisionEvaluationWrite(
            decision_evaluation_id=decision_evaluation_id(decision.evaluation_id),
            acquisition_opportunity_id=decision_input.acquisition_opportunity_id,
            policy_evaluation_id=decision.evaluation_id,
            decision_input=decision_input,
            proposal=proposal,
            policy_status=decision.status,
            policy_counterfactual_status=decision.counterfactual_status,
            expected_post_policy_version=expected_post_policy_version,
            disposition=disposition,
            recorded_event_id=recorded_event_id,
            created_at=created_at,
        )

    def _require_existing_binding(
        self,
        audit,
        opportunity_id,
        authorization,
        *,
        budget_usage: BudgetUsage,
    ) -> None:
        decision_input = AcquisitionDecisionInput.model_validate(audit.decision_input)
        proposal = _proposal_from_audit(audit)
        expected_action = policy_action_fingerprint(
            acquisition_opportunity_id=audit.acquisition_opportunity_id,
            supplier_ref=decision_input.supplier_ref,
            contact_ref=decision_input.contact_ref,
            proposal_fingerprint=audit.proposal_fingerprint,
        )
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(connection, authorization.evaluation_id)
        if row is None or audit.acquisition_opportunity_id != opportunity_id:
            raise DecisionEvaluationIdempotencyConflict(authorization.evaluation_id)
        existing_decision = decision_from_row(row)
        request = self._policy_request(
            authorization,
            opportunity_id=opportunity_id,
            expected_version=audit.expected_post_policy_version - 1,
            decision_input=decision_input,
            proposal=proposal,
            action_fingerprint=expected_action,
        )
        reconstructed = self._policy.semantic_fingerprint(
            request,
            evaluated_at=existing_decision.evaluated_at,
            budget_usage=budget_usage,
            policy_snapshot_id=existing_decision.policy_snapshot_id,
        )
        if row["semantic_fingerprint"] != reconstructed:
            raise DecisionEvaluationIdempotencyConflict(authorization.evaluation_id)

    def _policy_decision(self, evaluation_id: str):
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(policy_evaluation).where(
                    policy_evaluation.c.evaluation_id == evaluation_id
                )
            ).mappings().one()
        return decision_from_row(row)

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision engine clock must be timezone-aware")
        return value.astimezone(dt.UTC)


__all__ = ["DecisionEngineService", "policy_action_fingerprint"]
