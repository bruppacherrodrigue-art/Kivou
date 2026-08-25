"""Live Policy inputs and durable one-shot approvals for the runtime root."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Engine, RowMapping

from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    ApprovalError,
    RuntimeApprovalBinding,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.contracts import AcquisitionRuntimeStage, require_aware
from signals.acquisition_runtime.domain import (
    AuthorizedCall,
    DomainApprovalRequired,
    DomainAttemptIdentity,
)
from signals.acquisition_runtime.registry import AcquisitionActionContext
from signals.acquisition_runtime.supervisor import KIVOU_STAGE_COSTS
from signals.campaigns.contracts import CampaignAuthorizationInput
from signals.company_research.contracts import CompanyResearchAuthorizationInput
from signals.compliance.contracts import ComplianceAuthorizationInput
from signals.contact_discovery.contracts import ContactAuthorizationInput
from signals.decision_engine.contracts import DecisionAuthorizationInput
from signals.persistence.schema import acquisition_runtime_approval, policy_evaluation
from signals.policy.contracts import (
    ApprovalGrant,
    ApprovalPurpose,
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyControlSnapshot,
    PolicyStatus,
    Scope,
)
from signals.policy.registry import COMMAND_POLICIES
from signals.policy.store import PolicyStore
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supplier_discovery.contracts import DiscoveryAuthorizationInput

_APPROVAL_STAGES = frozenset(
    {
        AcquisitionRuntimeStage.PERSONALIZATION,
        AcquisitionRuntimeStage.CAMPAIGN,
        AcquisitionRuntimeStage.PROVIDER_HANDOFF,
    }
)


class RuntimePolicyConfigurationError(RuntimeError):
    """A safe machine-only failure at the live Policy composition boundary."""


def _exact_scope(control: PolicyControlSnapshot) -> Scope:
    if not (
        len(control.allowed_countries) == 1
        and len(control.allowed_languages) == 1
        and len(control.allowed_wedges) == 1
    ):
        raise RuntimePolicyConfigurationError("POLICY_SCOPE_NOT_EXACT")
    return Scope(
        country=control.allowed_countries[0],
        language=control.allowed_languages[0],
        wedge=control.allowed_wedges[0],
    )


def _stored_time(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        raise RuntimePolicyConfigurationError("APPROVAL_TIME_UNAVAILABLE")
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _common_authorization(
    *,
    context: AcquisitionActionContext,
    identity: DomainAttemptIdentity,
    approvals: tuple[ApprovalGrant, ...],
    control: PolicyControlSnapshot,
    runtime_revision: str,
    qa_signal_ref: str,
) -> dict[str, object]:
    profile = COMMAND_POLICIES[context.stage.command]
    observed_at = require_aware(context.at)
    return {
        "evaluation_id": identity.evaluation_id,
        "request_id": identity.request_id,
        "actor_type": "HERMES",
        "actor_ref": "kivou-acquisition-runtime",
        "qa_signal_ref": qa_signal_ref,
        "scope": _exact_scope(control),
        "currency": control.currency,
        "evidence": EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=profile.required_evidence,
            assessment_version="acquisition-runtime-evidence-v1",
            observed_at=observed_at,
        ),
        "operational": OperationalReadiness(
            runtime_revision=runtime_revision,
            provider_quota="READY",
            mailbox_quota="READY",
            send_window="OPEN",
            provider_control_plane="AVAILABLE",
        ),
        "expected_policy_version": control.policy_version,
        "approval_grants": approvals,
        "supervisor_plan_id": context.proposal.plan_ref,
        "supervisor_action_index": context.proposal.action_index,
        "supervisor_version": f"hermes-agent-{load_hermes_pin().version}",
        "skill_version": PROFILE_VERSION,
    }


class LiveRuntimePolicyAuthorizationFactory:
    """Build exact native DTOs from the effective persisted Policy snapshot."""

    def __init__(
        self,
        engine: Engine,
        *,
        runtime_revision: str,
        qa_signal_ref: str,
    ) -> None:
        if not runtime_revision or len(runtime_revision) > 100:
            raise RuntimePolicyConfigurationError("RUNTIME_REVISION_INVALID")
        if (
            not qa_signal_ref.startswith("procurement-opportunity:")
            or len(qa_signal_ref) > 256
        ):
            raise RuntimePolicyConfigurationError("QA_SIGNAL_REF_INVALID")
        self._engine = engine
        self._policy = PolicyStore(engine)
        self._runtime_revision = runtime_revision
        self._qa_signal_ref = qa_signal_ref

    def supplier(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
    ) -> AuthorizedCall[DiscoveryAuthorizationInput]:
        common, budget = self._inputs(context, identity, approvals)
        return AuthorizedCall(
            authorization=DiscoveryAuthorizationInput(
                **common,
                proposed_cost=KIVOU_STAGE_COSTS[context.stage],
                reason_codes=("ACQUISITION_RUNTIME_STAGE",),
                evidence_refs=self._evidence_refs(context),
            ),
            budget_usage=budget,
        )

    def contact(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[ContactAuthorizationInput]:
        del opportunity_id
        common, budget = self._inputs(context, identity, approvals)
        return AuthorizedCall(
            authorization=ContactAuthorizationInput(
                **common,
                proposed_cost=KIVOU_STAGE_COSTS[context.stage],
                reason_codes=("ACQUISITION_RUNTIME_STAGE",),
                evidence_refs=self._evidence_refs(context),
            ),
            budget_usage=budget,
        )

    def company(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[CompanyResearchAuthorizationInput]:
        del opportunity_id
        common, budget = self._inputs(context, identity, approvals)
        return AuthorizedCall(
            authorization=CompanyResearchAuthorizationInput(
                **common,
                proposed_cost=KIVOU_STAGE_COSTS[context.stage],
                reason_codes=("ACQUISITION_RUNTIME_STAGE",),
                evidence_refs=self._evidence_refs(context),
            ),
            budget_usage=budget,
        )

    def decision(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[DecisionAuthorizationInput]:
        del opportunity_id
        return self._decision_authorization(context, identity, approvals)

    def personalization(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[DecisionAuthorizationInput]:
        del opportunity_id
        result = self._decision_authorization(context, identity, approvals)
        return AuthorizedCall(
            authorization=result.authorization,
            budget_usage=result.budget_usage,
            language=result.authorization.scope.language,
        )

    def compliance(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[ComplianceAuthorizationInput]:
        del opportunity_id
        common, budget = self._inputs(context, identity, approvals)
        common.pop("compliance", None)
        return AuthorizedCall(
            authorization=ComplianceAuthorizationInput(**common),
            budget_usage=budget,
        )

    def campaign(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
        *,
        opportunity_id: str,
    ) -> AuthorizedCall[CampaignAuthorizationInput]:
        del opportunity_id
        common, budget = self._inputs(context, identity, approvals)
        common.pop("compliance", None)
        return AuthorizedCall(
            authorization=CampaignAuthorizationInput(**common),
            budget_usage=budget,
        )

    def _decision_authorization(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
    ) -> AuthorizedCall[DecisionAuthorizationInput]:
        common, budget = self._inputs(context, identity, approvals)
        return AuthorizedCall(
            authorization=DecisionAuthorizationInput(**common),
            budget_usage=budget,
        )

    def _inputs(
        self,
        context: AcquisitionActionContext,
        identity: DomainAttemptIdentity,
        approvals: tuple[ApprovalGrant, ...],
    ) -> tuple[dict[str, object], BudgetUsage]:
        control = self._policy.get_effective_control(require_aware(context.at))
        common = _common_authorization(
            context=context,
            identity=identity,
            approvals=approvals,
            control=control,
            runtime_revision=self._runtime_revision,
            qa_signal_ref=self._qa_signal_ref,
        )
        common["compliance"] = self._unknown_compliance(context.at)
        return common, self._budget_usage(context.at)

    def _budget_usage(self, at: dt.datetime) -> BudgetUsage:
        observed_at = require_aware(at)
        start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=1)
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(
                    sa.func.coalesce(sa.func.sum(policy_evaluation.c.estimated_cost), 0),
                    sa.func.coalesce(sa.func.sum(policy_evaluation.c.proposed_volume), 0),
                ).where(
                    policy_evaluation.c.executable.is_(True),
                    policy_evaluation.c.evaluated_at >= start,
                    policy_evaluation.c.evaluated_at < end,
                )
            ).one()
        return BudgetUsage(cost_used=Decimal(row[0]), volume_used=int(row[1]))

    @staticmethod
    def _unknown_compliance(at: dt.datetime) -> ComplianceAssessment:
        return ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="acquisition-runtime-not-applicable-v1",
            observed_at=require_aware(at),
        )

    @staticmethod
    def _evidence_refs(context: AcquisitionActionContext) -> tuple[str, ...]:
        return context.proposal.evidence_refs or (
            f"runtime-evidence:{context.proposal.argument_fingerprint}",
        )


class DurableRuntimeApprovalProvider:
    """Request and consume exact durable grants without ever constructing one."""

    def __init__(self, engine: Engine, *, approval_ttl_seconds: int) -> None:
        if not 60 <= approval_ttl_seconds <= 86_400:
            raise RuntimePolicyConfigurationError("APPROVAL_TTL_INVALID")
        self._engine = engine
        self._policy = PolicyStore(engine)
        self._approvals = AcquisitionRuntimeApprovalStore(engine)
        self._ttl = dt.timedelta(seconds=approval_ttl_seconds)

    def consume_for(
        self,
        context: AcquisitionActionContext,
        *,
        opportunity_id: str | None,
    ) -> tuple[ApprovalGrant, ...]:
        if context.stage not in _APPROVAL_STAGES:
            return ()
        if opportunity_id is None:
            raise RuntimePolicyConfigurationError("APPROVAL_TARGET_MISSING")
        control = self._policy.get_effective_control(require_aware(context.at))
        scope = _exact_scope(control)
        action = self._approval_action(context, opportunity_id=opportunity_id)
        if action is None:
            return ()
        target_ref, action_fingerprint = action
        consumer_ref = context.stage_snapshot.attempt_ref
        row = self._open_binding_row(
            context=context,
            opportunity_id=opportunity_id,
            target_ref=target_ref,
            action_fingerprint=action_fingerprint,
            control=control,
            scope=scope,
            consumer_ref=consumer_ref,
        )
        binding = (
            self._binding_from_row(row)
            if row is not None
            else self._new_binding(
                context=context,
                opportunity_id=opportunity_id,
                target_ref=target_ref,
                action_fingerprint=action_fingerprint,
                control=control,
                scope=scope,
            )
        )
        snapshot = self._approvals.request_approval(binding)
        if snapshot.status is RuntimeApprovalStatus.PENDING:
            raise DomainApprovalRequired
        try:
            grant = self._approvals.consume_grant(
                snapshot.approval_id,
                consumer_ref=consumer_ref,
                at=require_aware(context.at),
            )
        except ApprovalError:
            raise DomainApprovalRequired from None
        return (grant,)

    def _approval_action(
        self,
        context: AcquisitionActionContext,
        *,
        opportunity_id: str,
    ) -> tuple[str, str] | None:
        if context.stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF:
            return (
                f"acquisition-opportunity:{opportunity_id}",
                context.proposal.argument_fingerprint,
            )
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(
                    policy_evaluation.c.target_ref,
                    policy_evaluation.c.action_fingerprint,
                    policy_evaluation.c.status,
                )
                .where(
                    policy_evaluation.c.acquisition_opportunity_id == opportunity_id,
                    policy_evaluation.c.command == context.stage.command,
                )
                .order_by(
                    policy_evaluation.c.evaluated_at.desc(),
                    policy_evaluation.c.evaluation_id.desc(),
                )
                .limit(1)
            ).mappings().one_or_none()
        if row is None or row["status"] != PolicyStatus.APPROVAL_REQUIRED.value:
            return None
        return str(row["target_ref"]), str(row["action_fingerprint"])

    def _open_binding_row(
        self,
        *,
        context: AcquisitionActionContext,
        opportunity_id: str,
        target_ref: str,
        action_fingerprint: str,
        control: PolicyControlSnapshot,
        scope: Scope,
        consumer_ref: str,
    ) -> RowMapping | None:
        at = require_aware(context.at)
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(acquisition_runtime_approval)
                .where(
                    acquisition_runtime_approval.c.cycle_ref == context.cycle.cycle_ref,
                    acquisition_runtime_approval.c.stage == context.stage.value,
                    acquisition_runtime_approval.c.purpose == ApprovalPurpose.ACTION.value,
                    acquisition_runtime_approval.c.command == context.stage.command,
                    acquisition_runtime_approval.c.target_ref == target_ref,
                    acquisition_runtime_approval.c.acquisition_opportunity_id
                    == opportunity_id,
                    acquisition_runtime_approval.c.action_fingerprint
                    == action_fingerprint,
                    acquisition_runtime_approval.c.policy_version
                    == control.policy_version,
                    acquisition_runtime_approval.c.policy_snapshot_id
                    == control.policy_snapshot_id,
                    acquisition_runtime_approval.c.control_revision
                    == control.control_revision,
                    acquisition_runtime_approval.c.scope_fingerprint
                    == scope.fingerprint(),
                    acquisition_runtime_approval.c.expires_at > at,
                    sa.or_(
                        acquisition_runtime_approval.c.state.in_(
                            (
                                RuntimeApprovalStatus.PENDING.value,
                                RuntimeApprovalStatus.APPROVED.value,
                            )
                        ),
                        sa.and_(
                            acquisition_runtime_approval.c.state
                            == RuntimeApprovalStatus.CONSUMED.value,
                            acquisition_runtime_approval.c.consumed_by_ref
                            == consumer_ref,
                        ),
                    ),
                )
                .order_by(acquisition_runtime_approval.c.requested_at.desc())
                .limit(1)
            ).mappings().all()
        return rows[0] if rows else None

    def _new_binding(
        self,
        *,
        context: AcquisitionActionContext,
        opportunity_id: str,
        target_ref: str,
        action_fingerprint: str,
        control: PolicyControlSnapshot,
        scope: Scope,
    ) -> RuntimeApprovalBinding:
        requested_at = require_aware(context.at)
        material = json.dumps(
            {
                "action_fingerprint": action_fingerprint,
                "attempt_ref": context.stage_snapshot.attempt_ref,
                "control_revision": control.control_revision,
                "cycle_ref": context.cycle.cycle_ref,
                "kind": "acquisition-runtime-approval-request-v1",
                "policy_snapshot_id": control.policy_snapshot_id,
                "scope_fingerprint": scope.fingerprint(),
                "stage": context.stage.value,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        request_ref = f"approval-request:{hashlib.sha256(material.encode()).hexdigest()}"
        return RuntimeApprovalBinding(
            request_ref=request_ref,
            cycle_ref=context.cycle.cycle_ref,
            stage=context.stage,
            purpose=ApprovalPurpose.ACTION,
            command=context.stage.command,
            target_ref=target_ref,
            acquisition_opportunity_id=opportunity_id,
            action_fingerprint=action_fingerprint,
            policy_version=control.policy_version,
            policy_snapshot_id=control.policy_snapshot_id,
            control_revision=control.control_revision,
            scope_fingerprint=scope.fingerprint(),
            requested_at=requested_at,
            expires_at=requested_at + self._ttl,
        )

    @staticmethod
    def _binding_from_row(row: RowMapping) -> RuntimeApprovalBinding:
        return RuntimeApprovalBinding(
            request_ref=row["request_ref"],
            cycle_ref=row["cycle_ref"],
            stage=row["stage"],
            purpose=row["purpose"],
            command=row["command"],
            target_ref=row["target_ref"],
            acquisition_opportunity_id=row["acquisition_opportunity_id"],
            action_fingerprint=row["action_fingerprint"],
            policy_version=row["policy_version"],
            policy_snapshot_id=row["policy_snapshot_id"],
            control_revision=row["control_revision"],
            scope_fingerprint=row["scope_fingerprint"],
            requested_at=_stored_time(row["requested_at"]),
            expires_at=_stored_time(row["expires_at"]),
        )


__all__ = [
    "DurableRuntimeApprovalProvider",
    "LiveRuntimePolicyAuthorizationFactory",
    "RuntimePolicyConfigurationError",
]
