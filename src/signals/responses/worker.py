"""Explicit, non-autostarting Response Intelligence worker saga."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field

from signals.acquisition.contracts import AcquisitionState, ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_provider_event,
)
from signals.responses.classifier import (
    ResponseClassifier,
    ResponseClassifierUnavailable,
    derive_business_disposition,
)
from signals.responses.contracts import (
    ContentFingerprintKeyring,
    ResponseClassification,
    ResponseClassifierInput,
    ResponseClassifierOutput,
    ResponseFinalization,
    ResponseInputSource,
    ResponseReasonCode,
    content_fingerprint,
)
from signals.responses.normalization import (
    ResponseContentUnavailable,
    normalize_response_content,
)
from signals.responses.safety import evaluate_response_safety
from signals.responses.service import (
    EmailResolutionContext,
    EmailResolutionStatus,
    EmailResponseResolver,
)
from signals.responses.store import ResponseEvaluationConflict, ResponseStore


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ResponsePolicyFacts(_FrozenModel):
    response_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_event_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_event_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_workspace_ref: str = Field(min_length=1, max_length=128)
    campaign_ref: str = Field(min_length=1, max_length=64)
    member_ref: str = Field(min_length=1, max_length=64)
    acquisition_opportunity_id: str = Field(min_length=1, max_length=64)
    contact_ref: str = Field(min_length=1, max_length=64)
    provider_email_id: str = Field(min_length=1, max_length=128)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_fingerprint_version: str = Field(min_length=1, max_length=64)
    content_fingerprint_key_version: str = Field(min_length=1, max_length=100)
    resolver_version: str = Field(min_length=1, max_length=64)
    normalizer_version: str = Field(min_length=1, max_length=64)
    safety_version: str = Field(min_length=1, max_length=64)
    taxonomy_version: str = Field(min_length=1, max_length=64)
    classifier_version: str = Field(min_length=1, max_length=100)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    wedge: str = Field(min_length=1, max_length=100)
    language: str = Field(pattern=r"^(fr|en)$")
    human_response_confirmed: bool
    provider_auto_reply: bool
    observed_at: dt.datetime
    max_proposed_cost: Decimal = Field(ge=0, le=Decimal("1000"))


@dataclass(frozen=True)
class ResponsePolicyAuthorization:
    allowed: bool
    policy_evaluation_id: str
    policy_action_fingerprint: str
    policy_status: str


class ResponsePolicyAuthorizer(Protocol):
    def authorize(
        self, facts: ResponsePolicyFacts, *, now: dt.datetime
    ) -> ResponsePolicyAuthorization: ...


class ResponseWorkerStatus(StrEnum):
    FINALIZED = "FINALIZED"
    RETRY_WAIT = "RETRY_WAIT"
    REPLAYED = "REPLAYED"
    NOT_CLAIMED = "NOT_CLAIMED"


@dataclass(frozen=True)
class ResponseWorkerResult:
    status: ResponseWorkerStatus
    row: object


class ResponseWorker:
    """Run one bounded response evaluation; it is never started by imports or ASGI."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        resolver: EmailResponseResolver,
        classifier: ResponseClassifier,
        policy_authorizer: ResponsePolicyAuthorizer,
        content_keyring: ContentFingerprintKeyring,
        suppression_keyring: SuppressionIdentityKeyring,
        mailbox_accounts: Mapping[str, str],
        prompt_version: str | None = None,
        model_version: str | None = None,
    ) -> None:
        self._engine = engine
        self._store = ResponseStore(engine)
        self._resolver = resolver
        self._classifier = classifier
        self._policy = policy_authorizer
        self._content_keys = content_keyring
        self._suppressions = SuppressionStore(engine, suppression_keyring)
        self._mailbox_accounts = dict(mailbox_accounts)
        self._prompt_version = prompt_version
        self._model_version = model_version

    def process(
        self,
        response_evaluation_id: str,
        *,
        worker_ref: str,
        now: dt.datetime,
    ) -> ResponseWorkerResult:
        claim = self._store.claim(
            response_evaluation_id,
            worker_ref=worker_ref,
            now=now,
            lease_duration=dt.timedelta(minutes=5),
        )
        if not claim.claimed:
            status = (
                ResponseWorkerStatus.REPLAYED
                if claim.row["processing_state"] == "FINALIZED"
                else ResponseWorkerStatus.NOT_CLAIMED
            )
            return ResponseWorkerResult(status, claim.row)
        row = claim.row
        context = self._load_context(row)
        account = self._mailbox_accounts.get(context["member"]["mailbox_ref"])
        if account is None:
            return self._finalize_ambiguous(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                reason=ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
            )
        event = context["event"]
        resolution = self._resolver.resolve(
            EmailResolutionContext(
                provider_workspace_ref=event["provider_workspace_ref"],
                provider_campaign_id=event["provider_campaign_id"],
                provider_lead_id=event["provider_lead_id"],
                lead_email_transient=context["contact"]["business_email"],
                email_account_transient=account,
                provider_event_type=event["provider_event_type"],
                provider_event_timestamp=self._aware(event["occurred_at"]),
                webhook_email_id_transport_only=event["provider_email_event_id"],
            ),
            attempt=row["attempt"],
            now=now,
        )
        if resolution.status is EmailResolutionStatus.RETRYABLE:
            retried = self._store.mark_retry(
                response_evaluation_id,
                worker_ref=worker_ref,
                now=now,
                retry_at=resolution.retry_at or now + dt.timedelta(minutes=5),
                failure_code=(
                    resolution.reason_code.value
                    if resolution.reason_code
                    else "RESPONSE_CONTENT_PENDING"
                ),
            )
            return ResponseWorkerResult(ResponseWorkerStatus.RETRY_WAIT, retried)
        if resolution.status is not EmailResolutionStatus.RESOLVED:
            return self._finalize_ambiguous(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                reason=(
                    resolution.reason_code
                    or ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS
                ),
            )
        email = resolution.email
        assert email is not None and resolution.source_fingerprint is not None
        try:
            normalized = normalize_response_content(
                subject=email.subject,
                body_text=email.body.text,
                body_html=email.body.html,
            )
        except ResponseContentUnavailable:
            return self._finalize_ambiguous(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                reason=ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE,
                source_fingerprint=resolution.source_fingerprint,
                provider_email_id=email.id,
                provider_thread_id=email.thread_id,
            )
        fingerprint = content_fingerprint(
            subject=normalized.subject,
            current_response=normalized.current_response,
            keyring=self._content_keys,
        )
        safety = evaluate_response_safety(
            event_type=event["provider_event_type"],
            language=context["campaign"]["language"],
            subject=normalized.subject,
            current_response=normalized.current_response,
            provider_auto_reply=email.is_auto_reply,
        )
        if safety.final:
            assert safety.classification is not None
            output = ResponseClassifierOutput(
                classification=safety.classification,
                confidence=Decimal("1"),
                reason_codes=safety.reason_codes,
                hot_lead=False,
                review_required=safety.review_required,
                classifier_version=row["classifier_version"],
                language=context["campaign"]["language"],
                human_response_confirmed=safety.human_response_confirmed,
            )
            return self._finalize(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                output=output,
                source_fingerprint=resolution.source_fingerprint,
                content=fingerprint,
                provider_email_id=email.id,
                provider_thread_id=email.thread_id,
                policy=None,
                disposition="DETERMINISTIC_SAFETY",
            )
        facts = ResponsePolicyFacts(
            response_ref=row["response_ref"],
            provider_event_ref=event["provider_event_ref"],
            provider_event_fingerprint=event["canonical_event_fingerprint"],
            provider_workspace_ref=event["provider_workspace_ref"],
            campaign_ref=row["campaign_ref"],
            member_ref=row["member_ref"],
            acquisition_opportunity_id=row["acquisition_opportunity_id"],
            contact_ref=row["contact_ref"],
            provider_email_id=email.id,
            source_fingerprint=resolution.source_fingerprint,
            content_fingerprint=fingerprint.fingerprint,
            content_fingerprint_version=fingerprint.version,
            content_fingerprint_key_version=fingerprint.key_version,
            resolver_version=row["resolver_version"],
            normalizer_version=row["normalizer_version"],
            safety_version=row["safety_version"],
            taxonomy_version=row["taxonomy_version"],
            classifier_version=row["classifier_version"],
            country=context["campaign"]["country"],
            wedge=context["campaign"]["wedge"],
            language=context["campaign"]["language"],
            human_response_confirmed=True,
            provider_auto_reply=False,
            observed_at=self._aware(event["occurred_at"]),
            max_proposed_cost=Decimal(row["estimated_cost"]),
        )
        try:
            authorization = self._policy.authorize(facts, now=now)
        except Exception:  # noqa: BLE001 - injected Policy boundary must fail closed
            authorization = None
        if authorization is None or not authorization.allowed:
            return self._finalize_ambiguous(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                reason=ResponseReasonCode.POLICY_NOT_EXECUTABLE,
                source_fingerprint=resolution.source_fingerprint,
                content=fingerprint,
                provider_email_id=email.id,
                provider_thread_id=email.thread_id,
                policy=authorization,
                human_response_confirmed=True,
            )
        classifier_input = ResponseClassifierInput(
            response_ref=row["response_ref"],
            campaign_ref=row["campaign_ref"],
            member_ref=row["member_ref"],
            acquisition_opportunity_id=row["acquisition_opportunity_id"],
            contact_ref=row["contact_ref"],
            language=context["campaign"]["language"],
            subject_transient=normalized.subject,
            current_response_transient=normalized.current_response,
        )
        try:
            output = self._classifier.classify(classifier_input)
            if (
                output.classifier_version != row["classifier_version"]
                or output.language != context["campaign"]["language"]
                or not output.human_response_confirmed
            ):
                raise ValueError("classifier output binding mismatch")
        except (ResponseClassifierUnavailable, TimeoutError, OSError):
            classifier_failure = ResponseReasonCode.CLASSIFIER_UNAVAILABLE
        except Exception:  # noqa: BLE001 - injected model boundary must fail closed
            classifier_failure = ResponseReasonCode.CLASSIFIER_MALFORMED
        else:
            classifier_failure = None
        if classifier_failure is not None:
            return self._finalize_ambiguous(
                row,
                context,
                worker_ref=worker_ref,
                now=now,
                reason=classifier_failure,
                source_fingerprint=resolution.source_fingerprint,
                content=fingerprint,
                provider_email_id=email.id,
                provider_thread_id=email.thread_id,
                policy=authorization,
                human_response_confirmed=True,
            )
        return self._finalize(
            row,
            context,
            worker_ref=worker_ref,
            now=now,
            output=output,
            source_fingerprint=resolution.source_fingerprint,
            content=fingerprint,
            provider_email_id=email.id,
            provider_thread_id=email.thread_id,
            policy=authorization,
            disposition="SEMANTIC_CLASSIFIED",
        )

    @staticmethod
    def _aware(value: dt.datetime) -> dt.datetime:
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value

    def _load_context(self, evaluation):
        with self._engine.connect() as connection:
            event = connection.execute(
                sa.select(acquisition_provider_event).where(
                    acquisition_provider_event.c.provider_event_ref
                    == evaluation["provider_event_ref"]
                )
            ).mappings().one()
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == evaluation["campaign_ref"]
                )
            ).mappings().one()
            member = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.member_ref == evaluation["member_ref"]
                )
            ).mappings().one()
            contact = connection.execute(
                sa.select(acquisition_contact).where(
                    acquisition_contact.c.contact_ref == evaluation["contact_ref"]
                )
            ).mappings().one()
        return {"event": event, "campaign": campaign, "member": member, "contact": contact}

    def _finalize_ambiguous(
        self,
        row,
        context,
        *,
        worker_ref: str,
        now: dt.datetime,
        reason: ResponseReasonCode,
        source_fingerprint: str | None = None,
        content=None,
        provider_email_id: str | None = None,
        provider_thread_id: str | None = None,
        policy: ResponsePolicyAuthorization | None = None,
        human_response_confirmed: bool = False,
    ) -> ResponseWorkerResult:
        output = ResponseClassifierOutput(
            classification=ResponseClassification.AMBIGUOUS,
            confidence=Decimal("0"),
            reason_codes=(reason,),
            hot_lead=False,
            review_required=True,
            classifier_version=row["classifier_version"],
            language=context["campaign"]["language"],
            human_response_confirmed=human_response_confirmed,
        )
        return self._finalize(
            row,
            context,
            worker_ref=worker_ref,
            now=now,
            output=output,
            source_fingerprint=source_fingerprint or row["source_fingerprint"],
            content=content,
            provider_email_id=provider_email_id,
            provider_thread_id=provider_thread_id,
            policy=policy,
            disposition="FAIL_CLOSED_REVIEW",
        )

    def _finalize(
        self,
        row,
        context,
        *,
        worker_ref: str,
        now: dt.datetime,
        output: ResponseClassifierOutput,
        source_fingerprint: str,
        content,
        provider_email_id: str | None,
        provider_thread_id: str | None,
        policy: ResponsePolicyAuthorization | None,
        disposition: str,
    ) -> ResponseWorkerResult:
        derived = derive_business_disposition(output)
        usage = output.usage
        with self._engine.begin() as connection:
            current = ResponseStore.get_in_transaction(
                connection, row["response_evaluation_id"]
            )
            if current["processing_state"] == "FINALIZED":
                return ResponseWorkerResult(ResponseWorkerStatus.REPLAYED, current)
            if current["processing_state"] != "IN_FLIGHT" or current["lease_owner"] != worker_ref:
                raise ResponseEvaluationConflict(row["response_evaluation_id"])
            member = connection.execute(
                sa.select(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == row["member_ref"])
                .with_for_update()
            ).mappings().one()
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == row["member_ref"])
                .values(
                    execution_state=(
                        "SENT" if member["execution_state"] == "SENT" else "STOPPED"
                    ),
                    sequence_state="STOPPED",
                    updated_at=now,
                )
            )
            suppression_ref = self._write_suppression(
                connection, row, output=output, now=now
            )
            outcome_ref, action_ref = self._write_events(
                connection,
                row,
                output=output,
                record_replied=derived.record_replied,
                next_action=derived.next_action,
                now=now,
            )
            finalized = ResponseStore.finalize_in_transaction(
                connection,
                row["response_evaluation_id"],
                worker_ref=worker_ref,
                value=ResponseFinalization(
                    input_source=(
                        ResponseInputSource.INSTANTLY_EMAIL_V2
                        if provider_email_id is not None
                        else ResponseInputSource.WEBHOOK_V2
                    ),
                    source_fingerprint=source_fingerprint,
                    provider_email_id=provider_email_id,
                    provider_thread_id=provider_thread_id,
                    content_fingerprint=(content.fingerprint if content else None),
                    content_fingerprint_version=(content.version if content else None),
                    content_fingerprint_key_version=(content.key_version if content else None),
                    prompt_version=self._prompt_version,
                    model_version=self._model_version,
                    classification=output.classification,
                    confidence=output.confidence,
                    reason_codes=output.reason_codes,
                    human_response_confirmed=output.human_response_confirmed,
                    hot_lead=derived.hot_lead,
                    review_required=derived.review_required,
                    next_action=derived.next_action,
                    policy_evaluation_id=(policy.policy_evaluation_id if policy else None),
                    policy_action_fingerprint=(
                        policy.policy_action_fingerprint if policy else None
                    ),
                    policy_status=(policy.policy_status if policy else None),
                    actual_cost=(usage.cost if usage else Decimal("0")),
                    input_tokens=(usage.input_tokens if usage else 0),
                    output_tokens=(usage.output_tokens if usage else 0),
                    disposition=disposition,
                    outcome_event_ref=outcome_ref,
                    next_action_event_ref=action_ref,
                    suppression_ref=suppression_ref,
                    evaluated_at=now,
                    finalized_at=now,
                ),
            )
        return ResponseWorkerResult(ResponseWorkerStatus.FINALIZED, finalized.row)

    def _write_suppression(self, connection, row, *, output, now):
        if output.classification is ResponseClassification.UNSUBSCRIBE:
            source = SuppressionSource.UNSUBSCRIBE
            reason = SuppressionReasonCode.UNSUBSCRIBED
        elif output.classification is ResponseClassification.COMPLAINT:
            source = SuppressionSource.RECIPIENT_OBJECTION
            reason = SuppressionReasonCode.RECIPIENT_OBJECTED
        else:
            return None
        suppression = self._suppressions.record_for_contact_in_transaction(
            connection,
            row["contact_ref"],
            source=source,
            reason_code=reason,
            evidence_ref=f"suppression-evidence:{row['response_ref']}",
            received_at=now,
        )
        return suppression["suppression_id"]

    def _write_events(
        self,
        connection,
        row,
        *,
        output,
        record_replied: bool,
        next_action: str | None,
        now: dt.datetime,
    ) -> tuple[str | None, str]:
        acquisition = AcquisitionStore(self._engine, clock=lambda: now)
        opportunity = acquisition.get_opportunity_in_transaction(
            connection, row["acquisition_opportunity_id"], for_update=True
        )
        evidence = (
            f"response-evaluation:{row['response_evaluation_id']}",
            f"provider-event:{row['provider_event_ref']}",
        )
        outcome_ref = None
        if record_replied:
            result = acquisition.append_in_transaction(
                connection,
                opportunity.acquisition_opportunity_id,
                event_type=EventType.OUTCOME_RECORDED,
                expected_version=opportunity.stream_version,
                idempotency_key=f"response_outcome:{row['response_evaluation_id']}",
                payload={"outcome_state": AcquisitionState.REPLIED.value},
                actor_type=ActorType.EXTERNAL,
                actor_ref="instantly-response",
                reason_codes=tuple(item.value for item in output.reason_codes),
                evidence_refs=evidence,
                confidence=output.confidence,
                occurred_at=now,
            )
            opportunity = result.projection
            outcome_ref = result.event.event_id
        result = acquisition.append_in_transaction(
            connection,
            opportunity.acquisition_opportunity_id,
            event_type=EventType.NEXT_ACTION_SET,
            expected_version=opportunity.stream_version,
            idempotency_key=f"response_next_action:{row['response_evaluation_id']}",
            payload={"next_action": next_action},
            actor_type=ActorType.SYSTEM,
            actor_ref="kivou-response-intelligence",
            reason_codes=(f"RESPONSE_{output.classification.value}",),
            evidence_refs=evidence,
            occurred_at=now,
        )
        return outcome_ref, result.event.event_id


__all__ = [
    "ResponsePolicyAuthorization",
    "ResponsePolicyAuthorizer",
    "ResponsePolicyFacts",
    "ResponseWorker",
    "ResponseWorkerResult",
    "ResponseWorkerStatus",
]
