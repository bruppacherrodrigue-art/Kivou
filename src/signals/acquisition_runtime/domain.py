"""Concrete, bounded composition of Kivou's existing acquisition domains."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from functools import wraps
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import AcquisitionState, Decision
from signals.acquisition_runtime.actions import (
    KivouDomainDisposition,
    KivouDomainOutcome,
)
from signals.acquisition_runtime.contracts import RuntimeQaScope, RuntimeStageSnapshot
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.campaigns.contracts import (
    CampaignAuthorizationInput,
    CampaignDeploymentBlocked,
    CampaignInputChanged,
    CampaignNotActionable,
    CampaignPacingExceeded,
    ProviderOperationKind,
    ProviderOperationState,
)
from signals.campaigns.service import CampaignScheduleResult
from signals.company_research.contracts import (
    CompanyResearchAuthorizationInput,
    CompanyResearchServiceResult,
)
from signals.compliance.contracts import (
    ComplianceAssessmentWrite,
    ComplianceAuthorizationInput,
    ComplianceDisposition,
)
from signals.contact_discovery.contracts import (
    ContactAuthorizationInput,
    ContactDiscoveryServiceResult,
)
from signals.decision_engine.contracts import (
    DecisionAuditDisposition,
    DecisionAuthorizationInput,
    DecisionServiceResult,
)
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_company_profile,
    acquisition_compliance_assessment,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_decision_evaluation,
    acquisition_opportunity,
    acquisition_personalization_artifact,
    acquisition_provider_operation,
    acquisition_response_evaluation,
)
from signals.personalization.contracts import (
    PersonalizationArtifactWrite,
    PersonalizationDisposition,
)
from signals.personalization.grounding import PersonalizationDecisionNoLongerEligible
from signals.policy.contracts import ApprovalGrant, BudgetUsage, PolicyStatus
from signals.supplier_discovery.contracts import (
    DiscoveryAuthorizationInput,
    DiscoveryServiceResult,
    SupplierSearchNotActionable,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.seed import (
    AcquisitionSeedNotFound,
    resolve_public_acquisition_context,
)


@dataclass(frozen=True)
class DomainAttemptIdentity:
    evaluation_id: str
    request_id: str
    run_id: str
    correlation_id: str


def _attempt_ref(kind: str, attempt_ref: str) -> str:
    return hashlib.sha256(
        f"acquisition-runtime-domain-v1\0{kind}\0{attempt_ref}".encode()
    ).hexdigest()


def deterministic_attempt_identity(
    stage_snapshot: RuntimeStageSnapshot,
) -> DomainAttemptIdentity:
    """Derive replay-stable IDs; a durable new attempt receives fresh IDs."""

    attempt_ref = stage_snapshot.attempt_ref
    return DomainAttemptIdentity(
        evaluation_id=_attempt_ref("evaluation", attempt_ref),
        request_id=_attempt_ref("request", attempt_ref),
        run_id=_attempt_ref("run", attempt_ref),
        correlation_id=_attempt_ref("correlation", attempt_ref),
    )


@dataclass(frozen=True)
class OpportunityTruth:
    opportunity_id: str
    state: AcquisitionState
    supplier_ref: str | None = None
    contact_ref: str | None = None
    campaign_ref: str | None = None
    decision: Decision | None = None


@dataclass(frozen=True)
class DecisionTruth:
    evaluation_ref: str
    decision: Decision
    disposition: DecisionAuditDisposition = DecisionAuditDisposition.RECORDED
    policy_status: PolicyStatus = PolicyStatus.APPROVED


@dataclass(frozen=True)
class PersonalizationTruth:
    artifact_ref: str
    disposition: PersonalizationDisposition
    policy_status: PolicyStatus = PolicyStatus.APPROVED


@dataclass(frozen=True)
class ComplianceTruth:
    assessment_ref: str
    disposition: ComplianceDisposition
    state: str


@dataclass(frozen=True)
class CampaignTruth:
    campaign_ref: str
    member_ref: str
    transport_recipient_identity: str | None = None
    transport_recipient_key_version: str | None = None


@dataclass(frozen=True)
class ProviderOperationTruth:
    operation_ref: str
    kind: ProviderOperationKind
    state: ProviderOperationState
    desired_request_fingerprint: str = "0" * 64
    retry_at: dt.datetime | None = None


@dataclass(frozen=True)
class ResponseTruth:
    response_ref: str
    classification: str


class DomainTransientFailure(RuntimeError):
    """A bounded retryable condition without provider response text."""

    def __init__(
        self,
        code: str = "DOMAIN_RETRYABLE",
        *,
        retry_at: dt.datetime | None = None,
    ) -> None:
        safe_code = code if re.fullmatch(r"[A-Z0-9][A-Z0-9_:-]{0,99}", code) else "DOMAIN_RETRYABLE"
        super().__init__(safe_code)
        self.code = safe_code
        self.retry_at = retry_at


class DomainAmbiguousFailure(RuntimeError):
    """Persisted business truth contains more than one eligible runtime target."""


class DomainApprovalRequired(RuntimeError):
    """A durable, exact human approval request exists but is not consumable yet."""

    def __init__(self) -> None:
        super().__init__("HUMAN_APPROVAL_REQUIRED")


@dataclass(frozen=True)
class AuthorizedCall[AuthorizationT]:
    authorization: AuthorizationT
    budget_usage: BudgetUsage
    language: str | None = None


class RuntimeApprovalProvider(Protocol):
    def consume_for(
        self,
        context: AcquisitionActionContext,
        *,
        opportunity_id: str | None,
        action_fingerprint: str | None = None,
    ) -> tuple[ApprovalGrant, ...]: ...


class RuntimePolicyAuthorizationFactory(Protocol):
    """Build native domain authorizations from live Policy/approval evidence."""

    def supplier(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
    ) -> AuthorizedCall[DiscoveryAuthorizationInput]: ...

    def contact(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[ContactAuthorizationInput]: ...

    def company(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[CompanyResearchAuthorizationInput]: ...

    def decision(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[DecisionAuthorizationInput]: ...

    def personalization(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[DecisionAuthorizationInput]: ...

    def compliance(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[ComplianceAuthorizationInput]: ...

    def campaign(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[CampaignAuthorizationInput]: ...


type DomainAuthorization = (
    DiscoveryAuthorizationInput
    | ContactAuthorizationInput
    | CompanyResearchAuthorizationInput
    | DecisionAuthorizationInput
    | ComplianceAuthorizationInput
    | CampaignAuthorizationInput
)


class AcquisitionDomainTruth(Protocol):
    def resolve_seed(self, opportunity_key: str) -> tuple[str, ...]: ...
    def signal_country(self, opportunity_key: str) -> str | None: ...
    def opportunity(self, opportunity_key: str) -> OpportunityTruth | None: ...
    def company_profile_ref(self, opportunity_id: str) -> str | None: ...
    def decision(self, opportunity_id: str) -> DecisionTruth | None: ...
    def personalization(self, opportunity_id: str) -> PersonalizationTruth | None: ...
    def compliance(self, opportunity_id: str) -> ComplianceTruth | None: ...
    def campaign(self, opportunity_id: str) -> CampaignTruth | None: ...
    def provider_operations(
        self, campaign_ref: str, member_ref: str
    ) -> tuple[ProviderOperationTruth, ...]: ...
    def response(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> ResponseTruth | None: ...
    def conversion_refs(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> tuple[str, ...]: ...


class _SupplierService(Protocol):
    def discover(
        self,
        opportunity_key: str,
        targeting: SupplierTargetingConfig,
        authorization: DiscoveryAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        discovery_run_id: str,
        correlation_id: str,
    ) -> DiscoveryServiceResult: ...


class _ContactService(Protocol):
    def find(
        self,
        opportunity_id: str,
        authorization: ContactAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        contact_discovery_run_id: str,
        correlation_id: str,
    ) -> ContactDiscoveryServiceResult: ...


class _CompanyService(Protocol):
    def research(
        self,
        opportunity_id: str,
        authorization: CompanyResearchAuthorizationInput,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
        company_research_run_id: str,
        correlation_id: str,
    ) -> CompanyResearchServiceResult: ...


class _DecisionService(Protocol):
    def evaluate(
        self,
        opportunity_id: str,
        authorization: DecisionAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> DecisionServiceResult: ...


class _PersonalizationService(Protocol):
    def personalize(
        self,
        opportunity_id: str,
        language: str,
        authorization: DecisionAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> PersonalizationArtifactWrite: ...


class _ComplianceService(Protocol):
    def assess(
        self,
        opportunity_id: str,
        authorization: ComplianceAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> ComplianceAssessmentWrite: ...


class _CampaignService(Protocol):
    def schedule(
        self,
        opportunity_id: str,
        authorization: CampaignAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> CampaignScheduleResult: ...


class _CampaignWorker(Protocol):
    def process(self, operation_ref: str, now: dt.datetime) -> ProviderOperationState: ...


def _closed_domain_action[ActionOwnerT](
    action: Callable[[ActionOwnerT, AcquisitionActionContext], KivouDomainOutcome],
) -> Callable[[ActionOwnerT, AcquisitionActionContext], KivouDomainOutcome]:
    @wraps(action)
    def execute(owner: ActionOwnerT, context: AcquisitionActionContext) -> KivouDomainOutcome:
        try:
            return action(owner, context)
        except DomainApprovalRequired:
            return _waiting("HUMAN_APPROVAL_REQUIRED")
        except DomainAmbiguousFailure:
            return _blocked("DOMAIN_TRUTH_AMBIGUOUS")
        except DomainTransientFailure:
            return _waiting("DOMAIN_RETRYABLE")

    return execute


class SqlAcquisitionDomainTruth:
    def __init__(
        self,
        engine: Engine,
        *,
        seed_resolver: Callable[[Engine, str], object] = (resolve_public_acquisition_context),
    ) -> None:
        self.engine = engine
        self._seed_resolver = seed_resolver

    def resolve_seed(self, opportunity_key: str) -> tuple[str, ...]:
        try:
            seed = self._seed_resolver(self.engine, opportunity_key)
        except AcquisitionSeedNotFound:
            return ()
        refs = getattr(seed, "public_evidence_refs", ())
        if not isinstance(refs, tuple) or any(
            not isinstance(item, str) or not item for item in refs
        ):
            raise DomainAmbiguousFailure("public acquisition seed is malformed")
        return refs

    def signal_country(self, opportunity_key: str) -> str | None:
        try:
            seed = self._seed_resolver(self.engine, opportunity_key)
        except AcquisitionSeedNotFound:
            return None
        country = getattr(
            getattr(getattr(seed, "event", None), "provenance", None),
            "source_country",
            None,
        )
        return str(country) if country in {"CH", "FR"} else None

    def opportunity(self, opportunity_key: str) -> OpportunityTruth | None:
        signal_ref = f"procurement-opportunity:{opportunity_key}"
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(
                        acquisition_opportunity.c.acquisition_opportunity_id,
                        acquisition_opportunity.c.state,
                        acquisition_opportunity.c.supplier_ref,
                        acquisition_opportunity.c.contact_ref,
                        acquisition_opportunity.c.campaign_ref,
                        acquisition_opportunity.c.decision,
                    )
                    .where(acquisition_opportunity.c.signal_ref == signal_ref)
                    .order_by(acquisition_opportunity.c.acquisition_opportunity_id)
                    .limit(2)
                )
                .mappings()
                .all()
            )
        if not rows:
            return None
        if len(rows) != 1:
            raise DomainAmbiguousFailure("multiple acquisition opportunities")
        row = rows[0]
        return OpportunityTruth(
            opportunity_id=row["acquisition_opportunity_id"],
            state=AcquisitionState(row["state"]),
            supplier_ref=row["supplier_ref"],
            contact_ref=row["contact_ref"],
            campaign_ref=row["campaign_ref"],
            decision=Decision(row["decision"]) if row["decision"] else None,
        )

    def company_profile_ref(self, opportunity_id: str) -> str | None:
        with self.engine.connect() as connection:
            return connection.execute(
                sa.select(acquisition_company_profile.c.prebuild_fingerprint).where(
                    acquisition_company_profile.c.acquisition_opportunity_id == opportunity_id
                )
            ).scalar_one_or_none()

    def decision(self, opportunity_id: str) -> DecisionTruth | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(
                        acquisition_decision_evaluation.c.decision_evaluation_id,
                        acquisition_decision_evaluation.c.proposed_decision,
                        acquisition_decision_evaluation.c.disposition,
                        acquisition_decision_evaluation.c.policy_status,
                    )
                    .where(
                        acquisition_decision_evaluation.c.acquisition_opportunity_id
                        == opportunity_id
                    )
                    .order_by(
                        acquisition_decision_evaluation.c.created_at.desc(),
                        acquisition_decision_evaluation.c.decision_evaluation_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return DecisionTruth(
            evaluation_ref=row["decision_evaluation_id"],
            decision=Decision(row["proposed_decision"]),
            disposition=DecisionAuditDisposition(row["disposition"]),
            policy_status=PolicyStatus(row["policy_status"]),
        )

    def personalization(self, opportunity_id: str) -> PersonalizationTruth | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(
                        acquisition_personalization_artifact.c.personalization_artifact_id,
                        acquisition_personalization_artifact.c.disposition,
                        acquisition_personalization_artifact.c.policy_status,
                    )
                    .where(
                        acquisition_personalization_artifact.c.acquisition_opportunity_id
                        == opportunity_id
                    )
                    .order_by(
                        acquisition_personalization_artifact.c.created_at.desc(),
                        acquisition_personalization_artifact.c.personalization_artifact_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return PersonalizationTruth(
            artifact_ref=row["personalization_artifact_id"],
            disposition=PersonalizationDisposition(row["disposition"]),
            policy_status=PolicyStatus(row["policy_status"]),
        )

    def compliance(self, opportunity_id: str) -> ComplianceTruth | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(
                        acquisition_compliance_assessment.c.compliance_assessment_id,
                        acquisition_compliance_assessment.c.disposition,
                        acquisition_compliance_assessment.c.state,
                    )
                    .where(
                        acquisition_compliance_assessment.c.acquisition_opportunity_id
                        == opportunity_id
                    )
                    .order_by(
                        acquisition_compliance_assessment.c.created_at.desc(),
                        acquisition_compliance_assessment.c.compliance_assessment_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ComplianceTruth(
            assessment_ref=row["compliance_assessment_id"],
            disposition=ComplianceDisposition(row["disposition"]),
            state=row["state"],
        )

    def campaign(self, opportunity_id: str) -> CampaignTruth | None:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(
                        acquisition_campaign_member.c.campaign_ref,
                        acquisition_campaign_member.c.member_ref,
                        acquisition_campaign_member.c.transport_recipient_identity,
                        acquisition_campaign_member.c.transport_recipient_key_version,
                    )
                    .where(
                        acquisition_campaign_member.c.acquisition_opportunity_id == opportunity_id
                    )
                    .order_by(
                        acquisition_campaign_member.c.created_at.desc(),
                        acquisition_campaign_member.c.member_ref.desc(),
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
        if not rows:
            return None
        if len(rows) != 1:
            raise DomainAmbiguousFailure("multiple acquisition campaign members")
        return CampaignTruth(
            campaign_ref=rows[0]["campaign_ref"],
            member_ref=rows[0]["member_ref"],
            transport_recipient_identity=rows[0]["transport_recipient_identity"],
            transport_recipient_key_version=rows[0]["transport_recipient_key_version"],
        )

    def provider_operations(
        self, campaign_ref: str, member_ref: str
    ) -> tuple[ProviderOperationTruth, ...]:
        order = sa.case(
            (acquisition_provider_operation.c.kind == "CREATE_CAMPAIGN", 1),
            (acquisition_provider_operation.c.kind == "CONFIGURE_CAMPAIGN", 2),
            (acquisition_provider_operation.c.kind == "ADD_LEAD", 3),
            else_=99,
        )
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    sa.select(
                        acquisition_provider_operation.c.operation_ref,
                        acquisition_provider_operation.c.kind,
                        acquisition_provider_operation.c.state,
                        acquisition_provider_operation.c.desired_request_fingerprint,
                        acquisition_provider_operation.c.retry_after,
                    )
                    .where(
                        acquisition_provider_operation.c.campaign_ref == campaign_ref,
                        sa.or_(
                            acquisition_provider_operation.c.member_ref.is_(None),
                            acquisition_provider_operation.c.member_ref == member_ref,
                        ),
                    )
                    .order_by(order, acquisition_provider_operation.c.operation_ref)
                )
                .mappings()
                .all()
            )
        return tuple(
            ProviderOperationTruth(
                operation_ref=row["operation_ref"],
                kind=ProviderOperationKind(row["kind"]),
                state=ProviderOperationState(row["state"]),
                desired_request_fingerprint=row["desired_request_fingerprint"],
                retry_at=(
                    _aware_time(row["retry_after"])
                    if row["retry_after"] is not None
                    else None
                ),
            )
            for row in rows
        )

    def response(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> ResponseTruth | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(
                        acquisition_response_evaluation.c.response_evaluation_id,
                        acquisition_response_evaluation.c.classification,
                    )
                    .where(
                        acquisition_response_evaluation.c.acquisition_opportunity_id
                        == opportunity_id,
                        acquisition_response_evaluation.c.campaign_ref
                        == campaign.campaign_ref,
                        acquisition_response_evaluation.c.member_ref
                        == campaign.member_ref,
                        acquisition_response_evaluation.c.processing_state == "FINALIZED",
                    )
                    .order_by(
                        acquisition_response_evaluation.c.finalized_at.desc(),
                        acquisition_response_evaluation.c.response_evaluation_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ResponseTruth(
            response_ref=row["response_evaluation_id"],
            classification=row["classification"],
        )

    def conversion_refs(
        self, opportunity_id: str, campaign: CampaignTruth
    ) -> tuple[str, ...]:
        with self.engine.connect() as connection:
            journeys = (
                connection.execute(
                    sa.select(acquisition_conversion_journey.c.journey_ref)
                    .where(
                        acquisition_conversion_journey.c.acquisition_opportunity_id
                        == opportunity_id,
                        acquisition_conversion_journey.c.campaign_ref
                        == campaign.campaign_ref,
                        acquisition_conversion_journey.c.member_ref
                        == campaign.member_ref,
                    )
                    .order_by(
                        acquisition_conversion_journey.c.created_at.desc(),
                        acquisition_conversion_journey.c.journey_ref.desc(),
                    )
                    .limit(2)
                )
                .scalars()
                .all()
            )
            if not journeys:
                return ()
            if len(journeys) != 1:
                raise DomainAmbiguousFailure("multiple conversion journeys")
            event_ref = connection.execute(
                sa.select(acquisition_conversion_event.c.conversion_event_ref)
                .where(
                    acquisition_conversion_event.c.journey_ref == journeys[0],
                    acquisition_conversion_event.c.acquisition_opportunity_id
                    == opportunity_id,
                    acquisition_conversion_event.c.campaign_ref
                    == campaign.campaign_ref,
                    acquisition_conversion_event.c.member_ref == campaign.member_ref,
                )
                .order_by(
                    acquisition_conversion_event.c.recorded_at.desc(),
                    acquisition_conversion_event.c.conversion_event_ref.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
        return (journeys[0],) if event_ref is None else (journeys[0], event_ref)


class AcquisitionDomainActions:
    """Compose native services and first converge from their durable truth."""

    def __init__(
        self,
        *,
        truth: AcquisitionDomainTruth,
        supplier_service: _SupplierService,
        contact_service: _ContactService,
        company_service: _CompanyService,
        decision_service: _DecisionService,
        personalization_service: _PersonalizationService,
        compliance_service: _ComplianceService,
        campaign_service: _CampaignService,
        campaign_worker: _CampaignWorker,
        authorization_factory: RuntimePolicyAuthorizationFactory,
        approval_provider: RuntimeApprovalProvider,
        maximum_provider_operations: int,
        qa_transport_recipient_identity: str,
        qa_transport_recipient_key_version: str,
        qa_scope: RuntimeQaScope,
        targeting: SupplierTargetingConfig | None = None,
    ) -> None:
        if not 1 <= maximum_provider_operations <= 4:
            raise ValueError("provider operation bound must be between one and four")
        selected_targeting = targeting or SupplierTargetingConfig(
            max_pages=1,
            per_page=1,
            candidate_cap=1,
        )
        if (
            selected_targeting.max_pages != 1
            or selected_targeting.per_page != 1
            or selected_targeting.candidate_cap != 1
        ):
            raise ValueError("runtime supplier discovery is capped at one candidate")
        self._truth = truth
        self._supplier = supplier_service
        self._contact = contact_service
        self._company = company_service
        self._decision = decision_service
        self._personalization = personalization_service
        self._compliance = compliance_service
        self._campaign = campaign_service
        self._worker = campaign_worker
        self._authorizations = authorization_factory
        self._approvals = approval_provider
        self._provider_cap = maximum_provider_operations
        if re.fullmatch(r"[0-9a-f]{64}", qa_transport_recipient_identity) is None:
            raise ValueError("QA transport recipient identity must be a SHA-256 HMAC")
        if (
            not qa_transport_recipient_key_version
            or len(qa_transport_recipient_key_version) > 64
        ):
            raise ValueError("QA transport recipient key version is invalid")
        self._qa_transport_binding = (
            qa_transport_recipient_identity,
            qa_transport_recipient_key_version,
        )
        self._qa_scope = qa_scope
        self._targeting = selected_targeting

    @_closed_domain_action
    def resolve_signal_seed(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        try:
            refs = self._truth.resolve_seed(context.cycle.opportunity_key)
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        if not refs:
            return _blocked("SIGNAL_SEED_NOT_FOUND")
        if self._truth.signal_country(context.cycle.opportunity_key) != self._qa_scope.country:
            return _blocked("QA_SCOPE_SIGNAL_MISMATCH")
        return _complete(*(("public", ref) for ref in refs))

    @_closed_domain_action
    def discover_supplier(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        existing = self._truth.opportunity(context.cycle.opportunity_key)
        if existing is not None and existing.supplier_ref is not None:
            return _complete(
                ("opportunity", existing.opportunity_id),
                ("supplier", existing.supplier_ref),
            )
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                identity = deterministic_attempt_identity(context.stage_snapshot)
                approvals = self._approvals.consume_for(
                    fresh_context,
                    opportunity_id=None,
                )
                call = self._authorizations.supplier(
                    fresh_context,
                    identity,
                    approvals,
                )
                result = self._supplier.discover(
                    context.cycle.opportunity_key,
                    self._targeting,
                    call.authorization,
                    evaluated_at=observed_at,
                    budget_usage=call.budget_usage,
                    discovery_run_id=identity.run_id,
                    correlation_id=identity.correlation_id,
                )
        except SupplierSearchNotActionable:
            return _suppressed("SUPPLIER_NEED_NOT_ACTIONABLE")
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        policy = _policy_outcome(getattr(result, "decision", None))
        if policy is not None:
            return policy
        observed = self._truth.opportunity(context.cycle.opportunity_key)
        if observed is not None and observed.supplier_ref is not None:
            return _complete(
                ("opportunity", observed.opportunity_id),
                ("supplier", observed.supplier_ref),
            )
        run = getattr(result, "run", None)
        status = _value(getattr(run, "status", None))
        if status == "SEARCH_TOO_BROAD":
            return _blocked("SUPPLIER_SEARCH_TOO_BROAD")
        if status == "STARTED":
            return _started_run_checkpoint(
                run,
                observed_at=observed_at,
                code="SUPPLIER_PROVIDER_INDETERMINATE",
            )
        if _retryable_run(run):
            return _waiting(
                "SUPPLIER_PROVIDER_RETRYABLE",
                retry_at=getattr(run, "retry_after", None),
            )
        if status in {"SUCCESS", "PARTIAL"}:
            return _suppressed("SUPPLIER_NOT_FOUND")
        return _failed("SUPPLIER_DISCOVERY_FAILED")

    @_closed_domain_action
    def discover_contact(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        if opportunity.contact_ref is not None:
            return _complete(("contact", opportunity.contact_ref))
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                identity, call = self._authorized(
                    "contact",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                result = self._contact.find(
                    opportunity.opportunity_id,
                    call.authorization,
                    evaluated_at=observed_at,
                    budget_usage=call.budget_usage,
                    contact_discovery_run_id=identity.run_id,
                    correlation_id=identity.correlation_id,
                )
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        policy = _policy_outcome(getattr(result, "decision", None))
        if policy is not None:
            return policy
        observed = self._truth.opportunity(context.cycle.opportunity_key)
        if observed is not None and observed.contact_ref is not None:
            return _complete(("contact", observed.contact_ref))
        run = getattr(result, "run", None)
        status = _value(getattr(run, "status", None))
        if status in {"NO_CANDIDATE", "NO_VERIFIED_CONTACT"}:
            return _suppressed("VERIFIED_CONTACT_NOT_FOUND")
        if status == "CONTACT_SEARCH_TOO_BROAD":
            return _blocked("CONTACT_SEARCH_TOO_BROAD")
        if status == "STARTED":
            return _started_run_checkpoint(
                run,
                observed_at=observed_at,
                code="CONTACT_PROVIDER_INDETERMINATE",
            )
        if _retryable_run(run):
            return _waiting(
                "CONTACT_PROVIDER_RETRYABLE",
                retry_at=getattr(run, "retry_after", None),
            )
        return _failed("CONTACT_DISCOVERY_FAILED")

    @_closed_domain_action
    def research_company(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        profile_ref = self._truth.company_profile_ref(opportunity.opportunity_id)
        if profile_ref is not None:
            return _complete(("company", profile_ref))
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                identity, call = self._authorized(
                    "company",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                result = self._company.research(
                    opportunity.opportunity_id,
                    call.authorization,
                    evaluated_at=observed_at,
                    budget_usage=call.budget_usage,
                    company_research_run_id=identity.run_id,
                    correlation_id=identity.correlation_id,
                )
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        policy = _policy_outcome(getattr(result, "decision", None))
        if policy is not None:
            return policy
        profile_ref = self._truth.company_profile_ref(opportunity.opportunity_id)
        if profile_ref is not None:
            return _complete(("company", profile_ref))
        run = getattr(result, "run", None)
        if _value(getattr(run, "status", None)) == "STARTED":
            return _started_run_checkpoint(
                run,
                observed_at=observed_at,
                code="COMPANY_PROVIDER_INDETERMINATE",
            )
        if _retryable_run(run):
            return _waiting(
                "COMPANY_PROVIDER_RETRYABLE",
                retry_at=getattr(run, "retry_after", None),
            )
        return _failed("COMPANY_RESEARCH_FAILED")

    @_closed_domain_action
    def decide(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        existing = self._truth.decision(opportunity.opportunity_id)
        if existing is not None:
            return _decision_outcome(existing)
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                identity, call = self._authorized(
                    "decision",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                result = self._decision.evaluate(
                    opportunity.opportunity_id,
                    call.authorization,
                    budget_usage=call.budget_usage,
                )
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        policy = _policy_outcome(getattr(result, "decision", None))
        if policy is not None:
            return policy
        observed = self._truth.decision(opportunity.opportunity_id)
        if observed is None:
            proposal = getattr(result, "proposal", None)
            proposed = getattr(proposal, "proposed_decision", None)
            if proposed is None:
                return _failed("DECISION_RESULT_MISSING")
            observed = DecisionTruth(
                evaluation_ref=getattr(
                    getattr(result, "audit", None),
                    "decision_evaluation_id",
                    identity.evaluation_id,
                ),
                decision=Decision(_value(proposed)),
            )
        return _decision_outcome(observed)

    @_closed_domain_action
    def personalize(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        existing = self._truth.personalization(opportunity.opportunity_id)
        if existing is not None and not (
            existing.disposition is PersonalizationDisposition.POLICY_BLOCKED
            and existing.policy_status is PolicyStatus.APPROVAL_REQUIRED
        ):
            return _personalization_outcome(existing)
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                _identity, call = self._authorized(
                    "personalization",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                if call.language not in {"fr", "en"}:
                    return _blocked("PERSONALIZATION_LANGUAGE_NOT_CONFIGURED")
                self._personalization.personalize(
                    opportunity.opportunity_id,
                    call.language,
                    call.authorization,
                    budget_usage=call.budget_usage,
                )
        except PersonalizationDecisionNoLongerEligible:
            return _suppressed("PERSONALIZATION_NO_LONGER_ELIGIBLE")
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        observed = self._truth.personalization(opportunity.opportunity_id)
        if observed is None:
            return _failed("PERSONALIZATION_RESULT_MISSING")
        return _personalization_outcome(observed)

    @_closed_domain_action
    def assess_compliance(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        existing = self._truth.compliance(opportunity.opportunity_id)
        if existing is not None:
            return _compliance_outcome(existing)
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                _identity, call = self._authorized(
                    "compliance",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                self._compliance.assess(
                    opportunity.opportunity_id,
                    call.authorization,
                    budget_usage=call.budget_usage,
                )
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        observed = self._truth.compliance(opportunity.opportunity_id)
        if observed is None:
            return _failed("COMPLIANCE_RESULT_MISSING")
        return _compliance_outcome(observed)

    @_closed_domain_action
    def plan_campaign(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        existing = self._truth.campaign(opportunity.opportunity_id)
        if existing is not None:
            return _complete(
                ("campaign", existing.campaign_ref),
                ("member", existing.member_ref),
            )
        try:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                _identity, call = self._authorized(
                    "campaign",
                    fresh_context,
                    opportunity.opportunity_id,
                )
                result = self._campaign.schedule(
                    opportunity.opportunity_id,
                    call.authorization,
                    budget_usage=call.budget_usage,
                )
        except CampaignPacingExceeded:
            return _waiting("CAMPAIGN_PACING_LIMIT_REACHED")
        except CampaignDeploymentBlocked:
            return _blocked("CAMPAIGN_DEPLOYMENT_BLOCKED")
        except CampaignNotActionable:
            return _suppressed("CAMPAIGN_NO_LONGER_ACTIONABLE")
        except CampaignInputChanged:
            return _waiting("CAMPAIGN_INPUT_CHANGED")
        except DomainTransientFailure as error:
            return _waiting(error.code, retry_at=error.retry_at)
        if getattr(result, "disposition", None) == "POLICY_BLOCKED":
            return _blocked("CAMPAIGN_POLICY_BLOCKED")
        observed = self._truth.campaign(opportunity.opportunity_id)
        if observed is None:
            return _failed("CAMPAIGN_RESULT_MISSING")
        return _complete(
            ("campaign", observed.campaign_ref),
            ("member", observed.member_ref),
        )

    @_closed_domain_action
    def handoff_provider(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        if not context.allow_qa_provider_mutations:
            return _waiting("QA_PROVIDER_MUTATION_NOT_AUTHORIZED")
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        required = (
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        )
        with context.guard.protect() as observed_at:
            fresh_context = replace(context, at=observed_at)
            loaded = self._provider_handoff_truth(
                opportunity.opportunity_id,
                required=required,
            )
            if isinstance(loaded, KivouDomainOutcome):
                return loaded
            campaign, ordered, action_fingerprint = loaded
            deferred = _provider_retry_checkpoint(ordered, observed_at)
            if deferred is not None:
                return deferred
            self._approvals.consume_for(
                fresh_context,
                opportunity_id=opportunity.opportunity_id,
                action_fingerprint=action_fingerprint,
            )
        for expected_operation in ordered:
            with context.guard.protect() as observed_at:
                fresh_context = replace(context, at=observed_at)
                loaded = self._provider_handoff_truth(
                    opportunity.opportunity_id,
                    required=required,
                )
                if isinstance(loaded, KivouDomainOutcome):
                    return loaded
                campaign, current, current_fingerprint = loaded
                if current_fingerprint != action_fingerprint:
                    self._approvals.consume_for(
                        fresh_context,
                        opportunity_id=opportunity.opportunity_id,
                        action_fingerprint=current_fingerprint,
                    )
                    action_fingerprint = current_fingerprint
                deferred = _provider_retry_checkpoint(current, observed_at)
                if deferred is not None:
                    return deferred
                operation = next(
                    item
                    for item in current
                    if item.operation_ref == expected_operation.operation_ref
                )
                self._approvals.consume_for(
                    fresh_context,
                    opportunity_id=opportunity.opportunity_id,
                    action_fingerprint=action_fingerprint,
                )
                if operation.state is ProviderOperationState.CONFIRMED:
                    continue
                try:
                    state = self._worker.process(
                        operation.operation_ref,
                        observed_at,
                    )
                except DomainTransientFailure as error:
                    return _waiting(error.code, retry_at=error.retry_at)
                disposition = _provider_state_outcome(state)
                if disposition is not None:
                    refreshed = self._truth.provider_operations(
                        campaign.campaign_ref,
                        campaign.member_ref,
                    )
                    retry = next(
                        (
                            item.retry_at
                            for item in refreshed
                            if item.operation_ref == operation.operation_ref
                            and item.retry_at is not None
                        ),
                        None,
                    )
                    return disposition.model_copy(update={"retry_at": retry})
        observed = self._truth.provider_operations(campaign.campaign_ref, campaign.member_ref)
        if (
            len(observed) != len(required)
            or tuple(sorted(item.kind.value for item in observed))
            != tuple(sorted(item.value for item in required))
        ):
            return _blocked("PROVIDER_OPERATION_SET_UNSAFE")
        if any(item.state is not ProviderOperationState.CONFIRMED for item in observed):
            return _waiting("PROVIDER_OPERATIONS_INCOMPLETE")
        rebound = self._truth.campaign(opportunity.opportunity_id)
        if rebound is None or (
            rebound.transport_recipient_identity,
            rebound.transport_recipient_key_version,
        ) != self._qa_transport_binding:
            return _blocked("QA_TRANSPORT_BINDING_MISMATCH")
        return _complete(*(("provider-operation", item.operation_ref) for item in observed))

    def _provider_handoff_truth(
        self,
        opportunity_id: str,
        *,
        required: tuple[ProviderOperationKind, ...],
    ) -> tuple[CampaignTruth, tuple[ProviderOperationTruth, ...], str] | KivouDomainOutcome:
        campaign = self._truth.campaign(opportunity_id)
        if campaign is None:
            return _blocked("CAMPAIGN_NOT_PLANNED")
        stored_binding = (
            campaign.transport_recipient_identity,
            campaign.transport_recipient_key_version,
        )
        if stored_binding != (None, None) and stored_binding != self._qa_transport_binding:
            return _blocked("QA_TRANSPORT_BINDING_MISMATCH")
        operations = self._truth.provider_operations(
            campaign.campaign_ref,
            campaign.member_ref,
        )
        if not operations:
            return _waiting("PROVIDER_OPERATIONS_NOT_PLANNED")
        if (
            len(operations) != len(required)
            or len(operations) > self._provider_cap
            or tuple(sorted(item.kind.value for item in operations))
            != tuple(sorted(item.value for item in required))
        ):
            return _blocked("PROVIDER_OPERATION_SET_UNSAFE")
        ordered = tuple(
            sorted(
                operations,
                key=lambda item: required.index(item.kind),
            )
        )
        action_fingerprint = _provider_approval_fingerprint(
            campaign,
            ordered,
            qa_transport_binding=self._qa_transport_binding,
        )
        return campaign, ordered, action_fingerprint

    @_closed_domain_action
    def observe_response(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        campaign = self._truth.campaign(opportunity.opportunity_id)
        if campaign is None:
            return _blocked("CAMPAIGN_NOT_PLANNED")
        response = self._truth.response(opportunity.opportunity_id, campaign)
        if response is None:
            return _waiting("RESPONSE_NOT_OBSERVED")
        return _complete(("response", response.response_ref))

    @_closed_domain_action
    def reconcile_conversion(self, context: AcquisitionActionContext) -> KivouDomainOutcome:
        opportunity = self._required_opportunity(context)
        if isinstance(opportunity, KivouDomainOutcome):
            return opportunity
        campaign = self._truth.campaign(opportunity.opportunity_id)
        if campaign is None:
            return _blocked("CAMPAIGN_NOT_PLANNED")
        refs = self._truth.conversion_refs(opportunity.opportunity_id, campaign)
        if len(refs) < 2:
            return _waiting("ATTRIBUTION_CONVERSION_NOT_OBSERVED")
        return _complete(*(("conversion", ref) for ref in refs))

    def _required_opportunity(
        self, context: AcquisitionActionContext
    ) -> OpportunityTruth | KivouDomainOutcome:
        opportunity = self._truth.opportunity(context.cycle.opportunity_key)
        return opportunity or _blocked("ACQUISITION_OPPORTUNITY_MISSING")

    def _authorized(
        self,
        method: str,
        context: AcquisitionActionContext,
        opportunity_id: str,
    ) -> tuple[DomainAttemptIdentity, AuthorizedCall[DomainAuthorization]]:
        identity = deterministic_attempt_identity(context.stage_snapshot)
        approvals = self._approvals.consume_for(context, opportunity_id=opportunity_id)
        factory = getattr(self._authorizations, method)
        call = factory(
            context,
            identity,
            approvals,
            opportunity_id=opportunity_id,
        )
        return identity, call


def _value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _aware_time(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _provider_retry_checkpoint(
    operations: tuple[ProviderOperationTruth, ...],
    observed_at: dt.datetime,
) -> KivouDomainOutcome | None:
    retry_at = max(
        (
            item.retry_at
            for item in operations
            if item.state is ProviderOperationState.RETRYABLE_FAILED
            and item.retry_at is not None
            and item.retry_at > observed_at
        ),
        default=None,
    )
    return (
        _waiting("PROVIDER_OPERATION_RETRYABLE", retry_at=retry_at)
        if retry_at is not None
        else None
    )


def _provider_approval_fingerprint(
    campaign: CampaignTruth,
    operations: tuple[ProviderOperationTruth, ...],
    *,
    qa_transport_binding: tuple[str, str],
) -> str:
    canonical = json.dumps(
        {
            "campaign_ref": campaign.campaign_ref,
            "kind": "acquisition-runtime-provider-handoff-v1",
            "member_ref": campaign.member_ref,
            "operations": [
                {
                    "desired_request_fingerprint": item.desired_request_fingerprint,
                    "kind": item.kind.value,
                    "operation_ref": item.operation_ref,
                }
                for item in operations
            ],
            "qa_transport_recipient_identity": qa_transport_binding[0],
            "qa_transport_recipient_key_version": qa_transport_binding[1],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _opaque(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"acquisition-runtime-result-v1\0{kind}\0{value}".encode()).hexdigest()
    return f"{kind}:{digest}"


def _complete(*refs: tuple[str, str]) -> KivouDomainOutcome:
    return KivouDomainOutcome(
        disposition=KivouDomainDisposition.COMPLETE,
        result_refs=tuple(_opaque(kind, value) for kind, value in refs),
    )


def _waiting(
    code: str,
    *,
    retry_at: dt.datetime | None = None,
    replay_same_attempt: bool = False,
) -> KivouDomainOutcome:
    return KivouDomainOutcome(
        disposition=KivouDomainDisposition.WAITING,
        reason_codes=(code,),
        retry_at=retry_at,
        replay_same_attempt=replay_same_attempt,
    )


def _blocked(code: str) -> KivouDomainOutcome:
    return KivouDomainOutcome(
        disposition=KivouDomainDisposition.BLOCKED,
        reason_codes=(code,),
    )


def _suppressed(code: str) -> KivouDomainOutcome:
    return KivouDomainOutcome(
        disposition=KivouDomainDisposition.SUPPRESSED,
        reason_codes=(code,),
    )


def _failed(code: str) -> KivouDomainOutcome:
    return KivouDomainOutcome(
        disposition=KivouDomainDisposition.FAILED,
        reason_codes=(code,),
    )


def _policy_outcome(decision: object | None) -> KivouDomainOutcome | None:
    if decision is None or bool(getattr(decision, "executable", False)):
        return None
    status = _value(getattr(decision, "status", None))
    return _policy_status_outcome(status)


def _policy_status_outcome(status: str | None) -> KivouDomainOutcome:
    if status == PolicyStatus.RATE_LIMITED.value:
        return _waiting("POLICY_RATE_LIMITED")
    if status == PolicyStatus.BUDGET_EXCEEDED.value:
        return _blocked("POLICY_BUDGET_EXCEEDED")
    if status == PolicyStatus.COMPLIANCE_BLOCKED.value:
        return _blocked("POLICY_COMPLIANCE_BLOCKED")
    if status == PolicyStatus.APPROVAL_REQUIRED.value:
        return _waiting("POLICY_APPROVAL_REQUIRED")
    if status == PolicyStatus.INSUFFICIENT_EVIDENCE.value:
        return _blocked("POLICY_EVIDENCE_INSUFFICIENT")
    return _blocked("POLICY_DENIED")


def _retryable_run(run: object | None) -> bool:
    if run is None:
        return False
    if getattr(run, "retry_after", None) is not None:
        return True
    category = str(getattr(run, "error_category", "") or "").casefold()
    return (
        category
        in {
            "network",
            "network_error",
            "rate_limited",
            "server_error",
            "timeout",
        }
    )


def _started_run_checkpoint(
    run: object,
    *,
    observed_at: dt.datetime,
    code: str,
) -> KivouDomainOutcome:
    started_at = getattr(run, "started_at", None)
    if not isinstance(started_at, dt.datetime):
        return _failed("APOLLO_RUN_RECOVERY_METADATA_MISSING")
    started_at = _aware_time(started_at)
    deadline = started_at + dt.timedelta(minutes=10)
    if observed_at >= deadline:
        return _failed("APOLLO_RUN_RECOVERY_EXHAUSTED")
    return _waiting(
        code,
        retry_at=min(observed_at + dt.timedelta(minutes=1), deadline),
        replay_same_attempt=True,
    )


def _decision_outcome(truth: DecisionTruth) -> KivouDomainOutcome:
    if truth.disposition is DecisionAuditDisposition.POLICY_BLOCKED:
        return _policy_status_outcome(truth.policy_status.value)
    if truth.decision is Decision.SEND:
        return _complete(("decision", truth.evaluation_ref))
    if truth.decision is Decision.NO_SEND:
        return _suppressed("DECISION_NO_SEND")
    if truth.decision is Decision.REVIEW:
        return _blocked("DECISION_REVIEW_REQUIRED")
    return _waiting(f"DECISION_{truth.decision.value}")


def _personalization_outcome(truth: PersonalizationTruth) -> KivouDomainOutcome:
    if truth.disposition is PersonalizationDisposition.READY:
        return _complete(("personalization", truth.artifact_ref))
    if truth.policy_status is PolicyStatus.APPROVAL_REQUIRED:
        return _waiting("POLICY_APPROVAL_REQUIRED")
    return _blocked("PERSONALIZATION_POLICY_BLOCKED")


def _compliance_outcome(truth: ComplianceTruth) -> KivouDomainOutcome:
    if truth.disposition is ComplianceDisposition.RECORDED and truth.state == "ALLOWED":
        return _complete(("compliance", truth.assessment_ref))
    if truth.state == "REVIEW_REQUIRED":
        return _blocked("COMPLIANCE_REVIEW_REQUIRED")
    return _blocked("COMPLIANCE_BLOCKED")


def _provider_state_outcome(
    state: ProviderOperationState,
) -> KivouDomainOutcome | None:
    if state is ProviderOperationState.CONFIRMED:
        return None
    if state in {
        ProviderOperationState.PLANNED,
        ProviderOperationState.IN_FLIGHT,
        ProviderOperationState.RECONCILE_REQUIRED,
        ProviderOperationState.RETRYABLE_FAILED,
    }:
        return _waiting("PROVIDER_OPERATION_RETRYABLE")
    return _failed("PROVIDER_OPERATION_TERMINAL_FAILURE")


__all__ = [
    "AcquisitionDomainActions",
    "AcquisitionDomainTruth",
    "AuthorizedCall",
    "CampaignTruth",
    "ComplianceTruth",
    "DecisionTruth",
    "DomainAmbiguousFailure",
    "DomainApprovalRequired",
    "DomainAttemptIdentity",
    "DomainTransientFailure",
    "OpportunityTruth",
    "PersonalizationTruth",
    "ProviderOperationTruth",
    "ResponseTruth",
    "RuntimeApprovalProvider",
    "RuntimePolicyAuthorizationFactory",
    "SqlAcquisitionDomainTruth",
    "deterministic_attempt_identity",
]
