"""Response Intelligence orchestration primitives.

The first boundary implemented here is the fail-closed, read-only Instantly
Email resolution policy.  Business finalization is layered on top of this
primitive; the resolver itself has no persistence or clock access.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal
from enum import StrEnum
from typing import Literal

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator

from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.instantly import InstantlyErrorCode, InstantlyProviderError
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.schema import acquisition_response_evaluation
from signals.responses.classifier import derive_business_disposition
from signals.responses.contracts import (
    RESPONSE_SAFETY_VERSION,
    ContentFingerprintKeyring,
    ResponseClassification,
    ResponseClassifierOutput,
    ResponseFinalization,
    ResponseInputSource,
    ResponseReasonCode,
    ResponseReservation,
    content_fingerprint,
    response_evaluation_id,
    response_ref,
)
from signals.responses.instantly_email import (
    InstantlyEmail,
    InstantlyEmailReader,
    ListEmailsQuery,
)
from signals.responses.normalization import (
    ResponseContentUnavailable,
    normalize_response_content,
)
from signals.responses.safety import evaluate_response_safety
from signals.responses.store import ResponseStore


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("response event time must be timezone-aware")
    return value


def _address(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().casefold()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EmailResolutionContext(_FrozenModel):
    provider_workspace_ref: str = Field(min_length=1, max_length=128)
    provider_campaign_id: str = Field(min_length=1, max_length=128)
    provider_lead_id: str | None = Field(default=None, max_length=128)
    lead_email_transient: str = Field(min_length=3, max_length=320, repr=False)
    email_account_transient: str | None = Field(default=None, max_length=320, repr=False)
    provider_event_type: Literal["reply_received", "auto_reply_received"]
    provider_event_timestamp: dt.datetime
    # Instantly documents this webhook value as reply_to_uuid.  It is retained
    # only as bounded transport context and is never used for Email GET.
    webhook_email_id_transport_only: str | None = Field(
        default=None, max_length=256, repr=False
    )

    _timestamp = field_validator("provider_event_timestamp")(_aware)


class EmailResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    RETRYABLE = "RETRYABLE"
    UNAVAILABLE = "UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


class EmailResolutionResult(_FrozenModel):
    status: EmailResolutionStatus
    email: InstantlyEmail | None = Field(default=None, repr=False)
    source_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    source_fingerprint_key_version: str | None = Field(default=None, max_length=100)
    reason_code: ResponseReasonCode | None = None
    review_required: bool = False
    retry_at: dt.datetime | None = None

    _retry = field_validator("retry_at")(_aware)


class EmailResponseResolver:
    """Resolve one exact inbound Email without guessing from similarity or proximity."""

    def __init__(
        self,
        reader: InstantlyEmailReader,
        *,
        source_keyring: ContentFingerprintKeyring,
    ) -> None:
        self._reader = reader
        self._source_keyring = source_keyring

    @staticmethod
    def _matches(email: InstantlyEmail, context: EmailResolutionContext) -> bool:
        if email.organization_id != context.provider_workspace_ref:
            return False
        if email.campaign_id != context.provider_campaign_id:
            return False
        if context.provider_lead_id is not None and email.lead_id != context.provider_lead_id:
            return False
        recipient = _address(context.lead_email_transient)
        if _address(email.lead) != recipient:
            return False
        account = _address(context.email_account_transient)
        if account is not None and _address(email.eaccount) != account:
            return False
        lower = context.provider_event_timestamp - dt.timedelta(minutes=5)
        upper = context.provider_event_timestamp + dt.timedelta(minutes=15)
        if not (lower <= email.timestamp_created <= upper):
            return False
        expected_auto = context.provider_event_type == "auto_reply_received"
        return bool(email.is_auto_reply) is expected_auto

    def _source_fingerprint(
        self, *, context: EmailResolutionContext, email: InstantlyEmail
    ) -> tuple[str, str]:
        version = self._source_keyring.current_key_version
        canonical = json.dumps(
            {
                "campaign_id": context.provider_campaign_id,
                "email_id": email.id,
                "event_type": context.provider_event_type,
                "lead_id": email.lead_id,
                "message_id": email.message_id,
                "thread_id": email.thread_id,
                "timestamp_created": email.timestamp_created.astimezone(dt.UTC).isoformat(),
                "workspace": context.provider_workspace_ref,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hmac.new(
            self._source_keyring.keys[version],
            b"kivou:response-source-fingerprint:v1\0" + canonical,
            hashlib.sha256,
        ).hexdigest()
        return fingerprint, version

    @staticmethod
    def _ambiguous() -> EmailResolutionResult:
        return EmailResolutionResult(
            status=EmailResolutionStatus.AMBIGUOUS,
            reason_code=ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS,
            review_required=True,
        )

    def resolve(
        self,
        context: EmailResolutionContext,
        *,
        attempt: int,
        now: dt.datetime,
    ) -> EmailResolutionResult:
        _aware(now)
        if attempt < 1 or attempt > 3:
            raise ValueError("Email resolution attempt must be between 1 and 3")
        query = ListEmailsQuery(
            campaign_id=context.provider_campaign_id,
            lead=context.lead_email_transient,
            eaccount=context.email_account_transient,
            min_timestamp_created=context.provider_event_timestamp
            - dt.timedelta(minutes=5),
            max_timestamp_created=context.provider_event_timestamp
            + dt.timedelta(minutes=15),
            limit=100,
        )
        try:
            page = self._reader.list_emails(query)
        except InstantlyProviderError as exc:
            if exc.code is InstantlyErrorCode.RATE_LIMITED:
                return EmailResolutionResult(
                    status=EmailResolutionStatus.RETRYABLE,
                    reason_code=ResponseReasonCode.PROVIDER_RATE_LIMITED,
                    retry_at=now
                    + dt.timedelta(seconds=max(1, exc.retry_after_seconds or 60)),
                )
            return EmailResolutionResult(
                status=EmailResolutionStatus.RETRYABLE,
                reason_code=ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
                retry_at=now + dt.timedelta(minutes=5),
            )

        matches = tuple(item for item in page.items if self._matches(item, context))
        if not page.items:
            resolution_expires_at = context.provider_event_timestamp + dt.timedelta(minutes=15)
            if attempt < 3 and now < resolution_expires_at:
                return EmailResolutionResult(
                    status=EmailResolutionStatus.RETRYABLE,
                    reason_code=ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
                    retry_at=min(now + dt.timedelta(minutes=5), resolution_expires_at),
                )
            return EmailResolutionResult(
                status=EmailResolutionStatus.UNAVAILABLE,
                reason_code=ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
                review_required=True,
            )
        if len(matches) != 1:
            return self._ambiguous()

        try:
            full = self._reader.get_email(matches[0].id)
        except InstantlyProviderError as exc:
            if exc.code is InstantlyErrorCode.RATE_LIMITED:
                retry_seconds = max(1, exc.retry_after_seconds or 60)
            else:
                retry_seconds = 300
            return EmailResolutionResult(
                status=EmailResolutionStatus.RETRYABLE,
                reason_code=(
                    ResponseReasonCode.PROVIDER_RATE_LIMITED
                    if exc.code is InstantlyErrorCode.RATE_LIMITED
                    else ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE
                ),
                retry_at=now + dt.timedelta(seconds=retry_seconds),
            )
        if not self._matches(full, context) or full.id != matches[0].id:
            return self._ambiguous()
        fingerprint, key_version = self._source_fingerprint(context=context, email=full)
        return EmailResolutionResult(
            status=EmailResolutionStatus.RESOLVED,
            email=full,
            source_fingerprint=fingerprint,
            source_fingerprint_key_version=key_version,
        )


class ResponseWebhookIngress:
    """Transaction-scoped SPEC-027 reservation and deterministic safety handoff."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        suppression_keyring: SuppressionIdentityKeyring,
        source_keyring: ContentFingerprintKeyring,
        content_keyring: ContentFingerprintKeyring,
        classifier_version: str,
        estimated_classifier_cost: Decimal | str,
    ) -> None:
        if not classifier_version or len(classifier_version) > 100:
            raise ValueError("bounded classifier_version is required")
        estimated = Decimal(estimated_classifier_cost)
        if not estimated.is_finite() or estimated < 0 or estimated > Decimal("1000"):
            raise ValueError("bounded estimated classifier cost is required")
        self._engine = engine
        self._suppressions = SuppressionStore(engine, suppression_keyring)
        self._source_keyring = source_keyring
        self._content_keyring = content_keyring
        self._classifier_version = classifier_version
        self._estimated_cost = estimated

    def _source_fingerprint(self, provider_event_ref: str, response: str) -> str:
        version = self._source_keyring.current_key_version
        canonical = json.dumps(
            {
                "provider_event_ref": provider_event_ref,
                "response_ref": response,
                "version": "response-webhook-source-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(
            self._source_keyring.keys[version],
            b"kivou:response-webhook-source:v1\0" + canonical,
            hashlib.sha256,
        ).hexdigest()

    def reserve_in_transaction(
        self,
        connection,
        *,
        provider_event_ref: str,
        campaign,
        member,
        payload,
        received_at: dt.datetime,
    ) -> str:
        """Reserve exactly once; raw payload fields never enter stored values."""

        response = response_ref(
            provider_event_ref=provider_event_ref,
            campaign_ref=campaign["campaign_ref"],
            member_ref=member["member_ref"],
        )
        source = self._source_fingerprint(provider_event_ref, response)
        normalized = None
        try:
            normalized = normalize_response_content(
                subject=payload.reply_subject_transient,
                body_text=(
                    payload.reply_text_transient
                    or payload.reply_text_snippet_transient
                ),
                body_html=payload.reply_html_transient,
            )
        except ResponseContentUnavailable:
            pass
        safety = evaluate_response_safety(
            event_type=payload.event_type_transport_only,
            language=campaign["language"],
            subject=normalized.subject if normalized is not None else "",
            current_response=(
                normalized.current_response if normalized is not None else ""
            ),
            provider_auto_reply=(
                True
                if payload.event_type_transport_only == "auto_reply_received"
                else None
            ),
        )
        classifier_version = (
            RESPONSE_SAFETY_VERSION if safety.final else self._classifier_version
        )
        evaluation_id = response_evaluation_id(response, classifier_version)
        reservation = ResponseReservation(
            response_evaluation_id=evaluation_id,
            response_ref=response,
            provider_event_ref=provider_event_ref,
            campaign_ref=campaign["campaign_ref"],
            member_ref=member["member_ref"],
            acquisition_opportunity_id=member["acquisition_opportunity_id"],
            contact_ref=member["contact_ref"],
            input_source=ResponseInputSource.WEBHOOK_V2,
            source_fingerprint=source,
            classifier_version=classifier_version,
            estimated_cost=(Decimal("0") if safety.final else self._estimated_cost),
            received_at=received_at,
            created_at=received_at,
        )
        reserved = ResponseStore.reserve_in_transaction(connection, reservation)
        if reserved.row["processing_state"] == "FINALIZED" or not safety.final:
            return response

        assert safety.classification is not None
        disposition = derive_business_disposition(
            ResponseClassifierOutput(
                classification=safety.classification,
                confidence=Decimal("1"),
                reason_codes=safety.reason_codes,
                hot_lead=False,
                review_required=safety.review_required,
                classifier_version=RESPONSE_SAFETY_VERSION,
                language=campaign["language"],
                human_response_confirmed=safety.human_response_confirmed,
            )
        )
        suppression_ref = self._required_suppression(
            connection,
            classification=safety.classification,
            contact_ref=member["contact_ref"],
            response_ref_value=response,
            received_at=received_at,
        )
        outcome_event_ref, next_action_event_ref = self._write_acquisition_effects(
            connection,
            opportunity_id=member["acquisition_opportunity_id"],
            evaluation_id=evaluation_id,
            provider_event_ref=provider_event_ref,
            classification=safety.classification,
            reason_codes=safety.reason_codes,
            human_response_confirmed=disposition.record_replied,
            next_action=disposition.next_action,
            received_at=received_at,
        )
        fingerprint = (
            content_fingerprint(
                subject=normalized.subject,
                current_response=normalized.current_response,
                keyring=self._content_keyring,
            )
            if normalized is not None
            else None
        )
        connection.execute(
            sa.update(acquisition_response_evaluation)
            .where(
                acquisition_response_evaluation.c.response_evaluation_id
                == evaluation_id,
                acquisition_response_evaluation.c.processing_state == "PLANNED",
            )
            .values(
                processing_state="IN_FLIGHT",
                attempt=1,
                lease_owner="webhook-safety",
                lease_expires_at=received_at + dt.timedelta(minutes=1),
                updated_at=received_at,
            )
        )
        ResponseStore.finalize_in_transaction(
            connection,
            evaluation_id,
            worker_ref="webhook-safety",
            value=ResponseFinalization(
                input_source=ResponseInputSource.WEBHOOK_V2,
                source_fingerprint=source,
                content_fingerprint=(fingerprint.fingerprint if fingerprint else None),
                content_fingerprint_version=(fingerprint.version if fingerprint else None),
                content_fingerprint_key_version=(
                    fingerprint.key_version if fingerprint else None
                ),
                classification=safety.classification,
                confidence=Decimal("1"),
                reason_codes=safety.reason_codes,
                human_response_confirmed=safety.human_response_confirmed,
                hot_lead=False,
                review_required=disposition.review_required,
                next_action=disposition.next_action,
                actual_cost=Decimal("0"),
                input_tokens=0,
                output_tokens=0,
                disposition="DETERMINISTIC_SAFETY",
                outcome_event_ref=outcome_event_ref,
                next_action_event_ref=next_action_event_ref,
                suppression_ref=suppression_ref,
                evaluated_at=received_at,
                finalized_at=received_at,
            ),
        )
        return response

    def _required_suppression(
        self,
        connection,
        *,
        classification: ResponseClassification,
        contact_ref: str,
        response_ref_value: str,
        received_at: dt.datetime,
    ) -> str | None:
        if classification is ResponseClassification.UNSUBSCRIBE:
            source = SuppressionSource.UNSUBSCRIBE
            reason = SuppressionReasonCode.UNSUBSCRIBED
        elif classification is ResponseClassification.COMPLAINT:
            source = SuppressionSource.RECIPIENT_OBJECTION
            reason = SuppressionReasonCode.RECIPIENT_OBJECTED
        else:
            return None
        row = self._suppressions.record_for_contact_in_transaction(
            connection,
            contact_ref,
            source=source,
            reason_code=reason,
            evidence_ref=f"suppression-evidence:{response_ref_value}",
            received_at=received_at,
        )
        return row["suppression_id"]

    def _write_acquisition_effects(
        self,
        connection,
        *,
        opportunity_id: str,
        evaluation_id: str,
        provider_event_ref: str,
        classification: ResponseClassification,
        reason_codes: tuple[ResponseReasonCode, ...],
        human_response_confirmed: bool,
        next_action: str | None,
        received_at: dt.datetime,
    ) -> tuple[str | None, str]:
        acquisition = AcquisitionStore(self._engine, clock=lambda: received_at)
        current = acquisition.get_opportunity_in_transaction(
            connection, opportunity_id, for_update=True
        )
        evidence_refs = (
            f"response-evaluation:{evaluation_id}",
            f"provider-event:{provider_event_ref}",
        )
        outcome_event_ref = None
        if human_response_confirmed:
            outcome = acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.OUTCOME_RECORDED,
                expected_version=current.stream_version,
                idempotency_key=f"response_outcome:{evaluation_id}",
                payload={"outcome_state": AcquisitionState.REPLIED.value},
                actor_type=ActorType.EXTERNAL,
                actor_ref="instantly-response",
                reason_codes=tuple(item.value for item in reason_codes),
                evidence_refs=evidence_refs,
                occurred_at=received_at,
            )
            current = outcome.projection
            outcome_event_ref = outcome.event.event_id
        action = acquisition.append_in_transaction(
            connection,
            opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=current.stream_version,
            idempotency_key=f"response_next_action:{evaluation_id}",
            payload={"next_action": next_action},
            actor_type=ActorType.SYSTEM,
            actor_ref="kivou-response-intelligence",
            reason_codes=(f"RESPONSE_{classification.value}",),
            evidence_refs=evidence_refs,
            occurred_at=received_at,
        )
        return outcome_event_ref, action.event.event_id


__all__ = [
    "EmailResolutionContext",
    "EmailResolutionResult",
    "EmailResolutionStatus",
    "EmailResponseResolver",
    "ResponseWebhookIngress",
]
