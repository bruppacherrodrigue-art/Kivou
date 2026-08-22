"""Immutable, versioned contracts for SPEC-026 campaign execution."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from signals.decision_engine.policy import semantic_fingerprint
from signals.policy.contracts import (
    MAX_APPROVAL_GRANTS,
    ApprovalGrant,
    Currency,
    EvidenceReadiness,
    OperationalReadiness,
    Scope,
)

CAMPAIGN_FACTORY_VERSION = "campaign-factory-v1"
CAMPAIGN_ENVELOPE_VERSION = "campaign-envelope-v1"
CAMPAIGN_SEQUENCE_POLICY_VERSION = "campaign-sequence-policy-v1"
BATCH_SEAL_POLICY_VERSION = "batch-seal-policy-v1"
SEND_WINDOW_POLICY_VERSION = "send-window-policy-v1"
SEQUENCE_WINDOW_POLICY_VERSION = "sequence-window-policy-v1"
TRACKING_POLICY_VERSION = "tracking-policy-v1"
PACING_POLICY_VERSION = "pacing-policy-v1"
PROVIDER_STOP_POLICY_VERSION = "provider-stop-policy-v1"
PROVIDER_OPERATION_VERSION = "provider-operation-v1"
PROVIDER_EVENT_FINGERPRINT_VERSION = "provider-event-fingerprint-v2"
PROVIDER_OPERATION_MAX_ATTEMPTS = 3

StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ShortCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CampaignContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class CampaignLifecycle(StrEnum):
    BUILDING = "BUILDING"
    SEALED = "SEALED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MemberExecutionState(StrEnum):
    RESERVED = "RESERVED"
    ENROLLED = "ENROLLED"
    QUEUED = "QUEUED"
    STOPPED = "STOPPED"
    SENT = "SENT"
    FAILED = "FAILED"


class MemberSequenceState(StrEnum):
    PENDING_STEP1 = "PENDING_STEP1"
    WAITING_STEP2 = "WAITING_STEP2"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ProviderOperationKind(StrEnum):
    CREATE_CAMPAIGN = "CREATE_CAMPAIGN"
    CONFIGURE_CAMPAIGN = "CONFIGURE_CAMPAIGN"
    ADD_LEAD = "ADD_LEAD"
    ACTIVATE_CAMPAIGN = "ACTIVATE_CAMPAIGN"
    PAUSE_CAMPAIGN = "PAUSE_CAMPAIGN"
    PAUSE_LEAD = "PAUSE_LEAD"


class ProviderOperationState(StrEnum):
    PLANNED = "PLANNED"
    IN_FLIGHT = "IN_FLIGHT"
    CONFIRMED = "CONFIRMED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    TERMINAL_FAILED = "TERMINAL_FAILED"


class MailboxReadinessState(StrEnum):
    READY = "READY"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class TransportContractProof(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class LeadRiskReductionContractProof(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class WebhookEntitlement(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class ResponseIngressCapability(StrEnum):
    NONE = "NONE"
    SPEC027_V1 = "SPEC027_V1"


class BatchSealPolicy(CampaignContract):
    policy_version: Literal["batch-seal-policy-v1"] = BATCH_SEAL_POLICY_VERSION
    maximum_members: Literal[10] = 10
    maximum_assembly_seconds: Literal[900] = 900


class TrackingPolicy(CampaignContract):
    policy_version: Literal["tracking-policy-v1"] = TRACKING_POLICY_VERSION
    open_tracking: Literal[False] = False
    link_tracking: Literal[False] = False
    text_only: Literal[True] = True
    first_email_text_only: Literal[True] = True
    auto_variant_select: Literal[False] = False
    ai_sdr: Literal[False] = False
    spintax: Literal[False] = False
    liquid: Literal[False] = False
    allow_risky_contacts: Literal[False] = False
    bounce_protection: Literal[True] = True
    insert_unsubscribe_header: Literal[True] = True


class ProviderStopPolicy(CampaignContract):
    policy_version: Literal["provider-stop-policy-v1"] = PROVIDER_STOP_POLICY_VERSION
    stop_on_reply: Literal[True] = True
    stop_on_auto_reply: Literal[True] = True
    stop_for_company: Literal[False] = False


class PacingPolicy(CampaignContract):
    policy_version: Literal["pacing-policy-v1"] = PACING_POLICY_VERSION
    autonomous_live_cap: Literal[0] = 0
    global_daily_cap: Literal[5] = 5
    country_daily_cap: Literal[5] = 5
    wedge_daily_cap: Literal[3] = 3
    mailbox_daily_cap: Literal[3] = 3
    micro_campaign_member_cap: Literal[10] = 10
    company_rolling_30d_cap: Literal[1] = 1


class FooterCatalogEntry(CampaignContract):
    language: Literal["fr", "en"]
    sender_profile_ref: StableRef
    sender_identity: StableRef
    source_notice: StableRef
    privacy_route: StableRef
    visible_opt_out: StableRef

    @field_validator("sender_identity", "source_notice", "privacy_route", "visible_opt_out")
    @classmethod
    def forbid_template_syntax(cls, value: str) -> str:
        if any(token in value for token in ("{{", "}}", "{%", "%}", "[[", "]]")):
            raise ValueError("template syntax is forbidden in the footer catalog")
        return value


class FooterCatalog(CampaignContract):
    catalog_version: ShortCode = "footer-catalog-unconfigured-v1"
    entries: tuple[FooterCatalogEntry, ...] = ()
    catalog_fingerprint: Fingerprint | None = None

    @model_validator(mode="after")
    def fingerprint_catalog(self) -> FooterCatalog:
        identities = [(item.language, item.sender_profile_ref) for item in self.entries]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate footer catalog binding")
        expected = semantic_fingerprint(
            {"kind": "campaign-footer-catalog-v1", **self.model_dump(mode="json", exclude={"catalog_fingerprint"})}
        )
        if self.catalog_fingerprint not in (None, expected):
            raise ValueError("footer catalog fingerprint mismatch")
        object.__setattr__(self, "catalog_fingerprint", expected)
        return self


class MailboxCatalogEntry(CampaignContract):
    mailbox_ref: StableRef
    provider_account_id: StableRef
    sender_profile_ref: StableRef
    eligible_countries: tuple[Literal["CH", "FR"], ...] = Field(min_length=1, max_length=2)
    eligible_languages: tuple[Literal["fr", "en"], ...] = Field(min_length=1, max_length=2)
    eligible_wedges: tuple[ShortCode, ...] = Field(min_length=1, max_length=16)
    domain_ref: StableRef
    timezone: Literal["Europe/Zurich", "Europe/Paris"]
    kivou_daily_cap: int = Field(ge=0, le=5)
    kivou_campaign_cap: int = Field(ge=0, le=10)
    config_version: ShortCode
    config_fingerprint: Fingerprint
    enabled: bool = False


class MailboxCatalog(CampaignContract):
    catalog_version: ShortCode = "mailbox-catalog-unconfigured-v1"
    entries: tuple[MailboxCatalogEntry, ...] = ()

    @property
    def usable_entries(self) -> tuple[MailboxCatalogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.enabled)


class MailboxReadiness(CampaignContract):
    state: MailboxReadinessState
    provider_daily_limit: int = Field(ge=0, le=100000)
    sending_gap_seconds: int = Field(ge=0, le=86400)
    observed_at: dt.datetime
    valid_until: dt.datetime | None = None
    readiness_fingerprint: Fingerprint | None = None

    _times = field_validator("observed_at", "valid_until")(_aware)

    @model_validator(mode="after")
    def fingerprint_readiness(self) -> MailboxReadiness:
        expected = semantic_fingerprint(
            {
                "kind": "mailbox-readiness-v1",
                **self.model_dump(mode="json", exclude={"readiness_fingerprint"}),
            }
        )
        if self.readiness_fingerprint not in (None, expected):
            raise ValueError("mailbox readiness fingerprint mismatch")
        object.__setattr__(self, "readiness_fingerprint", expected)
        return self


class CampaignDeploymentConfig(CampaignContract):
    provider_workspace_ref: StableRef | None = None
    wedge: ShortCode | None = None
    wedge_version: ShortCode = "wedge-unconfigured-v1"
    mailbox_pool_version: ShortCode = "mailbox-pool-unconfigured-v1"
    mailbox_catalog: MailboxCatalog = MailboxCatalog()
    footer_catalog: FooterCatalog = FooterCatalog()
    transport_contract_proof: TransportContractProof = TransportContractProof.UNVERIFIED
    lead_risk_reduction_contract_proof: LeadRiskReductionContractProof = (
        LeadRiskReductionContractProof.UNVERIFIED
    )
    webhook_entitlement: WebhookEntitlement = WebhookEntitlement.UNVERIFIED
    response_ingress_capability: ResponseIngressCapability = ResponseIngressCapability.NONE

    @model_validator(mode="after")
    def require_risk_reduction_for_transport_proof(self) -> CampaignDeploymentConfig:
        if (
            self.transport_contract_proof is TransportContractProof.VERIFIED
            and self.lead_risk_reduction_contract_proof
            is not LeadRiskReductionContractProof.VERIFIED
        ):
            raise ValueError(
                "transport proof cannot be VERIFIED without contract-proven "
                "per-lead risk reduction"
            )
        return self


class CampaignAuthorizationInput(CampaignContract):
    evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    request_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HERMES|HUMAN)$")]
    actor_ref: StableRef | None = None
    scope: Scope
    currency: Currency
    evidence: EvidenceReadiness
    operational: OperationalReadiness
    expected_policy_version: ShortCode
    approval_grants: tuple[ApprovalGrant, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    supervisor_plan_id: str | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: str | None = None
    skill_version: str | None = None


class SequenceWindow(CampaignContract):
    policy_version: Literal["sequence-window-policy-v1"] = SEQUENCE_WINDOW_POLICY_VERSION
    send_window_policy_version: Literal["send-window-policy-v1"] = SEND_WINDOW_POLICY_VERSION
    timezone: Literal["Europe/Zurich", "Europe/Paris"]
    step_1_execution_date: dt.date
    step_1_authorization_deadline: dt.datetime
    step_2_execution_date: dt.date
    step_2_authorization_deadline: dt.datetime

    _deadlines = field_validator(
        "step_1_authorization_deadline", "step_2_authorization_deadline"
    )(_aware)


class CampaignFactoryInput(CampaignContract):
    wedge: ShortCode
    wedge_version: ShortCode
    jurisdiction: Literal["CH", "FR"]
    country: Literal["CH", "FR"]
    language: Literal["fr", "en"]
    selected_need_category: ShortCode
    selected_need_version: ShortCode
    personalization_catalog_version: ShortCode
    personalization_template_version: ShortCode
    language_policy_version: ShortCode
    envelope_catalog_version: ShortCode
    sender_profile_ref: StableRef
    mailbox_pool_version: ShortCode
    compliance_ruleset_fingerprint: Fingerprint
    step_1_execution_date: dt.date


class CampaignPlan(CampaignContract):
    factory_version: Literal["campaign-factory-v1"] = CAMPAIGN_FACTORY_VERSION
    campaign_group_key: Fingerprint
    campaign_ref: Fingerprint
    plan_fingerprint: Fingerprint
    batch_generation: int = Field(ge=1)
    provider_campaign_name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
    country: Literal["CH", "FR"]
    jurisdiction: Literal["CH", "FR"]
    language: Literal["fr", "en"]
    wedge: ShortCode
    selected_need_category: ShortCode
    sender_profile_ref: StableRef
    compliance_ruleset_fingerprint: Fingerprint
    batch_policy_version: Literal["batch-seal-policy-v1"] = BATCH_SEAL_POLICY_VERSION
    sequence_policy_version: Literal["campaign-sequence-policy-v1"] = CAMPAIGN_SEQUENCE_POLICY_VERSION
    send_window_policy_version: Literal["send-window-policy-v1"] = SEND_WINDOW_POLICY_VERSION
    sequence_window_policy_version: Literal["sequence-window-policy-v1"] = SEQUENCE_WINDOW_POLICY_VERSION
    tracking_policy_version: Literal["tracking-policy-v1"] = TRACKING_POLICY_VERSION
    pacing_policy_version: Literal["pacing-policy-v1"] = PACING_POLICY_VERSION
    sequence_window: SequenceWindow


class CampaignMemberReservation(CampaignContract):
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    personalization_artifact_id: StableRef
    personalization_artifact_fingerprint: Fingerprint
    compliance_assessment_id: StableRef
    compliance_assessment_fingerprint: Fingerprint
    policy_evaluation_id: StableRef
    policy_provenance: dict[str, object]
    input_fingerprint: Fingerprint
    contact_provider_identity_binding: Fingerprint
    envelope_fingerprint: Fingerprint
    policy_action_fingerprint: Fingerprint
    ruleset_fingerprint: Fingerprint
    sender_config_fingerprint: Fingerprint
    mailbox_ref: StableRef
    mailbox_readiness_fingerprint: Fingerprint
    sequence_authorization_fingerprint: Fingerprint


class CampaignReservationResult(CampaignContract):
    campaign_ref: Fingerprint
    member_ref: Fingerprint
    batch_generation: int = Field(ge=1)
    replayed: bool = False


class ProviderOperationRecord(CampaignContract):
    operation_ref: Fingerprint
    operation_key: Fingerprint
    kind: ProviderOperationKind
    state: ProviderOperationState
    campaign_ref: Fingerprint
    member_ref: Fingerprint | None = None
    desired_request_fingerprint: Fingerprint
    attempt: int = Field(ge=0)
    lease_owner: StableRef | None = None
    lease_expires_at: dt.datetime | None = None

    _lease = field_validator("lease_expires_at")(_aware)


class CampaignError(RuntimeError):
    """Base class for typed campaign-domain failures."""


class CampaignIdempotencyConflict(CampaignError):
    pass


class CampaignConcurrencyConflict(CampaignError):
    pass


class CampaignInputChanged(CampaignError):
    pass


class SequenceTimingInvariantViolation(CampaignError):
    pass


class CampaignNotActionable(CampaignError):
    pass


class CampaignDeploymentBlocked(CampaignError):
    pass


class CampaignPacingExceeded(CampaignError):
    pass


class CampaignBindingConflict(CampaignError):
    pass


class CampaignEvaluationRequiresFreshAttempt(CampaignError):
    pass
