"""Authoritative offline orchestration for deterministic acquisition compliance."""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable
from decimal import Decimal

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Connection, Engine

from signals.acquisition.contracts import (
    AcquisitionState,
    ActorType,
    Decision,
    EventType,
    OpportunityConcurrencyConflict,
)
from signals.acquisition.store import AcquisitionStore
from signals.company_research.contracts import PREBUILD_VERSION, SIZE_BAND_VERSION
from signals.company_research.store import CompanyResearchStore
from signals.compliance.contracts import (
    BusinessContextState,
    CHLegalBasis,
    ComplianceAssessmentWrite,
    ComplianceAuthorizationInput,
    ComplianceDisposition,
    ComplianceInput,
    EmailProvenance,
    SenderComplianceConfig,
)
from signals.compliance.jurisdiction import resolve_jurisdiction
from signals.compliance.rules import RULESET_V1, evaluate_compliance
from signals.compliance.store import (
    ComplianceAssessmentIdempotencyConflict,
    ComplianceAssessmentStore,
    SuppressionStore,
    compliance_assessment_id,
)
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.contracts import PROFILE_VERSION as CONTACT_PROFILE_VERSION
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.decision_engine.policy import semantic_fingerprint
from signals.decision_engine.service import _legacy_budget_usage_candidates
from signals.persistence.schema import (
    acquisition_event,
    acquisition_personalization_artifact,
)
from signals.policy.contracts import (
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    PolicyEvaluationIdempotencyConflict,
    PolicyRequest,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row
from signals.supplier_discovery.contracts import SupplierIdentityStatus
from signals.supplier_discovery.store import SupplierDiscoveryStore

_COMPLIANCE_EVIDENCE = (
    "ACQUISITION_DECISION",
    "PUBLIC_EVIDENCE",
    "VERIFIED_CONTACT",
    "ACQUISITION_PROSPECT_PREBUILD",
    "PERSONALIZATION_ARTIFACT",
    "COMPLIANCE_INPUT",
)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ComplianceNotActionable(ValueError):
    pass


class ComplianceBindingConflict(ValueError):
    pass


class CompliancePersonalizationNotReady(ValueError):
    pass


class ComplianceEvaluationRequiresFreshAttempt(RuntimeError):
    pass


class ComplianceInputChanged(RuntimeError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _action_fingerprint(
    *, opportunity_id: str, supplier_ref: str, contact_ref: str, proposal_fingerprint: str
) -> str:
    return semantic_fingerprint(
        {
            "kind": "compliance-policy-action-v1",
            "command": "assess_campaign_compliance",
            "acquisition_opportunity_id": opportunity_id,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "proposal_fingerprint": proposal_fingerprint,
        }
    )


class ComplianceService:
    def __init__(
        self,
        engine: Engine,
        *,
        keyring: SuppressionIdentityKeyring,
        sender_config: SenderComplianceConfig,
        clock: Callable[[], dt.datetime] = _utc_now,
        policy_gateway: PolicyGateway | None = None,
        expected_contact_profile_version: str = CONTACT_PROFILE_VERSION,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._keyring = keyring
        self._sender_config = sender_config
        self._expected_contact_profile_version = expected_contact_profile_version
        self._acquisition = AcquisitionStore(engine)
        self._companies = CompanyResearchStore(engine)
        self._contacts = ContactDiscoveryStore(engine)
        self._suppliers = SupplierDiscoveryStore(engine)
        self._suppressions = SuppressionStore(engine, keyring)
        self._assessments = ComplianceAssessmentStore(engine)
        self._policy_store = PolicyStore(engine)
        self._policy = policy_gateway or PolicyGateway(engine, acquisition_store=self._acquisition)
        # Deterministic test seam; production composition leaves it a no-op.
        self._after_policy_hook: Callable[[], None] = lambda: None
        self._after_revalidation_hook: Callable[[], None] = lambda: None

    def assess(
        self,
        opportunity_id: str,
        authorization: ComplianceAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ):
        existing = self._assessments.get_by_policy(authorization.evaluation_id)
        if existing is not None:
            self._require_existing(existing, opportunity_id, authorization)
            return existing
        with self._engine.connect() as connection:
            if self._policy_store.evaluation_row(connection, authorization.evaluation_id):
                raise ComplianceEvaluationRequiresFreshAttempt(authorization.evaluation_id)

        captured_at = self._now()
        values = self._build_values(self._load(opportunity_id, captured_at), captured_at)
        request = self._request(
            authorization, values, expected_version=values["opportunity"].stream_version
        )
        try:
            decision = self._policy.evaluate_and_record(
                request, evaluated_at=captured_at, budget_usage=budget_usage
            )
        except PolicyEvaluationIdempotencyConflict as error:
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id) from error
        except OpportunityConcurrencyConflict:
            concurrent = self._await_concurrent_result(
                authorization.evaluation_id, opportunity_id, authorization
            )
            if concurrent is not None:
                return concurrent
            raise ComplianceInputChanged(opportunity_id)
        self._after_policy_hook()
        expected_post_policy_version = values["opportunity"].stream_version + 1
        if not decision.executable:
            return self._commit_blocked(values, decision, captured_at, expected_post_policy_version)
        return self._commit_recorded(
            opportunity_id,
            values,
            decision,
            expected_post_policy_version,
            captured_at,
            authorization,
        )

    def _load(self, opportunity_id: str, assessed_at: dt.datetime):
        with self._engine.connect() as connection:
            current = self._acquisition.get_opportunity_in_transaction(
                connection, opportunity_id, for_update=False
            )
            return self._load_in_transaction(
                connection,
                opportunity_id,
                current=current,
                assessed_at=assessed_at,
            )

    def _load_in_transaction(
        self,
        connection: Connection,
        opportunity_id: str,
        *,
        current,
        assessed_at: dt.datetime,
        lock_contact: bool = False,
    ):
        self._require_actionable(current)
        assert current.supplier_ref is not None
        assert current.contact_ref is not None
        artifact = (
            connection.execute(
                sa.select(acquisition_personalization_artifact)
                .where(
                    acquisition_personalization_artifact.c.acquisition_opportunity_id
                    == opportunity_id,
                    acquisition_personalization_artifact.c.disposition == "READY",
                )
                .order_by(acquisition_personalization_artifact.c.created_at.desc())
            )
            .mappings()
            .first()
        )
        if artifact is None:
            raise CompliancePersonalizationNotReady(opportunity_id)
        event = (
            connection.execute(
                sa.select(acquisition_event).where(
                    acquisition_event.c.event_id == artifact["recorded_event_id"],
                    acquisition_event.c.event_type == EventType.NEXT_ACTION_SET.value,
                )
            )
            .mappings()
            .one_or_none()
        )
        if event is None or event["payload"].get("next_action") != "assess_campaign_compliance":
            raise CompliancePersonalizationNotReady(opportunity_id)
        try:
            supplier = self._suppliers.get_supplier_in_transaction(connection, current.supplier_ref)
            contact = self._contacts.get_contact_in_transaction(
                connection, current.contact_ref, for_update=lock_contact
            )
            profile = self._companies.get_profile_in_transaction(connection, opportunity_id)
        except (sa.exc.NoResultFound, ValidationError) as error:
            raise ComplianceBindingConflict(opportunity_id) from error
        self._require_bindings(current, artifact, supplier, contact, profile)
        # A durable objection is a hard boundary even when it arrived after the
        # assessment clock was captured. `effective_at` is retained as
        # provenance, never as an outreach-reactivation mechanism.
        suppression = self._suppressions.match_contact_in_transaction(
            connection, contact.contact_ref
        )
        return current, artifact, supplier, contact, profile, suppression

    @staticmethod
    def _require_actionable(opportunity) -> None:
        if not (
            opportunity.state is AcquisitionState.SEND
            and opportunity.decision is Decision.SEND
            and opportunity.next_action == "assess_campaign_compliance"
            and opportunity.supplier_ref
            and opportunity.contact_ref
        ):
            raise ComplianceNotActionable(opportunity.acquisition_opportunity_id)

    def _require_bindings(self, opportunity, artifact, supplier, contact, profile) -> None:
        snapshot = artifact["input_snapshot"]
        if not (
            artifact["supplier_ref"] == opportunity.supplier_ref == supplier.supplier_ref
            and artifact["contact_ref"] == opportunity.contact_ref == contact.contact_ref
            and profile.acquisition_opportunity_id == opportunity.acquisition_opportunity_id
            and profile.signal_ref == opportunity.signal_ref
            and profile.supplier_ref == supplier.supplier_ref
            and profile.contact_ref == contact.contact_ref
            and profile.prebuild_version == PREBUILD_VERSION
            and profile.size_band_version == SIZE_BAND_VERSION
            and snapshot.get("company_prebuild_fingerprint") == profile.prebuild_fingerprint
            and contact.supplier_ref == supplier.supplier_ref
            and contact.verification_state == "PROVIDER_VERIFIED"
            and contact.verification_provider == "apollo"
            and contact.provider_email_status == "verified"
            and contact.role_profile_version == self._expected_contact_profile_version
            and profile.contact_role_profile_version == self._expected_contact_profile_version
            and contact.role_profile_version == profile.contact_role_profile_version
            and contact.role_tier == profile.contact_role_tier
            and supplier.identity_status is SupplierIdentityStatus.PROVIDER_IDENTIFIED
            and profile.supplier_identity_status is SupplierIdentityStatus.PROVIDER_IDENTIFIED
        ):
            raise ComplianceBindingConflict(opportunity.acquisition_opportunity_id)

    def _build_values(self, loaded, captured_at: dt.datetime) -> dict[str, object]:
        opportunity, artifact, supplier, contact, profile, suppression = loaded
        jurisdiction = resolve_jurisdiction(
            supplier_country_code=supplier.country_code,
            provider_country=profile.provider_country,
            supplier_ref=supplier.supplier_ref,
            profile_ref=f"acquisition-company-profile:{opportunity.acquisition_opportunity_id}",
        )
        business_context = (
            BusinessContextState.PROFESSIONAL_CONTEXT_VERIFIED
            if contact.role_tier in {1, 2, 3}
            else BusinessContextState.BUSINESS_CONTEXT_INSUFFICIENT
        )
        public_refs = tuple(artifact["input_snapshot"].get("public_evidence_refs", ()))
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *suppression.suppression_refs,
                    f"acquisition-personalization:{artifact['personalization_artifact_id']}",
                    f"acquisition-decision:{artifact['decision_evaluation_id']}",
                    *public_refs,
                    f"acquisition-contact:{contact.contact_ref}",
                    f"acquisition-supplier:{supplier.supplier_ref}",
                    f"acquisition-company-profile:{opportunity.acquisition_opportunity_id}",
                    *jurisdiction.evidence_refs,
                )
            )
        )[:16]
        assert RULESET_V1.config_fingerprint is not None
        assert self._sender_config.config_fingerprint is not None
        input_values = {
            "acquisition_opportunity_id": opportunity.acquisition_opportunity_id,
            "supplier_ref": supplier.supplier_ref,
            "contact_ref": contact.contact_ref,
            "personalization_artifact_id": artifact["personalization_artifact_id"],
            "personalization_artifact_fingerprint": artifact["artifact_fingerprint"],
            "personalization_input_fingerprint": artifact["input_fingerprint"],
            "personalization_proposal_fingerprint": artifact["proposal_fingerprint"],
            "personalization_policy_action_fingerprint": artifact["policy_action_fingerprint"],
            "language": artifact["language"],
            "supplier_identity_status": supplier.identity_status.value,
            "contact_verification_state": contact.verification_state,
            "contact_verification_provider": contact.verification_provider,
            "contact_provider_email_status": contact.provider_email_status,
            "contact_source_fingerprint": contact.source_fingerprint,
            "contact_role_profile_version": contact.role_profile_version,
            "contact_role_tier": contact.role_tier,
            "jurisdiction": jurisdiction,
            "business_context_state": business_context,
            "email_provenance": EmailProvenance.PROVIDER_VERIFIED_BUSINESS_CONTACT,
            "sender_config": self._sender_config,
            "acquisition_purpose": "KIVOU_ACQUISITION_SIGNAL_RELEVANCE",
            # No durable proof source exists in current acquisition persistence.
            "ch_legal_basis": CHLegalBasis.UNPROVEN,
            "suppression_match_state": suppression.state,
            "suppression_key_versions_considered": suppression.key_versions_considered,
            "evidence_refs": evidence_refs,
            "ruleset_config_fingerprint": RULESET_V1.config_fingerprint,
            "ruleset_legal_review_ref": RULESET_V1.legal_review_ref,
            "ruleset_effective_from": RULESET_V1.effective_from,
            "ruleset_valid_until": RULESET_V1.valid_until,
            "assessed_at": captured_at,
            "as_of_date": captured_at.date(),
        }
        input_fingerprint = semantic_fingerprint(
            {
                "kind": "acquisition-compliance-input-v1",
                **{
                    key: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value)
                    for key, value in input_values.items()
                },
            }
        )
        compliance_input = ComplianceInput(
            **input_values, compliance_input_fingerprint=input_fingerprint
        )
        proposal = evaluate_compliance(compliance_input, RULESET_V1)
        action_fingerprint = _action_fingerprint(
            opportunity_id=opportunity.acquisition_opportunity_id,
            supplier_ref=supplier.supplier_ref,
            contact_ref=contact.contact_ref,
            proposal_fingerprint=proposal.proposal_fingerprint,
        )
        return {
            "opportunity": opportunity,
            "artifact": artifact,
            "supplier": supplier,
            "contact": contact,
            "profile": profile,
            "suppression": suppression,
            "input": compliance_input,
            "input_fingerprint": input_fingerprint,
            "input_snapshot": compliance_input.model_dump(mode="json"),
            "proposal": proposal,
            "proposal_fingerprint": proposal.proposal_fingerprint,
            "action_fingerprint": action_fingerprint,
        }

    @staticmethod
    def _internal_evidence(authorization: ComplianceAuthorizationInput) -> EvidenceReadiness:
        evidence = authorization.evidence
        return EvidenceReadiness(
            status=evidence.status,
            claims=_COMPLIANCE_EVIDENCE,
            assessment_version=evidence.assessment_version,
            observed_at=evidence.observed_at,
            valid_until=evidence.valid_until,
        )

    @staticmethod
    def _pending_compliance(observed_at: dt.datetime) -> ComplianceAssessment:
        return ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="policy-compliance-pending-v1",
            observed_at=observed_at,
        )

    def _request(
        self,
        authorization: ComplianceAuthorizationInput,
        values: dict[str, object],
        *,
        expected_version: int,
    ) -> PolicyRequest:
        opportunity = values["opportunity"]
        supplier = values["supplier"]
        contact = values["contact"]
        proposal = values["proposal"]
        compliance_input = values["input"]
        if (
            authorization.scope.country != compliance_input.jurisdiction.country_code
            or authorization.scope.language != compliance_input.language
        ):
            raise ComplianceBindingConflict(compliance_input.acquisition_opportunity_id)
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="assess_campaign_compliance",
            target_ref=f"acquisition-opportunity:{opportunity.acquisition_opportunity_id}",
            acquisition_opportunity_id=opportunity.acquisition_opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=_canonical(
                {
                    "compliance_input_fingerprint": values["input_fingerprint"],
                    "compliance_proposal_fingerprint": values["proposal_fingerprint"],
                    "personalization_artifact_id": compliance_input.personalization_artifact_id,
                    "supplier_ref": supplier.supplier_ref,
                    "contact_ref": contact.contact_ref,
                }
            ),
            action_fingerprint=values["action_fingerprint"],
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=("COMPLIANCE_PROPOSED",),
            evidence_refs=proposal.evidence_refs,
            evidence=self._internal_evidence(authorization),
            compliance=self._pending_compliance(compliance_input.assessed_at),
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )

    def _write(
        self,
        values,
        decision,
        disposition: ComplianceDisposition,
        created_at: dt.datetime,
        expected_post_policy_version: int,
        event_id: str | None = None,
    ) -> ComplianceAssessmentWrite:
        compliance_input = values["input"]
        proposal = values["proposal"]
        return ComplianceAssessmentWrite(
            compliance_assessment_id=compliance_assessment_id(decision.evaluation_id),
            acquisition_opportunity_id=compliance_input.acquisition_opportunity_id,
            personalization_artifact_id=compliance_input.personalization_artifact_id,
            supplier_ref=compliance_input.supplier_ref,
            contact_ref=compliance_input.contact_ref,
            policy_evaluation_id=decision.evaluation_id,
            jurisdiction=compliance_input.jurisdiction.jurisdiction,
            ruleset_config_fingerprint=compliance_input.ruleset_config_fingerprint,
            input_fingerprint=values["input_fingerprint"],
            proposal_fingerprint=values["proposal_fingerprint"],
            policy_action_fingerprint=values["action_fingerprint"],
            state=proposal.state,
            reason_codes=proposal.reason_codes,
            evidence_refs=proposal.evidence_refs,
            input_snapshot=values["input_snapshot"],
            valid_until=proposal.valid_until,
            policy_status=decision.status.value,
            policy_counterfactual_status=(
                decision.counterfactual_status.value if decision.counterfactual_status else None
            ),
            expected_post_policy_version=expected_post_policy_version,
            disposition=disposition,
            next_action=proposal.next_action,
            recorded_event_id=event_id,
            created_at=created_at,
        )

    def _commit_blocked(self, values, decision, created_at, expected):
        with self._engine.begin() as connection:
            row = self._policy_store.evaluation_row(connection, decision.evaluation_id)
            if row is None or row["action_fingerprint"] != values["action_fingerprint"]:
                raise ComplianceAssessmentIdempotencyConflict(decision.evaluation_id)
            return self._assessments.append_in_transaction(
                connection,
                self._write(
                    values,
                    decision,
                    ComplianceDisposition.POLICY_BLOCKED,
                    created_at,
                    expected,
                ),
            )

    def _commit_recorded(
        self,
        opportunity_id,
        values,
        decision,
        expected,
        captured_at,
        authorization,
    ):
        try:
            with self._engine.begin() as connection:
                current = self._acquisition.get_opportunity_in_transaction(
                    connection, opportunity_id, for_update=True
                )
                if current.stream_version != expected:
                    raise ComplianceInputChanged(opportunity_id)
                try:
                    rebuilt = self._build_values(
                        self._load_in_transaction(
                            connection,
                            opportunity_id,
                            current=current,
                            assessed_at=captured_at,
                            lock_contact=True,
                        ),
                        captured_at,
                    )
                except (
                    ComplianceBindingConflict,
                    ComplianceNotActionable,
                    CompliancePersonalizationNotReady,
                    ValidationError,
                    sa.exc.NoResultFound,
                ) as error:
                    raise ComplianceInputChanged(opportunity_id) from error
                self._after_revalidation_hook()
                if any(
                    rebuilt[key] != values[key]
                    for key in (
                        "input_fingerprint",
                        "proposal_fingerprint",
                        "action_fingerprint",
                    )
                ):
                    raise ComplianceInputChanged(opportunity_id)
                proposal = rebuilt["proposal"]
                mutation = self._acquisition.append_in_transaction(
                    connection,
                    opportunity_id,
                    event_type=EventType.NEXT_ACTION_SET,
                    expected_version=expected,
                    idempotency_key=f"compliance_next_action:{decision.evaluation_id}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-compliance",
                    reason_codes=proposal.reason_codes,
                    evidence_refs=proposal.evidence_refs,
                    policy_version=decision.policy_version,
                    payload={"next_action": proposal.next_action},
                    causation_id=decision.evaluation_id,
                    occurred_at=captured_at,
                )
                return self._assessments.append_in_transaction(
                    connection,
                    self._write(
                        rebuilt,
                        decision,
                        ComplianceDisposition.RECORDED,
                        captured_at,
                        expected,
                        mutation.event.event_id,
                    ),
                )
        except (ComplianceInputChanged, OpportunityConcurrencyConflict):
            existing = self._await_concurrent_result(
                decision.evaluation_id, opportunity_id, authorization
            )
            if existing is not None:
                return existing
            raise ComplianceInputChanged(opportunity_id)

    def _require_existing(self, existing, opportunity_id, authorization) -> None:
        if existing["acquisition_opportunity_id"] != opportunity_id:
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id)
        if existing["compliance_assessment_id"] != compliance_assessment_id(
            authorization.evaluation_id
        ):
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id)
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(connection, authorization.evaluation_id)
            policy_event = (
                connection.execute(
                    sa.select(acquisition_event.c.stream_sequence).where(
                        acquisition_event.c.acquisition_opportunity_id == opportunity_id,
                        acquisition_event.c.idempotency_key
                        == f"policy_evaluation:{authorization.evaluation_id}",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None or policy_event is None or row["request_id"] != authorization.request_id:
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id)
        historical = decision_from_row(row)
        control = self._policy_store.get_control(historical.policy_snapshot_id)
        historical_cost_used = control.daily_cost_cap - historical.cost_remaining
        historical_volume_used = control.daily_volume_cap - historical.volume_remaining
        if historical_cost_used < 0 or historical_volume_used < 0:
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id)
        request = self._replay_request(
            authorization,
            existing,
            expected_version=policy_event["stream_sequence"] - 1,
            observed_at=historical.evaluated_at,
        )
        budget = BudgetUsage(cost_used=historical_cost_used, volume_used=historical_volume_used)
        matches = row["semantic_fingerprint"] == self._policy.semantic_fingerprint(
            request,
            evaluated_at=historical.evaluated_at,
            budget_usage=budget,
            policy_snapshot_id=historical.policy_snapshot_id,
        )
        if not matches:
            matches = any(
                row["semantic_fingerprint"]
                == self._policy.semantic_fingerprint(
                    request,
                    evaluated_at=historical.evaluated_at,
                    budget_usage=candidate,
                    policy_snapshot_id=historical.policy_snapshot_id,
                    legacy_decimal_encoding=True,
                )
                for candidate in _legacy_budget_usage_candidates(
                    historical_cost_used, historical_volume_used
                )
            )
        if not matches:
            raise ComplianceAssessmentIdempotencyConflict(authorization.evaluation_id)

    def _replay_request(
        self, authorization, existing, *, expected_version: int, observed_at: dt.datetime
    ) -> PolicyRequest:
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="assess_campaign_compliance",
            target_ref=f"acquisition-opportunity:{existing['acquisition_opportunity_id']}",
            acquisition_opportunity_id=existing["acquisition_opportunity_id"],
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=_canonical(
                {
                    "compliance_input_fingerprint": existing["input_fingerprint"],
                    "compliance_proposal_fingerprint": existing["proposal_fingerprint"],
                    "personalization_artifact_id": existing["personalization_artifact_id"],
                    "supplier_ref": existing["supplier_ref"],
                    "contact_ref": existing["contact_ref"],
                }
            ),
            action_fingerprint=existing["policy_action_fingerprint"],
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=0,
            reason_codes=("COMPLIANCE_PROPOSED",),
            evidence_refs=tuple(existing["evidence_refs"]),
            evidence=self._internal_evidence(authorization),
            compliance=self._pending_compliance(observed_at),
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )

    def _await_concurrent_result(self, evaluation_id, opportunity_id, authorization):
        for _ in range(100):
            existing = self._assessments.get_by_policy(evaluation_id)
            if existing is not None:
                self._require_existing(existing, opportunity_id, authorization)
                return existing
            time.sleep(0.01)
        return None

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("compliance clock must be timezone-aware")
        return value.astimezone(dt.UTC)


__all__ = [
    "ComplianceAssessmentIdempotencyConflict",
    "ComplianceBindingConflict",
    "ComplianceEvaluationRequiresFreshAttempt",
    "ComplianceInputChanged",
    "ComplianceNotActionable",
    "CompliancePersonalizationNotReady",
    "ComplianceService",
]
