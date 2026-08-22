"""Authenticated, deduplicated, PII-minimized Instantly transport ingress."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator

from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import (
    PROVIDER_EVENT_FINGERPRINT_VERSION,
    ProviderOperationKind,
    ResponseIngressCapability,
    SequenceTimingInvariantViolation,
)
from signals.campaigns.factory import materialize_step_2_timing, sequence_timing_fingerprint
from signals.campaigns.store import CampaignStore
from signals.campaigns.worker import classify_email_sent
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    SuppressionIdentityKeyring,
    SuppressionIdentityUnavailable,
    normalize_business_email,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_provider_event,
)


class ProviderEventType(StrEnum):
    EMAIL_SENT = "email_sent"
    EMAIL_BOUNCED = "email_bounced"
    EMAIL_OPENED = "email_opened"
    EMAIL_LINK_CLICKED = "email_link_clicked"
    LINK_CLICKED = "link_clicked"
    REPLY_RECEIVED = "reply_received"
    LEAD_UNSUBSCRIBED = "lead_unsubscribed"
    CAMPAIGN_COMPLETED = "campaign_completed"
    EMAIL_ACCOUNT_ERROR = "email_account_error"


class WebhookSubscriptionInvalid(ValueError):
    pass


class WebhookBindingError(ValueError):
    pass


def validate_webhook_subscription(
    event_types: tuple[str, ...], *, response_ingress_capability: ResponseIngressCapability
) -> None:
    unknown = set(event_types) - {item.value for item in ProviderEventType}
    if unknown:
        raise WebhookSubscriptionInvalid(f"unknown Instantly webhook events: {sorted(unknown)}")
    if (
        response_ingress_capability is ResponseIngressCapability.NONE
        and ProviderEventType.REPLY_RECEIVED.value in event_types
    ):
        raise WebhookSubscriptionInvalid(
            "reply_received requires response_ingress_capability SPEC027_V1"
        )


@dataclass(frozen=True)
class WebhookFingerprintKeyring:
    current_key_version: str
    keys: dict[str, bytes]

    def __post_init__(self) -> None:
        if self.current_key_version not in self.keys or not self.keys[self.current_key_version]:
            raise ValueError("current webhook fingerprint key must be available")
        if len(self.keys) > 8:
            raise ValueError("webhook fingerprint keyring is too large")


class InstantlyWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_type: ProviderEventType
    timestamp: dt.datetime
    workspace_id: str = Field(min_length=1, max_length=128)
    campaign_id: str = Field(min_length=1, max_length=128)
    lead_id: str | None = Field(default=None, min_length=1, max_length=128)
    email_id: str | None = Field(default=None, min_length=1, max_length=128)
    step: int | None = Field(default=None, ge=1, le=2)
    variant: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=64)
    email_account: str | None = Field(default=None, max_length=320)
    lead_email: str | None = Field(default=None, max_length=320)
    reply_subject: str | None = Field(default=None, max_length=998)
    reply_text_snippet: str | None = Field(default=None, max_length=4096)
    reply_text: str | None = Field(default=None, max_length=65536)
    reply_html: str | None = Field(default=None, max_length=65536)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("webhook timestamp must be timezone-aware")
        return value


@dataclass(frozen=True)
class WebhookIngestResult:
    event_fingerprint: str
    replayed: bool
    incident_code: str | None = None


class InstantlyWebhookService:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        provider_workspace_ref: str,
        fingerprint_keyring: WebhookFingerprintKeyring,
        suppression_keyring: SuppressionIdentityKeyring,
        response_ingress_capability: ResponseIngressCapability,
    ) -> None:
        self._engine = engine
        self._workspace = provider_workspace_ref
        self._fingerprint_keyring = fingerprint_keyring
        self._suppression_keyring = suppression_keyring
        self._response_capability = response_ingress_capability
        self._suppressions = SuppressionStore(engine, suppression_keyring)
        self._campaigns = CampaignStore(engine)

    def ingest(
        self, raw: dict[str, object], *, received_at: dt.datetime
    ) -> WebhookIngestResult:
        payload = InstantlyWebhookPayload.model_validate(raw)
        if payload.workspace_id != self._workspace:
            raise WebhookBindingError("Instantly workspace mismatch")
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("webhook received_at must be timezone-aware")
        if abs(received_at - payload.timestamp.astimezone(dt.UTC)) > dt.timedelta(days=7):
            raise WebhookBindingError("Instantly event timestamp is outside the accepted bound")
        fingerprints = self._fingerprints(payload)
        fingerprint = fingerprints[self._fingerprint_keyring.current_key_version]
        acquisition = AcquisitionStore(self._engine, clock=lambda: received_at)
        with self._engine.begin() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.provider_campaign_id == payload.campaign_id,
                    acquisition_campaign.c.provider_workspace_ref == payload.workspace_id,
                )
            ).mappings().one_or_none()
            if campaign is None:
                raise WebhookBindingError("unknown provider campaign binding")
            member = None
            if payload.lead_id is not None:
                member = connection.execute(
                    sa.select(acquisition_campaign_member).where(
                        acquisition_campaign_member.c.campaign_ref == campaign["campaign_ref"],
                        acquisition_campaign_member.c.provider_lead_id == payload.lead_id,
                    )
                ).mappings().one_or_none()
            elif payload.lead_email is not None:
                try:
                    normalized = normalize_business_email(payload.lead_email)
                except SuppressionIdentityUnavailable as exc:
                    raise WebhookBindingError("provider lead identity is unusable") from exc
                candidates = connection.execute(
                    sa.select(acquisition_campaign_member)
                    .join(
                        acquisition_contact,
                        acquisition_contact.c.contact_ref
                        == acquisition_campaign_member.c.contact_ref,
                    )
                    .where(
                        acquisition_campaign_member.c.campaign_ref
                        == campaign["campaign_ref"],
                        sa.func.lower(sa.func.trim(acquisition_contact.c.business_email))
                        == normalized,
                    )
                ).mappings().all()
                if len(candidates) == 1:
                    member = candidates[0]
                elif len(candidates) > 1:
                    raise WebhookBindingError("provider lead identity is ambiguous")
            member_required = payload.event_type not in {
                ProviderEventType.CAMPAIGN_COMPLETED,
                ProviderEventType.EMAIL_ACCOUNT_ERROR,
            }
            if member_required and member is None:
                raise WebhookBindingError("unknown provider lead binding")
            existing_fingerprint = connection.scalar(
                sa.select(acquisition_provider_event.c.canonical_event_fingerprint).where(
                    acquisition_provider_event.c.canonical_event_fingerprint.in_(
                        tuple(fingerprints.values())
                    )
                )
            )
            if existing_fingerprint is not None:
                return WebhookIngestResult(
                    event_fingerprint=existing_fingerprint, replayed=True
                )
            inserted = self._insert_event(
                connection,
                fingerprint=fingerprint,
                fingerprint_key_version=self._fingerprint_keyring.current_key_version,
                payload=payload,
                campaign=campaign,
                member=member,
                received_at=received_at,
            )
            if not inserted:
                return WebhookIngestResult(event_fingerprint=fingerprint, replayed=True)
            incident: str | None = None
            acquisition_event_id: str | None = None
            if payload.event_type is ProviderEventType.EMAIL_SENT:
                assert member is not None
                incident, acquisition_event_id = self._email_sent(
                    connection,
                    acquisition,
                    payload,
                    campaign,
                    member,
                    fingerprint,
                    received_at,
                )
            elif payload.event_type is ProviderEventType.LEAD_UNSUBSCRIBED:
                assert member is not None
                evidence_ref = f"suppression-evidence:{fingerprint}"
                self._suppressions.record_for_contact_in_transaction(
                    connection,
                    member["contact_ref"],
                    source=SuppressionSource.UNSUBSCRIBE,
                    reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                    evidence_ref=evidence_ref,
                    received_at=payload.timestamp,
                )
                self._stop_member(
                    connection,
                    campaign,
                    member,
                    received_at,
                    "RECIPIENT_UNSUBSCRIBED",
                )
            elif payload.event_type is ProviderEventType.REPLY_RECEIVED:
                assert member is not None
                self._stop_member(
                    connection, campaign, member, received_at, "REPLY_RECEIVED"
                )
                if self._response_capability is ResponseIngressCapability.NONE:
                    incident = "UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS"
            elif payload.event_type in {
                ProviderEventType.EMAIL_BOUNCED,
                ProviderEventType.EMAIL_ACCOUNT_ERROR,
            }:
                if member is not None:
                    self._stop_member(
                        connection,
                        campaign,
                        member,
                        received_at,
                        "PROVIDER_TRANSPORT_UNSAFE",
                    )
                else:
                    self._campaigns.plan_operation_in_transaction(
                        connection,
                        ProviderOperationKind.PAUSE_CAMPAIGN,
                        campaign_ref=campaign["campaign_ref"],
                        member_ref=None,
                        desired_request_fingerprint=semantic_fingerprint(
                            {
                                "kind": "provider-account-error-stop-v1",
                                "campaign_ref": campaign["campaign_ref"],
                            }
                        ),
                        correlation_id=(
                            f"provider-account-error:{campaign['campaign_ref']}"
                        ),
                        now=received_at,
                    )
            elif payload.event_type is ProviderEventType.CAMPAIGN_COMPLETED:
                connection.execute(
                    sa.update(acquisition_campaign)
                    .where(
                        acquisition_campaign.c.campaign_ref == campaign["campaign_ref"]
                    )
                    .values(lifecycle="COMPLETED", updated_at=received_at)
                )
            connection.execute(
                sa.update(acquisition_provider_event)
                .where(
                    acquisition_provider_event.c.canonical_event_fingerprint == fingerprint
                )
                .values(
                    resolution_state="PROCESSED",
                    incident_code=incident,
                    recorded_acquisition_event_id=acquisition_event_id,
                )
            )
            return WebhookIngestResult(
                event_fingerprint=fingerprint,
                replayed=False,
                incident_code=incident,
            )

    def _fingerprints(self, payload: InstantlyWebhookPayload) -> dict[str, str]:
        stable: dict[str, object] = {
            "version": PROVIDER_EVENT_FINGERPRINT_VERSION,
            "event_type": payload.event_type.value,
            "workspace_id": payload.workspace_id,
            "campaign_id": payload.campaign_id,
            "lead_id": payload.lead_id,
            "email_id": payload.email_id,
            "step": payload.step,
            "variant": payload.variant,
            "timestamp": payload.timestamp.astimezone(dt.UTC).isoformat(),
            "status": payload.status,
        }
        if payload.email_id is None:
            stable["transient_event_differentiator"] = {
                "reply_subject": payload.reply_subject,
                "reply_text_snippet": payload.reply_text_snippet,
                "reply_text": payload.reply_text,
                "reply_html": payload.reply_html,
            }
        encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
        return {
            version: hmac.new(
                key,
                b"kivou:instantly-provider-event:v1\0" + encoded,
                hashlib.sha256,
            ).hexdigest()
            for version, key in sorted(self._fingerprint_keyring.keys.items())
        }

    @staticmethod
    def _insert_event(
        connection,
        *,
        fingerprint,
        fingerprint_key_version,
        payload,
        campaign,
        member,
        received_at,
    ) -> bool:
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported provider event persistence dialect")
        result = connection.execute(
            insert(acquisition_provider_event)
            .values(
                provider_event_ref=semantic_fingerprint(
                    {"kind": "provider-event-ref-v1", "fingerprint": fingerprint}
                ),
                canonical_event_fingerprint=fingerprint,
                fingerprint_version=PROVIDER_EVENT_FINGERPRINT_VERSION,
                fingerprint_key_version=fingerprint_key_version,
                provider_event_type=payload.event_type.value,
                provider_workspace_ref=payload.workspace_id,
                provider_campaign_id=payload.campaign_id,
                provider_lead_id=payload.lead_id,
                provider_email_event_id=payload.email_id,
                campaign_ref=campaign["campaign_ref"],
                member_ref=member["member_ref"] if member else None,
                acquisition_opportunity_id=(
                    member["acquisition_opportunity_id"] if member else None
                ),
                contact_ref=member["contact_ref"] if member else None,
                step=payload.step,
                variant=payload.variant,
                occurred_at=payload.timestamp,
                received_at=received_at,
                mailbox_ref=member["mailbox_ref"] if member else None,
                transport_status=payload.status,
                resolution_state="ACCEPTED",
            )
            .on_conflict_do_nothing(
                index_elements=[acquisition_provider_event.c.canonical_event_fingerprint]
            )
        )
        return result.rowcount == 1

    def _email_sent(
        self,
        connection,
        acquisition,
        payload,
        campaign,
        member,
        fingerprint,
        received_at,
    ) -> tuple[str | None, str | None]:
        if payload.step == 1:
            if member["step_1_sent_at"] is not None:
                recorded = member["step_1_sent_at"]
                if recorded.tzinfo is None:
                    recorded = recorded.replace(tzinfo=dt.UTC)
                if recorded == payload.timestamp:
                    return None, member["sent_event_id"]
                incident = "CONFLICTING_STEP1_TRANSPORT_TRUTH"
                connection.execute(
                    sa.update(acquisition_campaign_member)
                    .where(
                        acquisition_campaign_member.c.member_ref == member["member_ref"]
                    )
                    .values(
                        sequence_state="STOPPED",
                        incident_code=incident,
                        updated_at=received_at,
                    )
                )
                return incident, member["sent_event_id"]
            deadline = campaign["step_1_authorization_deadline"]
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=dt.UTC)
            start = dt.datetime.combine(
                campaign["step_1_execution_date"],
                dt.time(9),
                ZoneInfo(campaign["timezone"]),
            ).astimezone(dt.UTC)
            prior_state_incident = None
            if member["execution_state"] in {"STOPPED", "FAILED"}:
                prior_state_incident = "UNEXPECTED_EMAIL_SENT_AFTER_STOP"
            elif member["execution_state"] != "QUEUED":
                prior_state_incident = "STEP1_SENT_WITHOUT_QUEUE_AUTHORIZATION"
            if prior_state_incident is None:
                _, incident = classify_email_sent(
                    step=1,
                    occurred_at=payload.timestamp,
                    due_at=start,
                    deadline=deadline,
                )
            else:
                incident = prior_state_incident
            timing: dict[str, object] = {}
            sequence_state = "STOPPED" if incident else "WAITING_STEP2"
            if not incident:
                from signals.campaigns.contracts import SequenceWindow

                window = SequenceWindow(
                    timezone=campaign["timezone"],
                    step_1_execution_date=campaign["step_1_execution_date"],
                    step_1_authorization_deadline=deadline,
                    step_2_execution_date=campaign["step_2_execution_date"],
                    step_2_authorization_deadline=(
                        campaign["step_2_authorization_deadline"].replace(tzinfo=dt.UTC)
                        if campaign["step_2_authorization_deadline"].tzinfo is None
                        else campaign["step_2_authorization_deadline"]
                    ),
                )
                try:
                    due = materialize_step_2_timing(window, payload.timestamp)
                except SequenceTimingInvariantViolation:
                    incident = "SEQUENCE_TIMING_INVARIANT_VIOLATION"
                    sequence_state = "STOPPED"
                else:
                    timing = {
                        "step_1_sent_at": payload.timestamp,
                        "step_2_due_at": due.astimezone(dt.UTC),
                        "sequence_timing_fingerprint": sequence_timing_fingerprint(
                            sequence_authorization_fingerprint=member[
                                "sequence_authorization_fingerprint"
                            ],
                            step_1_sent_at=payload.timestamp,
                            step_2_due_at=due,
                            step_2_authorization_deadline=window.step_2_authorization_deadline,
                        ),
                    }
            current = acquisition.get_opportunity_in_transaction(
                connection, member["acquisition_opportunity_id"], for_update=True
            )
            event_id = None
            if current.state is AcquisitionState.QUEUED:
                mutation = acquisition.append_in_transaction(
                    connection,
                    current.acquisition_opportunity_id,
                    event_type=EventType.STATE_TRANSITIONED,
                    expected_version=current.stream_version,
                    idempotency_key=f"instantly_email_sent_step1:{fingerprint}",
                    payload={"target_state": "SENT"},
                    actor_type=ActorType.EXTERNAL,
                    actor_ref="instantly",
                    reason_codes=("INSTANTLY_EMAIL_SENT",),
                    evidence_refs=(f"provider-event:{fingerprint}",),
                    occurred_at=payload.timestamp,
                )
                event_id = mutation.event.event_id
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member["member_ref"])
                .values(
                    execution_state="SENT",
                    sequence_state=sequence_state,
                    incident_code=incident,
                    sent_event_id=event_id,
                    step_1_provider_event_ref=semantic_fingerprint(
                        {"kind": "provider-event-ref-v1", "fingerprint": fingerprint}
                    ),
                    updated_at=received_at,
                    **timing,
                )
            )
            pending_step_1 = connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.campaign_ref
                    == campaign["campaign_ref"],
                    acquisition_campaign_member.c.sequence_state == "PENDING_STEP1",
                )
            )
            if int(pending_step_1 or 0) == 0:
                self._campaigns.plan_operation_in_transaction(
                    connection,
                    ProviderOperationKind.PAUSE_CAMPAIGN,
                    campaign_ref=campaign["campaign_ref"],
                    member_ref=None,
                    desired_request_fingerprint=semantic_fingerprint(
                        {
                            "kind": "step2-live-safety-hold-v1",
                            "campaign_ref": campaign["campaign_ref"],
                            "step_2_execution_date": campaign[
                                "step_2_execution_date"
                            ],
                        }
                    ),
                    correlation_id=f"step2-safety-hold:{campaign['campaign_ref']}",
                    now=received_at,
                )
            return incident, event_id
        if payload.step == 2:
            due = member["step_2_due_at"]
            deadline = member["step_2_authorization_deadline"]
            if due is not None and due.tzinfo is None:
                due = due.replace(tzinfo=dt.UTC)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=dt.UTC)
            _, incident = classify_email_sent(
                step=2,
                occurred_at=payload.timestamp,
                due_at=due,
                deadline=deadline,
            )
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member["member_ref"])
                .values(
                    sequence_state="COMPLETED",
                    incident_code=incident,
                    step_2_provider_event_ref=semantic_fingerprint(
                        {"kind": "provider-event-ref-v1", "fingerprint": fingerprint}
                    ),
                    updated_at=received_at,
                )
            )
            return incident, None
        return "PROVIDER_STEP_UNRESOLVED", None

    def _stop_member(self, connection, campaign, member, now, reason: str) -> None:
        execution_state = "SENT" if member["execution_state"] == "SENT" else "STOPPED"
        connection.execute(
            sa.update(acquisition_campaign_member)
            .where(acquisition_campaign_member.c.member_ref == member["member_ref"])
            .values(
                execution_state=execution_state,
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
                desired_request_fingerprint=(
                    member["provider_binding_fingerprint"]
                    or member["sequence_authorization_fingerprint"]
                ),
                correlation_id=f"transport-stop:{reason}:{member['member_ref']}",
                now=now,
            )
        self._campaigns.plan_operation_in_transaction(
            connection,
            ProviderOperationKind.PAUSE_CAMPAIGN,
            campaign_ref=campaign["campaign_ref"],
            member_ref=None,
            desired_request_fingerprint=semantic_fingerprint(
                {
                    "kind": "transport-hard-stop-v1",
                    "campaign_ref": campaign["campaign_ref"],
                    "reason": reason,
                }
            ),
            correlation_id=f"transport-stop:{reason}:{campaign['campaign_ref']}",
            now=now,
        )
