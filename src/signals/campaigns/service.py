"""Kivou-owned schedule planning and durable provider-operation preparation."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import AcquisitionState, ActorType, Decision, EventType
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import (
    CampaignAuthorizationInput,
    CampaignBindingConflict,
    CampaignDeploymentBlocked,
    CampaignDeploymentConfig,
    CampaignEvaluationRequiresFreshAttempt,
    CampaignFactoryInput,
    CampaignIdempotencyConflict,
    CampaignInputChanged,
    CampaignMemberReservation,
    CampaignNotActionable,
    LeadRiskReductionContractProof,
    MailboxCatalogEntry,
    MailboxReadiness,
    MailboxReadinessState,
    ProviderOperationKind,
    TransportContractProof,
    WebhookEntitlement,
)
from signals.campaigns.envelope import CampaignEnvelope, EnvelopeInput, build_envelope
from signals.campaigns.factory import CampaignFactory
from signals.campaigns.instantly import (
    build_provider_campaign_config,
    provider_campaign_config_fingerprint,
)
from signals.campaigns.store import CampaignStore
from signals.compliance.contracts import SenderComplianceConfig, SuppressionMatchState
from signals.compliance.jurisdiction import resolve_jurisdiction
from signals.compliance.rules import RULESET_V1
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.source import AttributionSourceFacts, AttributionSourceResolver
from signals.decision_engine.policy import semantic_fingerprint
from signals.operations.circuit_breakers import (
    AcquisitionCircuitOpen,
    AcquisitionExecutionGuard,
)
from signals.operations.contracts import BreakerScope
from signals.operations.store import OperationsStore
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_company_profile,
    acquisition_compliance_assessment,
    acquisition_contact,
    acquisition_event,
    acquisition_personalization_artifact,
    acquisition_provider_operation,
    acquisition_supplier,
)
from signals.policy.contracts import (
    AutonomyMode,
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    PolicyControlUnavailable,
    PolicyRequest,
)
from signals.policy.gateway import PolicyGateway
from signals.policy.store import PolicyStore, decision_from_row

_SCHEDULE_EVIDENCE = (
    "ACQUISITION_DECISION",
    "PUBLIC_EVIDENCE",
    "VERIFIED_CONTACT",
    "ACQUISITION_PROSPECT_PREBUILD",
    "PERSONALIZATION_ARTIFACT",
    "COMPLIANCE_ASSESSMENT",
    "CAMPAIGN_PLAN",
    "MAILBOX_READINESS",
    "SEND_WINDOW",
)


class MailboxReadinessSource(Protocol):
    def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness: ...


@dataclass(frozen=True)
class CampaignPreview:
    opportunity_id: str
    captured_at: dt.datetime
    plan: object
    envelope: CampaignEnvelope
    mailbox: MailboxCatalogEntry
    readiness: MailboxReadiness
    assessment: dict[str, object]
    artifact: dict[str, object]
    input_fingerprint: str
    action_fingerprint: str
    evidence_refs: tuple[str, ...]
    contact_provider_identity_binding: str


@dataclass(frozen=True)
class CampaignScheduleResult:
    disposition: str
    policy_status: str
    campaign_ref: str | None = None
    member_ref: str | None = None
    execution_state: str | None = None
    replayed: bool = False


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class CampaignService:
    def __init__(
        self,
        engine: Engine,
        *,
        keyring: SuppressionIdentityKeyring,
        sender_config: SenderComplianceConfig,
        deployment: CampaignDeploymentConfig,
        mailbox_readiness: MailboxReadinessSource,
        clock: Callable[[], dt.datetime] = _utc_now,
        policy_gateway: PolicyGateway | None = None,
        attribution_link_builder: AttributionLinkBuilder | None = None,
    ) -> None:
        self._engine = engine
        self._keyring = keyring
        self._sender_config = sender_config
        self._deployment = deployment
        self._mailbox_readiness = mailbox_readiness
        self._clock = clock
        self._acquisition = AcquisitionStore(engine)
        self._suppressions = SuppressionStore(engine, keyring)
        self._campaigns = CampaignStore(engine)
        self._policy_store = PolicyStore(engine)
        self._policy = policy_gateway or PolicyGateway(engine, acquisition_store=self._acquisition)
        self._execution_guard = AcquisitionExecutionGuard(OperationsStore(engine))
        self._attribution_link_builder = attribution_link_builder
        self._attribution_source_resolver = AttributionSourceResolver(engine)
        self._after_policy_hook: Callable[[], None] = lambda: None

    def preview(self, opportunity_id: str, *, captured_at: dt.datetime) -> CampaignPreview:
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("campaign captured_at must be timezone-aware")
        self._require_deployment_planning()
        return self._build_preview(opportunity_id, captured_at.astimezone(dt.UTC))

    def schedule(
        self,
        opportunity_id: str,
        authorization: CampaignAuthorizationInput,
        *,
        budget_usage: BudgetUsage,
    ) -> CampaignScheduleResult:
        authorization_fingerprint = self._authorization_fingerprint(
            authorization, budget_usage
        )
        existing = self._existing_result(
            authorization.evaluation_id,
            opportunity_id,
            authorization_fingerprint=authorization_fingerprint,
        )
        if existing is not None:
            return existing
        with self._engine.connect() as connection:
            if self._policy_store.evaluation_row(connection, authorization.evaluation_id):
                raise CampaignEvaluationRequiresFreshAttempt(authorization.evaluation_id)
        self._require_deployment_planning()
        captured_at = self._now()
        preview = self._build_preview(opportunity_id, captured_at)
        self._require_execution_circuit(
            campaign_ref=preview.plan.campaign_ref,
            country=preview.plan.country,
            wedge=preview.plan.wedge,
            mailbox_refs=(preview.mailbox.mailbox_ref,),
        )
        if (
            authorization.scope.country != preview.plan.country
            or authorization.scope.language != preview.plan.language
            or authorization.scope.wedge != self._deployment.wedge
        ):
            raise CampaignBindingConflict(opportunity_id)
        current = self._acquisition.get_opportunity(opportunity_id)
        request = self._policy_request(
            authorization, preview, expected_version=current.stream_version
        )
        decision = self._policy.evaluate_and_record(
            request, evaluated_at=captured_at, budget_usage=budget_usage
        )
        if not decision.executable:
            return CampaignScheduleResult(
                disposition="POLICY_BLOCKED", policy_status=decision.status.value
            )
        control = self._policy_store.get_control(decision.policy_snapshot_id)
        if control.autonomy_mode is AutonomyMode.AUTONOMOUS_CAPPED:
            return CampaignScheduleResult(
                disposition="POLICY_BLOCKED", policy_status="AUTONOMOUS_LIVE_CAP_ZERO"
            )
        self._after_policy_hook()
        try:
            rebuilt = self._build_preview(
                opportunity_id,
                captured_at,
                expected_campaign_ref=preview.plan.campaign_ref,
            )
        except (
            CampaignBindingConflict,
            CampaignDeploymentBlocked,
            CampaignNotActionable,
        ) as exc:
            raise CampaignInputChanged("campaign input changed after Policy") from exc
        if rebuilt.action_fingerprint != preview.action_fingerprint:
            raise CampaignInputChanged(opportunity_id)
        if decision.valid_until is not None and captured_at >= decision.valid_until:
            raise CampaignInputChanged("Policy decision expired before provider planning")
        provenance = {
            "policy_evaluation_id": decision.evaluation_id,
            "status": decision.status.value,
            "executable": decision.executable,
            "command": decision.command,
            "action_fingerprint": decision.action_fingerprint,
            "policy_version": decision.policy_version,
            "policy_snapshot_id": decision.policy_snapshot_id,
            "control_revision": decision.control_revision,
            "decision_valid_until": (
                decision.valid_until.isoformat() if decision.valid_until else None
            ),
            "autonomy_mode": control.autonomy_mode.value,
            "authorization_fingerprint": authorization_fingerprint,
            "budget_usage": budget_usage.model_dump(mode="json"),
            "approval_refs": [item.model_dump(mode="json") for item in decision.approval_refs],
        }
        sequence_authorization_fingerprint = semantic_fingerprint(
            {
                "kind": "campaign-sequence-authorization-v1",
                "campaign_ref": preview.plan.campaign_ref,
                "action_fingerprint": decision.action_fingerprint,
                "policy_provenance": provenance,
                "personalization_artifact_id": preview.artifact["personalization_artifact_id"],
                "compliance_assessment_id": preview.assessment["compliance_assessment_id"],
                "envelope_fingerprint": preview.envelope.envelope_fingerprint,
                "window": preview.plan.sequence_window.model_dump(mode="json"),
            }
        )
        reservation = self._campaigns.reserve_member(
            self._factory_input(preview),
            CampaignMemberReservation(
                acquisition_opportunity_id=opportunity_id,
                supplier_ref=preview.artifact["supplier_ref"],
                contact_ref=preview.artifact["contact_ref"],
                personalization_artifact_id=preview.artifact["personalization_artifact_id"],
                personalization_artifact_fingerprint=preview.artifact["artifact_fingerprint"],
                compliance_assessment_id=preview.assessment["compliance_assessment_id"],
                compliance_assessment_fingerprint=preview.assessment["proposal_fingerprint"],
                policy_evaluation_id=decision.evaluation_id,
                policy_provenance=provenance,
                input_fingerprint=preview.input_fingerprint,
                contact_provider_identity_binding=(
                    preview.contact_provider_identity_binding
                ),
                envelope_fingerprint=preview.envelope.envelope_fingerprint,
                policy_action_fingerprint=decision.action_fingerprint,
                ruleset_fingerprint=preview.assessment["ruleset_config_fingerprint"],
                sender_config_fingerprint=self._sender_config.config_fingerprint,
                mailbox_ref=preview.mailbox.mailbox_ref,
                mailbox_readiness_fingerprint=preview.readiness.readiness_fingerprint,
                sequence_authorization_fingerprint=sequence_authorization_fingerprint,
            ),
            provider_workspace_ref=self._deployment.provider_workspace_ref,
            desired_provider_config_fingerprint=self._provider_config_fingerprint(preview),
            reserved_at=captured_at,
            expected_campaign_ref=preview.plan.campaign_ref,
            operation_correlation_id=authorization.request_id,
            effective_mailbox_daily_cap=min(
                preview.mailbox.kivou_daily_cap,
                preview.readiness.provider_daily_limit,
            ),
        )
        return CampaignScheduleResult(
            disposition="PLANNED",
            policy_status=decision.status.value,
            campaign_ref=reservation.campaign_ref,
            member_ref=reservation.member_ref,
            execution_state="RESERVED",
            replayed=reservation.replayed,
        )

    def queue_and_seal(self, campaign_ref: str, *, captured_at: dt.datetime) -> str:
        """Authorize already-enrolled members before any provider activation."""
        self._require_activation_capabilities()
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            members = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.campaign_ref == campaign_ref
                )
            ).mappings().all()
        if (
            campaign["lifecycle"] != "BUILDING"
            or campaign["membership_closed_at"] is None
            or not members
            or campaign["provider_campaign_id"] is None
            or campaign["current_provider_config_fingerprint"]
            != campaign["desired_provider_config_fingerprint"]
        ):
            raise CampaignInputChanged("campaign is not ready to seal")
        if any(member["execution_state"] == "RESERVED" for member in members):
            raise CampaignInputChanged(
                "reserved provider enrollment work must reconcile before sealing"
            )
        control = self._policy_store.get_effective_control(captured_at)
        if control.kill_switch or control.read_only:
            raise CampaignDeploymentBlocked("live Policy safety control blocks activation")
        retained = []
        rejected = []
        for member in members:
            if member["execution_state"] != "ENROLLED":
                continue
            try:
                preview = self._build_preview(
                    member["acquisition_opportunity_id"],
                    captured_at,
                    expected_campaign_ref=campaign_ref,
                )
                decision = self._decision(member["policy_evaluation_id"])
                valid = (
                    decision.allowed
                    and decision.command == "schedule_campaign"
                    and decision.action_fingerprint == member["policy_action_fingerprint"]
                    and (
                        decision.valid_until is None
                        or captured_at < decision.valid_until
                    )
                    and preview.plan.campaign_ref == campaign_ref
                    and preview.artifact["artifact_fingerprint"]
                    == member["personalization_artifact_fingerprint"]
                    and preview.assessment["proposal_fingerprint"]
                    == member["compliance_assessment_fingerprint"]
                    and preview.envelope.envelope_fingerprint
                    == member["envelope_fingerprint"]
                    and preview.mailbox.mailbox_ref == member["mailbox_ref"]
                )
            except (
                CampaignBindingConflict,
                CampaignDeploymentBlocked,
                CampaignInputChanged,
                CampaignNotActionable,
            ):
                valid = False
            if valid:
                retained.append(member)
            else:
                rejected.append(member)
        for member in rejected:
            self._stop_enrolled_member(member, campaign, captured_at)
        if not retained:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.update(acquisition_campaign)
                    .where(acquisition_campaign.c.campaign_ref == campaign_ref)
                    .values(lifecycle="FAILED", updated_at=captured_at)
                )
            raise CampaignInputChanged("campaign has no eligible retained members")
        members = retained
        acquisition = AcquisitionStore(self._engine, clock=lambda: captured_at)
        with self._engine.begin() as connection:
            locked_campaign = connection.execute(
                sa.select(acquisition_campaign)
                .where(acquisition_campaign.c.campaign_ref == campaign_ref)
                .with_for_update()
            ).mappings().one()
            if locked_campaign["lifecycle"] != "BUILDING":
                raise CampaignInputChanged("campaign lifecycle changed before queue")
            for member in members:
                current = acquisition.get_opportunity_in_transaction(
                    connection,
                    member["acquisition_opportunity_id"],
                    for_update=True,
                )
                queued = acquisition.append_in_transaction(
                    connection,
                    current.acquisition_opportunity_id,
                    event_type=EventType.STATE_TRANSITIONED,
                    expected_version=current.stream_version,
                    idempotency_key=f"campaign_queue:{member['member_ref']}",
                    payload={"target_state": "QUEUED", "campaign_ref": campaign_ref},
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-campaign-factory",
                    reason_codes=("CAMPAIGN_MEMBER_QUEUED",),
                    evidence_refs=(f"campaign-member:{member['member_ref']}",),
                    causation_id=member["policy_evaluation_id"],
                    occurred_at=captured_at,
                )
                cleared = acquisition.append_in_transaction(
                    connection,
                    current.acquisition_opportunity_id,
                    event_type=EventType.NEXT_ACTION_SET,
                    expected_version=queued.projection.stream_version,
                    idempotency_key=f"campaign_clear_action:{member['member_ref']}",
                    payload={"next_action": None},
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-campaign-factory",
                    reason_codes=("CAMPAIGN_MEMBER_QUEUED",),
                    evidence_refs=(f"campaign-member:{member['member_ref']}",),
                    causation_id=member["policy_evaluation_id"],
                    occurred_at=captured_at,
                )
                connection.execute(
                    sa.update(acquisition_campaign_member)
                    .where(
                        acquisition_campaign_member.c.member_ref == member["member_ref"],
                        acquisition_campaign_member.c.execution_state == "ENROLLED",
                    )
                    .values(
                        execution_state="QUEUED",
                        queue_event_id=queued.event.event_id,
                        action_clear_event_id=cleared.event.event_id,
                        updated_at=captured_at,
                    )
                )
            connection.execute(
                sa.update(acquisition_campaign)
                .where(acquisition_campaign.c.campaign_ref == campaign_ref)
                .values(lifecycle="SEALED", updated_at=captured_at)
            )
            operation = self._campaigns.plan_operation_in_transaction(
                connection,
                ProviderOperationKind.ACTIVATE_CAMPAIGN,
                campaign_ref=campaign_ref,
                member_ref=None,
                desired_request_fingerprint=locked_campaign[
                    "desired_provider_config_fingerprint"
                ],
                correlation_id=f"activate:{campaign_ref}",
                now=captured_at,
            )
        return operation.operation_ref

    def require_provider_mutation(
        self,
        kind: ProviderOperationKind,
        campaign_ref: str,
        *,
        member_ref: str | None,
        captured_at: dt.datetime,
    ) -> None:
        """Revalidate Kivou authority immediately before provider exposure.

        Provider reconciliation and risk-reduction operations deliberately use
        separate paths: an unknown remote outcome must remain observable, and a
        safety pause must never be prevented by a newly unsafe business input.
        """
        if kind not in {
            ProviderOperationKind.CREATE_CAMPAIGN,
            ProviderOperationKind.CONFIGURE_CAMPAIGN,
            ProviderOperationKind.ADD_LEAD,
        }:
            raise ValueError("operation does not use the provider-exposure guard")
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("provider mutation time must be timezone-aware")
        captured_at = captured_at.astimezone(dt.UTC)
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one_or_none()
            statement = sa.select(acquisition_campaign_member).where(
                acquisition_campaign_member.c.campaign_ref == campaign_ref
            )
            if member_ref is not None:
                statement = statement.where(
                    acquisition_campaign_member.c.member_ref == member_ref
                )
            members = connection.execute(statement).mappings().all()
        if campaign is None or campaign["lifecycle"] != "BUILDING" or not members:
            raise CampaignInputChanged("provider mutation binding is no longer BUILDING")
        self._require_execution_circuit(
            campaign_ref=campaign_ref,
            country=campaign["country"],
            wedge=campaign["wedge"],
            mailbox_refs=tuple(sorted({member["mailbox_ref"] for member in members})),
        )
        if kind is ProviderOperationKind.ADD_LEAD and (
            member_ref is None or len(members) != 1 or members[0]["execution_state"] != "RESERVED"
        ):
            raise CampaignInputChanged("ADD_LEAD requires one exact RESERVED member")
        if kind is ProviderOperationKind.ADD_LEAD and self._attribution_link_builder is None:
            raise CampaignInputChanged("first-party attribution link is unconfigured")
        try:
            control = self._policy_store.get_effective_control(captured_at)
        except (PolicyControlUnavailable, ValidationError, sa.exc.SQLAlchemyError) as exc:
            raise CampaignInputChanged("live Policy control is unavailable") from exc
        if control.kill_switch or control.read_only:
            raise CampaignInputChanged("live Policy safety control blocks provider mutation")
        for member in members:
            try:
                preview = self._build_preview(
                    member["acquisition_opportunity_id"],
                    captured_at,
                    expected_campaign_ref=campaign_ref,
                )
                decision = self._decision(member["policy_evaluation_id"])
            except (
                CampaignBindingConflict,
                CampaignDeploymentBlocked,
                CampaignInputChanged,
                CampaignNotActionable,
            ) as exc:
                raise CampaignInputChanged("provider mutation input changed") from exc
            provenance = member["policy_provenance"]
            approval_refs = [
                item.model_dump(mode="json") for item in decision.approval_refs
            ]
            if not (
                decision.allowed
                and decision.command == "schedule_campaign"
                and decision.evaluation_id == member["policy_evaluation_id"]
                and decision.action_fingerprint == member["policy_action_fingerprint"]
                and decision.action_fingerprint == preview.action_fingerprint
                and decision.policy_version == provenance.get("policy_version")
                and decision.policy_snapshot_id == provenance.get("policy_snapshot_id")
                and decision.control_revision == provenance.get("control_revision")
                and approval_refs == provenance.get("approval_refs")
                and (
                    decision.valid_until is None
                    or captured_at < decision.valid_until
                )
                and preview.input_fingerprint == member["input_fingerprint"]
                and preview.contact_provider_identity_binding
                == member["contact_provider_identity_binding"]
                and preview.plan.campaign_ref == campaign_ref
                and preview.plan.plan_fingerprint == member["plan_fingerprint"]
                and preview.artifact["artifact_fingerprint"]
                == member["personalization_artifact_fingerprint"]
                and preview.assessment["proposal_fingerprint"]
                == member["compliance_assessment_fingerprint"]
                and preview.assessment["ruleset_config_fingerprint"]
                == member["ruleset_fingerprint"]
                and self._sender_config.config_fingerprint
                == member["sender_config_fingerprint"]
                and preview.envelope.envelope_fingerprint
                == member["envelope_fingerprint"]
                and preview.mailbox.mailbox_ref == member["mailbox_ref"]
            ):
                raise CampaignInputChanged("provider mutation authorization changed")

    def _stop_enrolled_member(self, member, campaign, now: dt.datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.member_ref == member["member_ref"],
                    acquisition_campaign_member.c.execution_state == "ENROLLED",
                )
                .values(
                    execution_state="STOPPED",
                    sequence_state="STOPPED",
                    reason_code="PRE_QUEUE_AUTHORIZATION_CHANGED",
                    updated_at=now,
                )
            )
            self._clear_schedule_action_in_transaction(
                connection, member, now, "PRE_QUEUE_AUTHORIZATION_CHANGED"
            )
            if member["provider_lead_id"]:
                self._campaigns.plan_operation_in_transaction(
                    connection,
                    ProviderOperationKind.PAUSE_LEAD,
                    campaign_ref=campaign["campaign_ref"],
                    member_ref=member["member_ref"],
                    desired_request_fingerprint=member["provider_binding_fingerprint"],
                    correlation_id=f"pre-queue-stop:{member['member_ref']}",
                    now=now,
                )

    def stop_before_provider_exposure(
        self, campaign_ref: str, member_ref: str, *, captured_at: dt.datetime
    ) -> None:
        """Make a rejected reserved member non-actionable without provider I/O."""
        with self._engine.begin() as connection:
            member = connection.execute(
                sa.select(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.campaign_ref == campaign_ref,
                    acquisition_campaign_member.c.member_ref == member_ref,
                )
                .with_for_update()
            ).mappings().one()
            if member["execution_state"] != "RESERVED":
                return
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member_ref)
                .values(
                    execution_state="STOPPED",
                    sequence_state="STOPPED",
                    reason_code="PRE_PROVIDER_AUTHORIZATION_CHANGED",
                    updated_at=captured_at,
                )
            )
            self._clear_schedule_action_in_transaction(
                connection, member, captured_at, "PRE_PROVIDER_AUTHORIZATION_CHANGED"
            )

    def stop_after_provider_exposure(
        self,
        campaign_ref: str,
        member_ref: str,
        *,
        provider_lead_id: str,
        binding_fingerprint: str,
        captured_at: dt.datetime,
    ) -> None:
        """Persist reconciled exposure and its risk reduction in one commit."""
        with self._engine.begin() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            member = connection.execute(
                sa.select(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member_ref)
                .with_for_update()
            ).mappings().one()
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member_ref)
                .values(
                    provider_lead_id=provider_lead_id,
                    provider_binding_fingerprint=binding_fingerprint,
                    execution_state="STOPPED",
                    sequence_state="STOPPED",
                    reason_code="POST_PROVIDER_AUTHORIZATION_CHANGED",
                    updated_at=captured_at,
                )
            )
            self._clear_schedule_action_in_transaction(
                connection, member, captured_at, "POST_PROVIDER_AUTHORIZATION_CHANGED"
            )
            self._campaigns.plan_operation_in_transaction(
                connection,
                ProviderOperationKind.PAUSE_LEAD,
                campaign_ref=campaign_ref,
                member_ref=member_ref,
                desired_request_fingerprint=binding_fingerprint,
                correlation_id=f"post-provider-stop:{member_ref}",
                now=captured_at,
            )
            self._campaigns.plan_operation_in_transaction(
                connection,
                ProviderOperationKind.PAUSE_CAMPAIGN,
                campaign_ref=campaign_ref,
                member_ref=None,
                desired_request_fingerprint=campaign[
                    "desired_provider_config_fingerprint"
                ],
                correlation_id=f"post-provider-stop:{campaign_ref}",
                now=captured_at,
            )

    def _clear_schedule_action_in_transaction(
        self,
        connection: sa.Connection,
        member,
        now: dt.datetime,
        reason: str,
    ) -> None:
        current = self._acquisition.get_opportunity_in_transaction(
            connection,
            member["acquisition_opportunity_id"],
            for_update=True,
        )
        if current.next_action != "schedule_campaign":
            return
        self._acquisition.append_in_transaction(
            connection,
            current.acquisition_opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=current.stream_version,
            idempotency_key=f"campaign_stop_action:{member['member_ref']}:{reason}",
            payload={"next_action": None},
            actor_type=ActorType.SYSTEM,
            actor_ref="kivou-campaign-factory",
            reason_codes=(reason,),
            evidence_refs=(f"campaign-member:{member['member_ref']}",),
            causation_id=member["policy_evaluation_id"],
            occurred_at=now,
        )

    def require_activation(self, campaign_ref: str, *, captured_at: dt.datetime) -> None:
        self._require_activation_capabilities()
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            members = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.campaign_ref == campaign_ref
                )
            ).mappings().all()
        if campaign["lifecycle"] != "SEALED" or not members:
            raise CampaignInputChanged("only a SEALED campaign may activate")
        self._require_execution_circuit(
            campaign_ref=campaign_ref,
            country=campaign["country"],
            wedge=campaign["wedge"],
            mailbox_refs=tuple(sorted({member["mailbox_ref"] for member in members})),
        )
        retained = tuple(
            member for member in members if member["execution_state"] == "QUEUED"
        )
        excluded = tuple(
            member
            for member in members
            if member["execution_state"] in {"STOPPED", "FAILED"}
        )
        if not retained or len(retained) + len(excluded) != len(members):
            raise CampaignInputChanged(
                "every retained member must be QUEUED and every exclusion terminal"
            )
        with self._engine.connect() as connection:
            for member in excluded:
                if member["provider_lead_id"] is None:
                    continue
                pause_confirmed = connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(acquisition_provider_operation)
                    .where(
                        acquisition_provider_operation.c.campaign_ref == campaign_ref,
                        acquisition_provider_operation.c.member_ref
                        == member["member_ref"],
                        acquisition_provider_operation.c.kind
                        == ProviderOperationKind.PAUSE_LEAD.value,
                        acquisition_provider_operation.c.state == "CONFIRMED",
                    )
                )
                if int(pause_confirmed or 0) == 0:
                    raise CampaignInputChanged(
                        "excluded provider membership is not proven non-sendable"
                    )
        if captured_at >= campaign["step_1_authorization_deadline"].replace(tzinfo=dt.UTC):
            raise CampaignInputChanged("Step 1 authorization window expired")
        try:
            control = self._policy_store.get_effective_control(captured_at)
        except (PolicyControlUnavailable, ValidationError, sa.exc.SQLAlchemyError) as exc:
            for member in retained:
                self._stop_pre_activation_member(
                    member, campaign, captured_at, "LIVE_POLICY_CONTROL_UNAVAILABLE"
                )
            raise CampaignDeploymentBlocked("live Policy control unavailable") from exc
        if control.kill_switch or control.read_only:
            for member in members:
                self._stop_pre_activation_member(
                    member, campaign, captured_at, "LIVE_POLICY_HARD_STOP"
                )
            raise CampaignDeploymentBlocked("live Policy safety control blocks activation")
        for member in retained:
            decision = self._decision(member["policy_evaluation_id"])
            provenance = member["policy_provenance"]
            exact_policy = bool(
                decision.allowed
                and decision.command == "schedule_campaign"
                and decision.evaluation_id == member["policy_evaluation_id"]
                and decision.action_fingerprint == member["policy_action_fingerprint"]
                and decision.policy_version == provenance.get("policy_version")
                and decision.policy_snapshot_id == provenance.get("policy_snapshot_id")
                and decision.control_revision == provenance.get("control_revision")
                and [item.model_dump(mode="json") for item in decision.approval_refs]
                == provenance.get("approval_refs")
            )
            if not exact_policy or (
                decision.valid_until is not None
                and captured_at >= decision.valid_until
            ):
                self._stop_pre_activation_member(
                    member,
                    campaign,
                    captured_at,
                    "POLICY_FRESHNESS_EXPIRED",
                )
                raise CampaignInputChanged(
                    "Policy freshness or binding changed before activation"
                )
            try:
                self._require_queued_member_current(member, campaign, captured_at)
            except CampaignInputChanged:
                self._stop_pre_activation_member(
                    member,
                    campaign,
                    captured_at,
                    "PRE_ACTIVATION_AUTHORIZATION_CHANGED",
                )
                raise

    def _stop_pre_activation_member(
        self, member, campaign, now: dt.datetime, reason: str
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.member_ref == member["member_ref"],
                    acquisition_campaign_member.c.execution_state == "QUEUED",
                )
                .values(
                    execution_state="STOPPED",
                    sequence_state="STOPPED",
                    reason_code=reason,
                    updated_at=now,
                )
            )
            if member["provider_lead_id"]:
                self._campaigns.plan_operation_in_transaction(
                    connection,
                    ProviderOperationKind.PAUSE_LEAD,
                    campaign_ref=campaign["campaign_ref"],
                    member_ref=member["member_ref"],
                    desired_request_fingerprint=member["provider_binding_fingerprint"],
                    correlation_id=f"pre-activation-stop:{member['member_ref']}",
                    now=now,
                )

    def require_step_2_safety(
        self, campaign_ref: str, *, captured_at: dt.datetime
    ) -> None:
        """Apply current hard-stop controls without re-running historical Policy."""
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            all_members = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.campaign_ref == campaign_ref
                )
            ).mappings().all()
        members = tuple(
            member
            for member in all_members
            if member["sequence_state"] == "WAITING_STEP2"
        )
        if not members:
            raise CampaignDeploymentBlocked("no member is waiting for Step 2")
        self._require_execution_circuit(
            campaign_ref=campaign_ref,
            country=campaign["country"],
            wedge=campaign["wedge"],
            mailbox_refs=tuple(sorted({member["mailbox_ref"] for member in all_members})),
        )
        if campaign["lifecycle"] != "PAUSED":
            raise CampaignDeploymentBlocked(
                "provider campaign must be durably PAUSED before Step 2 safety release"
            )
        if any(
            member["sequence_state"] == "PENDING_STEP1" for member in all_members
        ):
            raise CampaignDeploymentBlocked(
                "Step 1 membership is unresolved before Step 2 release"
            )
        excluded = tuple(
            member
            for member in all_members
            if member["sequence_state"] in {"STOPPED", "FAILED"}
        )
        with self._engine.connect() as connection:
            for member in excluded:
                if member["provider_lead_id"] is None:
                    raise CampaignDeploymentBlocked(
                        "excluded Step 2 member has no provider binding proof"
                    )
                pause_confirmed = connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(acquisition_provider_operation)
                    .where(
                        acquisition_provider_operation.c.campaign_ref == campaign_ref,
                        acquisition_provider_operation.c.member_ref
                        == member["member_ref"],
                        acquisition_provider_operation.c.kind
                        == ProviderOperationKind.PAUSE_LEAD.value,
                        acquisition_provider_operation.c.state == "CONFIRMED",
                    )
                )
                if int(pause_confirmed or 0) == 0:
                    raise CampaignDeploymentBlocked(
                        "excluded Step 2 member is not proven non-sendable"
                    )
        deadline = campaign["step_2_authorization_deadline"]
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=dt.UTC)
        due_values = []
        for member in members:
            due = member["step_2_due_at"]
            if due is None:
                self._stop_step_2_members(
                    campaign,
                    members,
                    captured_at,
                    reason="STEP2_TIMING_UNAVAILABLE",
                    pause_campaign=True,
                )
                raise CampaignDeploymentBlocked("Step 2 timing is unavailable")
            if due.tzinfo is None:
                due = due.replace(tzinfo=dt.UTC)
            due_values.append(due)
        if captured_at < max(due_values) or captured_at >= deadline:
            raise CampaignDeploymentBlocked("Step 2 is outside its one authorized window")
        try:
            control = self._policy_store.get_effective_control(captured_at)
        except (PolicyControlUnavailable, ValidationError, sa.exc.SQLAlchemyError) as exc:
            self._stop_step_2_members(
                campaign,
                members,
                captured_at,
                reason="LIVE_POLICY_CONTROL_UNAVAILABLE",
                pause_campaign=True,
            )
            raise CampaignDeploymentBlocked("live Policy control unavailable") from exc
        if control.kill_switch or control.read_only:
            reason = "KILL_SWITCH_ACTIVE" if control.kill_switch else "READ_ONLY_ACTIVE"
            self._stop_step_2_members(
                campaign,
                members,
                captured_at,
                reason=reason,
                pause_campaign=True,
            )
            label = "kill_switch" if control.kill_switch else "read_only"
            raise CampaignDeploymentBlocked(f"live {label} safety control blocks Step 2")
        for member in members:
            suppression = self._suppressions.match_contact(member["contact_ref"])
            if suppression.state is not SuppressionMatchState.CLEAR:
                self._stop_step_2_members(
                    campaign,
                    (member,),
                    captured_at,
                    reason="SUPPRESSION_NOT_CLEAR",
                    pause_campaign=False,
                )
                raise CampaignDeploymentBlocked("current suppression blocks Step 2")
            mailbox = next(
                (
                    item
                    for item in self._deployment.mailbox_catalog.usable_entries
                    if item.mailbox_ref == member["mailbox_ref"]
                ),
                None,
            )
            if mailbox is None:
                self._stop_step_2_members(
                    campaign,
                    (member,),
                    captured_at,
                    reason="MAILBOX_BINDING_UNAVAILABLE",
                    pause_campaign=True,
                )
                raise CampaignDeploymentBlocked("mailbox UNKNOWN before Step 2")
            readiness = self._mailbox_readiness.get(
                mailbox.provider_account_id, observed_at=captured_at
            )
            if readiness.state is MailboxReadinessState.TEMPORARILY_UNAVAILABLE:
                self._campaigns.plan_operation(
                    ProviderOperationKind.PAUSE_CAMPAIGN,
                    campaign_ref=campaign_ref,
                    member_ref=None,
                    desired_request_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                    correlation_id=f"step2-temporary-pause:{campaign_ref}",
                    now=captured_at,
                )
                raise CampaignDeploymentBlocked("mailbox temporarily unavailable")
            if readiness.state is not MailboxReadinessState.READY:
                self._stop_step_2_members(
                    campaign,
                    (member,),
                    captured_at,
                    reason=f"MAILBOX_{readiness.state.value}",
                    pause_campaign=True,
                )
                raise CampaignDeploymentBlocked(
                    f"mailbox {readiness.state.value} before Step 2"
                )

    def _stop_step_2_members(
        self,
        campaign,
        members,
        now: dt.datetime,
        *,
        reason: str,
        pause_campaign: bool,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.member_ref.in_(
                        [member["member_ref"] for member in members]
                    ),
                    acquisition_campaign_member.c.sequence_state == "WAITING_STEP2",
                )
                .values(sequence_state="STOPPED", reason_code=reason, updated_at=now)
            )
            if pause_campaign:
                self._campaigns.plan_operation_in_transaction(
                    connection,
                    ProviderOperationKind.PAUSE_CAMPAIGN,
                    campaign_ref=campaign["campaign_ref"],
                    member_ref=None,
                    desired_request_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                    correlation_id=f"risk-reduction:{reason}:{campaign['campaign_ref']}",
                    now=now,
                )
            else:
                for member in members:
                    if member["provider_lead_id"]:
                        self._campaigns.plan_operation_in_transaction(
                            connection,
                            ProviderOperationKind.PAUSE_LEAD,
                            campaign_ref=campaign["campaign_ref"],
                            member_ref=member["member_ref"],
                            desired_request_fingerprint=member[
                                "provider_binding_fingerprint"
                            ],
                            correlation_id=f"risk-reduction:{reason}:{member['member_ref']}",
                            now=now,
                        )

    def _require_queued_member_current(self, member, campaign, captured_at: dt.datetime) -> None:
        with self._engine.connect() as connection:
            opportunity = self._acquisition.get_opportunity_in_transaction(
                connection, member["acquisition_opportunity_id"]
            )
            artifact = connection.execute(
                sa.select(acquisition_personalization_artifact).where(
                    acquisition_personalization_artifact.c.personalization_artifact_id
                    == member["personalization_artifact_id"],
                    acquisition_personalization_artifact.c.disposition == "READY",
                )
            ).mappings().one_or_none()
            assessment = connection.execute(
                sa.select(acquisition_compliance_assessment).where(
                    acquisition_compliance_assessment.c.compliance_assessment_id
                    == member["compliance_assessment_id"],
                    acquisition_compliance_assessment.c.disposition == "RECORDED",
                    acquisition_compliance_assessment.c.state == "ALLOWED",
                )
            ).mappings().one_or_none()
            supplier = connection.execute(
                sa.select(acquisition_supplier).where(
                    acquisition_supplier.c.supplier_ref == member["supplier_ref"]
                )
            ).mappings().one_or_none()
            contact = connection.execute(
                sa.select(acquisition_contact).where(
                    acquisition_contact.c.contact_ref == member["contact_ref"]
                )
            ).mappings().one_or_none()
            profile = connection.execute(
                sa.select(acquisition_company_profile).where(
                    acquisition_company_profile.c.acquisition_opportunity_id
                    == member["acquisition_opportunity_id"]
                )
            ).mappings().one_or_none()
            suppression = self._suppressions.match_contact_in_transaction(
                connection, member["contact_ref"]
            )
        current_bindings = False
        if supplier is not None and contact is not None and profile is not None and assessment:
            snapshot = assessment["input_snapshot"]
            current_jurisdiction = resolve_jurisdiction(
                supplier_country_code=supplier["country_code"],
                provider_country=profile["provider_country"],
                supplier_ref=supplier["supplier_ref"],
                profile_ref=(
                    "acquisition-company-profile:"
                    f"{member['acquisition_opportunity_id']}"
                ),
            )
            current_identity_binding = semantic_fingerprint(
                {
                    "kind": "campaign-contact-provider-identity-v1",
                    "identities": self._keyring.identities_for_email(
                        contact["business_email"]
                    ),
                }
            )
            current_bindings = bool(
                contact["supplier_ref"] == supplier["supplier_ref"] == member["supplier_ref"]
                and profile["supplier_ref"] == supplier["supplier_ref"]
                and profile["contact_ref"] == contact["contact_ref"] == member["contact_ref"]
                and profile["signal_ref"] == opportunity.signal_ref
                and artifact is not None
                and profile["prebuild_fingerprint"]
                == artifact["input_snapshot"].get("company_prebuild_fingerprint")
                and contact["verification_state"]
                == snapshot.get("contact_verification_state")
                and contact["verification_provider"]
                == snapshot.get("contact_verification_provider")
                and contact["provider_email_status"]
                == snapshot.get("contact_provider_email_status")
                and contact["source_fingerprint"]
                == snapshot.get("contact_source_fingerprint")
                and contact["role_profile_version"]
                == snapshot.get("contact_role_profile_version")
                and contact["role_tier"] == snapshot.get("contact_role_tier")
                and current_jurisdiction.model_dump(mode="json")
                == snapshot.get("jurisdiction")
                and current_identity_binding
                == member["contact_provider_identity_binding"]
            )
        if not (
            opportunity.state is AcquisitionState.QUEUED
            and opportunity.campaign_ref == campaign["campaign_ref"]
            and opportunity.next_action is None
            and artifact is not None
            and assessment is not None
            and artifact["artifact_fingerprint"]
            == member["personalization_artifact_fingerprint"]
            and assessment["proposal_fingerprint"]
            == member["compliance_assessment_fingerprint"]
            and assessment["ruleset_config_fingerprint"] == member["ruleset_fingerprint"]
            and suppression.state is SuppressionMatchState.CLEAR
            and current_bindings
        ):
            raise CampaignInputChanged("queued member binding/suppression changed")
        valid_until = assessment["valid_until"]
        if valid_until is None or valid_until.replace(tzinfo=dt.UTC) <= captured_at:
            raise CampaignInputChanged("compliance freshness expired before activation")
        mailbox = next(
            (
                item
                for item in self._deployment.mailbox_catalog.usable_entries
                if item.mailbox_ref == member["mailbox_ref"]
            ),
            None,
        )
        if mailbox is None:
            raise CampaignInputChanged("queued mailbox binding is unavailable")
        readiness = self._mailbox_readiness.get(
            mailbox.provider_account_id, observed_at=captured_at
        )
        if readiness.state is MailboxReadinessState.TEMPORARILY_UNAVAILABLE:
            raise CampaignDeploymentBlocked("queued mailbox is no longer READY")
        if readiness.state is not MailboxReadinessState.READY:
            raise CampaignInputChanged("queued mailbox is unsafe or UNKNOWN")

    def attribution_url_for_member(
        self, member: dict[str, object], campaign: dict[str, object]
    ) -> str | None:
        if self._attribution_link_builder is None:
            return None
        with self._engine.connect() as connection:
            payload = self._attribution_source_resolver.for_member(
                connection, str(member["member_ref"])
            )
        return self._attribution_link_builder.build(payload).url

    def _attribution_url(
        self,
        *,
        opportunity_id: str,
        signal_ref: str,
        campaign_ref: str,
        member_ref: str,
        country: str,
        wedge: str,
        wedge_version: str,
        need_ref: str,
        need_version: str,
        timezone: str,
        step_1_execution_date: dt.date,
        step_2_authorization_deadline: dt.datetime,
    ) -> str | None:
        if self._attribution_link_builder is None:
            return None
        payload = self._attribution_source_resolver.from_facts(
            AttributionSourceFacts(
                campaign_ref=campaign_ref,
                member_ref=member_ref,
                acquisition_opportunity_id=opportunity_id,
                signal_ref=signal_ref,
                country=country,
                wedge=wedge,
                wedge_version=wedge_version,
                need_ref=need_ref,
                need_version=need_version,
                timezone=timezone,
                step_1_execution_date=step_1_execution_date,
                step_2_authorization_deadline=step_2_authorization_deadline,
            )
        )
        return self._attribution_link_builder.build(
            payload
        ).url

    def _require_activation_capabilities(self) -> None:
        if self._attribution_link_builder is None:
            raise CampaignDeploymentBlocked("first-party attribution link is unconfigured")
        if self._deployment.transport_contract_proof is not TransportContractProof.VERIFIED:
            raise CampaignDeploymentBlocked("transport contract proof is UNVERIFIED")
        if (
            self._deployment.lead_risk_reduction_contract_proof
            is not LeadRiskReductionContractProof.VERIFIED
        ):
            raise CampaignDeploymentBlocked(
                "per-lead risk-reduction contract proof is UNVERIFIED"
            )
        if self._deployment.webhook_entitlement is not WebhookEntitlement.VERIFIED:
            raise CampaignDeploymentBlocked("webhook entitlement is UNVERIFIED")

    def _decision(self, evaluation_id: str):
        with self._engine.connect() as connection:
            row = self._policy_store.evaluation_row(connection, evaluation_id)
        if row is None:
            raise CampaignInputChanged("Policy evaluation is missing")
        return decision_from_row(row)

    def _build_preview(
        self,
        opportunity_id: str,
        captured_at: dt.datetime,
        *,
        expected_campaign_ref: str | None = None,
    ) -> CampaignPreview:
        with self._engine.connect() as connection:
            opportunity = self._acquisition.get_opportunity_in_transaction(
                connection, opportunity_id
            )
            if not (
                opportunity.state is AcquisitionState.SEND
                and opportunity.decision is Decision.SEND
                and opportunity.next_action == "schedule_campaign"
                and opportunity.supplier_ref
                and opportunity.contact_ref
            ):
                from signals.campaigns.contracts import CampaignNotActionable

                raise CampaignNotActionable(opportunity_id)
            assessment = connection.execute(
                sa.select(acquisition_compliance_assessment)
                .where(
                    acquisition_compliance_assessment.c.acquisition_opportunity_id
                    == opportunity_id,
                    acquisition_compliance_assessment.c.disposition == "RECORDED",
                    acquisition_compliance_assessment.c.state == "ALLOWED",
                    acquisition_compliance_assessment.c.next_action == "schedule_campaign",
                )
                .order_by(acquisition_compliance_assessment.c.created_at.desc())
            ).mappings().first()
            if assessment is None:
                raise CampaignBindingConflict("current ALLOWED compliance is required")
            artifact = connection.execute(
                sa.select(acquisition_personalization_artifact).where(
                    acquisition_personalization_artifact.c.personalization_artifact_id
                    == assessment["personalization_artifact_id"],
                    acquisition_personalization_artifact.c.disposition == "READY",
                )
            ).mappings().one_or_none()
            if artifact is None or not (
                artifact["supplier_ref"] == opportunity.supplier_ref == assessment["supplier_ref"]
                and artifact["contact_ref"] == opportunity.contact_ref == assessment["contact_ref"]
            ):
                raise CampaignBindingConflict("artifact/contact/supplier binding changed")
            supplier = connection.execute(
                sa.select(acquisition_supplier).where(
                    acquisition_supplier.c.supplier_ref == opportunity.supplier_ref
                )
            ).mappings().one_or_none()
            contact = connection.execute(
                sa.select(acquisition_contact).where(
                    acquisition_contact.c.contact_ref == opportunity.contact_ref
                )
            ).mappings().one_or_none()
            profile = connection.execute(
                sa.select(acquisition_company_profile).where(
                    acquisition_company_profile.c.acquisition_opportunity_id
                    == opportunity_id
                )
            ).mappings().one_or_none()
            if supplier is None or contact is None or profile is None:
                raise CampaignBindingConflict("current company/contact binding is missing")
            assessment_snapshot = assessment["input_snapshot"]
            artifact_snapshot = artifact["input_snapshot"]
            jurisdiction = resolve_jurisdiction(
                supplier_country_code=supplier["country_code"],
                provider_country=profile["provider_country"],
                supplier_ref=supplier["supplier_ref"],
                profile_ref=f"acquisition-company-profile:{opportunity_id}",
            )
            if not (
                contact["supplier_ref"] == supplier["supplier_ref"]
                and profile["supplier_ref"] == supplier["supplier_ref"]
                and profile["contact_ref"] == contact["contact_ref"]
                and profile["signal_ref"] == opportunity.signal_ref
                and profile["prebuild_fingerprint"]
                == artifact_snapshot.get("company_prebuild_fingerprint")
                and contact["verification_state"]
                == assessment_snapshot.get("contact_verification_state")
                and contact["verification_provider"]
                == assessment_snapshot.get("contact_verification_provider")
                and contact["provider_email_status"]
                == assessment_snapshot.get("contact_provider_email_status")
                and contact["source_fingerprint"]
                == assessment_snapshot.get("contact_source_fingerprint")
                and contact["role_profile_version"]
                == assessment_snapshot.get("contact_role_profile_version")
                and contact["role_tier"]
                == assessment_snapshot.get("contact_role_tier")
                and jurisdiction.model_dump(mode="json")
                == assessment_snapshot.get("jurisdiction")
            ):
                raise CampaignBindingConflict("current company/contact semantics changed")
            compliance_event = connection.execute(
                sa.select(acquisition_event.c.payload).where(
                    acquisition_event.c.event_id == assessment["recorded_event_id"]
                )
            ).scalar_one_or_none()
            if not compliance_event or compliance_event.get("next_action") != "schedule_campaign":
                raise CampaignBindingConflict("workflow is not bound to this compliance result")
            suppression = self._suppressions.match_contact_in_transaction(
                connection, opportunity.contact_ref
            )
        valid_until = assessment["valid_until"]
        if valid_until is None or valid_until.replace(tzinfo=dt.UTC) <= captured_at:
            raise CampaignBindingConflict("compliance freshness expired before scheduling")
        if suppression.state is not SuppressionMatchState.CLEAR:
            raise CampaignBindingConflict("suppression is not safely clear")
        if assessment["ruleset_config_fingerprint"] != RULESET_V1.config_fingerprint:
            raise CampaignBindingConflict("compliance ruleset binding changed")
        snapshot = assessment["input_snapshot"]
        sender_snapshot = snapshot.get("sender_config", {})
        if sender_snapshot.get("config_fingerprint") != self._sender_config.config_fingerprint:
            raise CampaignBindingConflict("sender compliance config changed")
        mailbox = self._select_mailbox(
            country=assessment["jurisdiction"],
            language=artifact["language"],
            sender_profile_ref=self._sender_config.sender_profile_ref,
        )
        readiness = self._mailbox_readiness.get(
            mailbox.provider_account_id, observed_at=captured_at
        )
        if readiness.state is not MailboxReadinessState.READY:
            raise CampaignDeploymentBlocked("mailbox is not READY")
        if readiness.valid_until is not None and readiness.valid_until <= captured_at:
            raise CampaignDeploymentBlocked("mailbox readiness is stale")
        local = captured_at.astimezone(ZoneInfo(mailbox.timezone))
        if local.weekday() >= 5 or not dt.time(9) <= local.timetz().replace(tzinfo=None) < dt.time(17):
            raise CampaignDeploymentBlocked("send window is closed")
        factory_input = CampaignFactoryInput(
            wedge=self._deployment.wedge,
            wedge_version=self._deployment.wedge_version,
            jurisdiction=assessment["jurisdiction"],
            country=assessment["jurisdiction"],
            language=artifact["language"],
            selected_need_category=artifact["input_snapshot"]["selected_need_category"],
            selected_need_version=artifact["need_engine_version"],
            personalization_catalog_version=artifact["catalog_version"],
            personalization_template_version=artifact["template_version"],
            language_policy_version=artifact["language_policy_version"],
            envelope_catalog_version=self._deployment.footer_catalog.catalog_version,
            sender_profile_ref=self._sender_config.sender_profile_ref,
            mailbox_pool_version=self._deployment.mailbox_pool_version,
            compliance_ruleset_fingerprint=assessment["ruleset_config_fingerprint"],
            step_1_execution_date=local.date(),
        )
        if expected_campaign_ref is None:
            plan = self._campaigns.propose_plan(factory_input, at=captured_at)
        else:
            with self._engine.connect() as connection:
                generation = connection.scalar(
                    sa.select(acquisition_campaign.c.batch_generation).where(
                        acquisition_campaign.c.campaign_ref == expected_campaign_ref
                    )
                )
            plan = (
                self._campaigns.propose_plan(factory_input, at=captured_at)
                if generation is None
                else CampaignFactory().build(factory_input, batch_generation=generation)
            )
            if plan.campaign_ref != expected_campaign_ref:
                raise CampaignInputChanged("campaign semantic grouping changed")
        ruleset_until = snapshot.get("ruleset_valid_until")
        sender_until = sender_snapshot.get("valid_until")
        self._require_sequence_coverage(
            ruleset_until, plan.sequence_window.step_2_authorization_deadline, "ruleset"
        )
        self._require_sequence_coverage(
            sender_until, plan.sequence_window.step_2_authorization_deadline, "sender"
        )
        envelope = build_envelope(
            EnvelopeInput(
                language=artifact["language"],
                sender_profile_ref=self._sender_config.sender_profile_ref,
                subject=artifact["subject"],
                greeting=artifact["greeting"],
                body=artifact["body"],
                cta=artifact["cta"],
                attribution_url=self._attribution_url(
                    opportunity_id=opportunity_id,
                    signal_ref=opportunity.signal_ref,
                    campaign_ref=plan.campaign_ref,
                    member_ref=semantic_fingerprint(
                        {
                            "kind": "campaign-member-v1",
                            "acquisition_opportunity_id": opportunity_id,
                        }
                    ),
                    country=plan.country,
                    wedge=plan.wedge,
                    wedge_version=factory_input.wedge_version,
                    need_ref=plan.selected_need_category,
                    need_version=factory_input.selected_need_version,
                    timezone=plan.sequence_window.timezone,
                    step_1_execution_date=plan.sequence_window.step_1_execution_date,
                    step_2_authorization_deadline=(
                        plan.sequence_window.step_2_authorization_deadline
                    ),
                ),
                catalog=self._deployment.footer_catalog,
            )
        )
        evidence_refs = tuple(
            dict.fromkeys(
                (
                    *assessment["evidence_refs"],
                    f"campaign-plan:{plan.plan_fingerprint}",
                    f"mailbox-readiness:{readiness.readiness_fingerprint}",
                )
            )
        )[:16]
        contact_provider_identity_binding = semantic_fingerprint(
            {
                "kind": "campaign-contact-provider-identity-v1",
                "identities": self._keyring.identities_for_email(
                    contact["business_email"]
                ),
            }
        )
        input_values = {
            "opportunity_id": opportunity_id,
            "supplier_ref": opportunity.supplier_ref,
            "contact_ref": opportunity.contact_ref,
            "artifact_id": artifact["personalization_artifact_id"],
            "artifact_fingerprint": artifact["artifact_fingerprint"],
            "assessment_id": assessment["compliance_assessment_id"],
            "assessment_fingerprint": assessment["proposal_fingerprint"],
            "plan_fingerprint": plan.plan_fingerprint,
            "envelope_fingerprint": envelope.envelope_fingerprint,
            "mailbox_ref": mailbox.mailbox_ref,
            "mailbox_readiness_state": readiness.state.value,
            "mailbox_provider_daily_limit": readiness.provider_daily_limit,
            "mailbox_sending_gap_seconds": readiness.sending_gap_seconds,
            "contact_provider_identity_binding": contact_provider_identity_binding,
        }
        input_fingerprint = semantic_fingerprint(
            {"kind": "campaign-input-v1", **input_values}
        )
        action_fingerprint = semantic_fingerprint(
            {"kind": "schedule-campaign-action-v1", "command": "schedule_campaign", **input_values}
        )
        return CampaignPreview(
            opportunity_id=opportunity_id,
            captured_at=captured_at,
            plan=plan,
            envelope=envelope,
            mailbox=mailbox,
            readiness=readiness,
            assessment=dict(assessment),
            artifact=dict(artifact),
            input_fingerprint=input_fingerprint,
            action_fingerprint=action_fingerprint,
            evidence_refs=evidence_refs,
            contact_provider_identity_binding=contact_provider_identity_binding,
        )

    def _factory_input(self, preview: CampaignPreview) -> CampaignFactoryInput:
        artifact = preview.artifact
        return CampaignFactoryInput(
            wedge=self._deployment.wedge,
            wedge_version=self._deployment.wedge_version,
            jurisdiction=preview.plan.jurisdiction,
            country=preview.plan.country,
            language=preview.plan.language,
            selected_need_category=preview.plan.selected_need_category,
            selected_need_version=artifact["need_engine_version"],
            personalization_catalog_version=artifact["catalog_version"],
            personalization_template_version=artifact["template_version"],
            language_policy_version=artifact["language_policy_version"],
            envelope_catalog_version=self._deployment.footer_catalog.catalog_version,
            sender_profile_ref=preview.plan.sender_profile_ref,
            mailbox_pool_version=self._deployment.mailbox_pool_version,
            compliance_ruleset_fingerprint=preview.plan.compliance_ruleset_fingerprint,
            step_1_execution_date=preview.plan.sequence_window.step_1_execution_date,
        )

    def _policy_request(
        self,
        authorization: CampaignAuthorizationInput,
        preview: CampaignPreview,
        *,
        expected_version: int,
    ) -> PolicyRequest:
        assessment = preview.assessment
        return PolicyRequest(
            evaluation_id=authorization.evaluation_id,
            request_id=authorization.request_id,
            command="schedule_campaign",
            target_ref=f"acquisition-opportunity:{preview.opportunity_id}",
            acquisition_opportunity_id=preview.opportunity_id,
            expected_opportunity_version=expected_version,
            actor_type=authorization.actor_type,
            actor_ref=authorization.actor_ref,
            qa_signal_ref=authorization.qa_signal_ref,
            canonical_arguments=json.dumps(
                {
                    "campaign_input_fingerprint": preview.input_fingerprint,
                    "campaign_plan_fingerprint": preview.plan.plan_fingerprint,
                    "envelope_fingerprint": preview.envelope.envelope_fingerprint,
                    "mailbox_ref": preview.mailbox.mailbox_ref,
                    "sequence_window": preview.plan.sequence_window.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            action_fingerprint=preview.action_fingerprint,
            scope=authorization.scope,
            proposed_cost=Decimal("0"),
            currency=authorization.currency,
            proposed_volume=1,
            reason_codes=("CAMPAIGN_SEQUENCE_PROPOSED",),
            evidence_refs=preview.evidence_refs,
            evidence=EvidenceReadiness(
                status=EvidenceStatus.READY,
                claims=_SCHEDULE_EVIDENCE,
                assessment_version="campaign-evidence-v1",
                observed_at=preview.captured_at,
                valid_until=preview.readiness.valid_until,
            ),
            compliance=ComplianceAssessment(
                state=ComplianceState.ALLOWED,
                assessment_version=assessment["ruleset_version"],
                observed_at=assessment["created_at"].replace(tzinfo=dt.UTC),
                valid_until=assessment["valid_until"].replace(tzinfo=dt.UTC),
            ),
            operational=authorization.operational,
            expected_policy_version=authorization.expected_policy_version,
            approval_grants=authorization.approval_grants,
            supervisor_plan_id=authorization.supervisor_plan_id,
            supervisor_action_index=authorization.supervisor_action_index,
            supervisor_version=authorization.supervisor_version,
            skill_version=authorization.skill_version,
        )

    def _select_mailbox(self, *, country: str, language: str, sender_profile_ref: str):
        matches = tuple(
            entry
            for entry in self._deployment.mailbox_catalog.usable_entries
            if country in entry.eligible_countries
            and language in entry.eligible_languages
            and self._deployment.wedge in entry.eligible_wedges
            and entry.sender_profile_ref == sender_profile_ref
        )
        if len(matches) != 1:
            raise CampaignDeploymentBlocked("exactly one eligible mailbox is required")
        return matches[0]

    def _require_deployment_planning(self) -> None:
        if not self._deployment.provider_workspace_ref:
            raise CampaignDeploymentBlocked("provider workspace is unconfigured")
        if not self._deployment.wedge:
            raise CampaignDeploymentBlocked("Kivou wedge is unconfigured")
        if not self._deployment.mailbox_catalog.usable_entries:
            raise CampaignDeploymentBlocked("mailbox catalog has zero usable entries")
        if not self._deployment.footer_catalog.entries:
            raise CampaignDeploymentBlocked("footer catalog is unconfigured")

    def _require_execution_circuit(
        self,
        *,
        campaign_ref: str,
        country: str,
        wedge: str,
        mailbox_refs: tuple[str, ...],
    ) -> None:
        scopes = (
            BreakerScope(scope_type="CAMPAIGN", scope_ref=campaign_ref),
            BreakerScope(scope_type="COUNTRY", scope_ref=country),
            BreakerScope(scope_type="WEDGE", scope_ref=wedge),
            *(
                BreakerScope(scope_type="MAILBOX", scope_ref=mailbox_ref)
                for mailbox_ref in mailbox_refs
            ),
        )
        try:
            self._execution_guard.require_allowed(*scopes)
        except AcquisitionCircuitOpen as exc:
            raise CampaignDeploymentBlocked("acquisition execution circuit is open") from exc

    @staticmethod
    def _require_sequence_coverage(raw, deadline: dt.datetime, kind: str) -> None:
        if raw is None:
            return
        boundary = dt.datetime.fromisoformat(raw) if isinstance(raw, str) else raw
        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=dt.UTC)
        if boundary < deadline:
            raise CampaignDeploymentBlocked(f"{kind} validity does not cover Step 2")

    @staticmethod
    def _provider_config_fingerprint(preview: CampaignPreview) -> str:
        window = preview.plan.sequence_window
        config = build_provider_campaign_config(
            step_1_execution_date=window.step_1_execution_date,
            step_2_execution_date=window.step_2_execution_date,
            timezone=window.timezone,
            provider_account_id=preview.mailbox.provider_account_id,
            daily_limit=min(3, preview.mailbox.kivou_daily_cap),
        )
        return provider_campaign_config_fingerprint(preview.plan.campaign_ref, config)

    def _existing_result(
        self,
        evaluation_id: str,
        opportunity_id: str,
        *,
        authorization_fingerprint: str,
    ) -> CampaignScheduleResult | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.policy_evaluation_id == evaluation_id
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            if (
                row["acquisition_opportunity_id"] != opportunity_id
                or row["policy_provenance"].get("authorization_fingerprint")
                != authorization_fingerprint
            ):
                raise CampaignIdempotencyConflict(
                    "campaign replay authorization semantics changed"
                )
            policy_row = self._policy_store.evaluation_row(connection, evaluation_id)
            if policy_row is None:
                raise CampaignInputChanged("campaign member has no Policy evaluation")
            decision = decision_from_row(policy_row)
            return CampaignScheduleResult(
                disposition="PLANNED",
                policy_status=decision.status.value,
                campaign_ref=row["campaign_ref"],
                member_ref=row["member_ref"],
                execution_state=row["execution_state"],
                replayed=True,
            )

    @staticmethod
    def _authorization_fingerprint(
        authorization: CampaignAuthorizationInput, budget_usage: BudgetUsage
    ) -> str:
        return semantic_fingerprint(
            {
                "kind": "campaign-authorization-replay-v1",
                "authorization": authorization.model_dump(mode="json"),
                "budget_usage": budget_usage.model_dump(mode="json"),
            }
        )

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("campaign clock must be timezone-aware")
        return value.astimezone(dt.UTC)
