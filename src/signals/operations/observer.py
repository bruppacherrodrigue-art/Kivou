"""Explicit no-autostart observer over existing authoritative acquisition facts."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.operations.circuit_breakers import (
    BounceObservation,
    CircuitBreakerService,
    ProviderFailureObservation,
)
from signals.operations.contracts import BreakerScope, canonical_fingerprint
from signals.operations.safety_controller import SafetyController
from signals.operations.store import OperationsStore, SaveResult
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_provider_event,
    acquisition_provider_operation,
    acquisition_response_evaluation,
)
from signals.policy.contracts import PolicyControlUnavailable
from signals.policy.store import PolicyStore

_CRITICAL_TRANSPORT_CODES = {
    "UNEXPECTED_EMAIL_SENT_AFTER_STOP",
    "CONFLICTING_STEP1_TRANSPORT_TRUTH",
    "DUPLICATE_BUSINESS_SEND",
    "TRANSPORT_STATE_CONFLICT",
}
_POSITIVE_PROVIDER_KINDS = {
    "CREATE_CAMPAIGN",
    "CONFIGURE_CAMPAIGN",
    "ADD_LEAD",
    "ACTIVATE_CAMPAIGN",
}


@dataclass(frozen=True)
class ObservationResult:
    incident_refs: tuple[str, ...]


class RepositoryReliabilityObserver:
    """Scan one campaign from local tables and materialize bounded safety facts."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._store = OperationsStore(engine)
        self._breakers = CircuitBreakerService(self._store)
        self._safety = SafetyController(engine)
        self._policy = PolicyStore(engine)

    def scan_campaign(
        self, campaign_ref: str, *, observed_at: dt.datetime
    ) -> ObservationResult:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observation time must be timezone-aware")
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            events = connection.execute(
                sa.select(acquisition_provider_event)
                .where(acquisition_provider_event.c.campaign_ref == campaign_ref)
                .order_by(
                    acquisition_provider_event.c.occurred_at,
                    acquisition_provider_event.c.provider_event_ref,
                )
            ).mappings().all()
            complaints = connection.execute(
                sa.select(acquisition_response_evaluation).where(
                    acquisition_response_evaluation.c.campaign_ref == campaign_ref,
                    acquisition_response_evaluation.c.processing_state == "FINALIZED",
                    acquisition_response_evaluation.c.classification == "COMPLAINT",
                )
            ).mappings().all()
            operations = connection.execute(
                sa.select(acquisition_provider_operation)
                .where(acquisition_provider_operation.c.campaign_ref == campaign_ref)
                .order_by(
                    acquisition_provider_operation.c.updated_at.desc(),
                    acquisition_provider_operation.c.operation_ref.desc(),
                )
            ).mappings().all()

        outcomes: list[SaveResult] = []
        sent_members = tuple(
            sorted(
                {
                    row["member_ref"]
                    for row in events
                    if row["provider_event_type"] == "email_sent"
                    and row["step"] == 1
                    and row["member_ref"] is not None
                }
            )
        )
        bounced_members = tuple(
            sorted(
                {
                    row["member_ref"]
                    for row in events
                    if row["provider_event_type"] == "email_bounced"
                    and row["step"] == 1
                    and row["member_ref"] in sent_members
                }
            )
        )
        bounce = self._breakers.observe_bounces(
            BounceObservation(
                scope=BreakerScope(scope_type="CAMPAIGN", scope_ref=campaign_ref),
                authoritative_step1_members=sent_members,
                bounced_step1_members=bounced_members,
                source_state_ref=canonical_fingerprint(
                    "campaign-bounce-observation:v1",
                    {
                        "campaign_ref": campaign_ref,
                        "sent": sent_members,
                        "bounced": bounced_members,
                    },
                ),
                observed_at=observed_at,
                campaign_ref=campaign_ref,
                wedge=campaign["wedge"],
                country=campaign["country"],
            )
        )
        if bounce is not None:
            outcomes.append(bounce)
            self._downgrade(bounce, observed_at=observed_at, critical=False)

        for complaint in complaints:
            outcome = self._breakers.observe_complaint(
                campaign_ref=campaign_ref,
                response_evaluation_ref=complaint["response_evaluation_id"],
                observed_at=observed_at,
            )
            outcomes.append(outcome)
            self._downgrade(outcome, observed_at=observed_at, critical=False)

        for event in events:
            code = event["incident_code"]
            if code not in _CRITICAL_TRANSPORT_CODES:
                continue
            outcome = self._breakers.observe_critical_transport(
                campaign_ref=campaign_ref,
                provider_event_ref=event["provider_event_ref"],
                incident_code=code,
                observed_at=observed_at,
            )
            outcomes.append(outcome)
            self._downgrade(outcome, observed_at=observed_at, critical=True)

        qualifying_refs: list[str] = []
        qualifying_codes: list[str] = []
        for operation in operations:
            if operation["kind"] not in _POSITIVE_PROVIDER_KINDS:
                continue
            code = operation["error_code"] or operation["state"]
            if operation["state"] in {"TERMINAL_FAILED", "RECONCILE_REQUIRED"}:
                if code == "RATE_LIMITED":
                    continue
                qualifying_refs.append(operation["operation_ref"])
                qualifying_codes.append(code)
                if len(qualifying_refs) == 3:
                    break
                continue
            if operation["state"] == "RETRYABLE_FAILED" and code != "RATE_LIMITED":
                qualifying_refs.append(operation["operation_ref"])
                qualifying_codes.append(code)
                if len(qualifying_refs) == 3:
                    break
                continue
            break
        provider = self._breakers.observe_provider_failures(
            ProviderFailureObservation(
                scope=BreakerScope(scope_type="CAMPAIGN", scope_ref=campaign_ref),
                failure_refs=tuple(qualifying_refs),
                failure_codes=tuple(qualifying_codes),
                source_state_ref=canonical_fingerprint(
                    "campaign-provider-failure-observation:v1", qualifying_refs
                ),
                observed_at=observed_at,
                campaign_ref=campaign_ref,
            )
        )
        if provider is not None:
            outcomes.append(provider)
            self._downgrade(provider, observed_at=observed_at, critical=False)

        return ObservationResult(
            incident_refs=tuple(sorted({item.row["incident_ref"] for item in outcomes}))
        )

    def _downgrade(
        self, outcome: SaveResult, *, observed_at: dt.datetime, critical: bool
    ) -> None:
        try:
            before = self._policy.get_effective_control(observed_at)
        except PolicyControlUnavailable:
            return
        reason = (
            "CRITICAL_OPERATIONAL_INCIDENT" if critical else "OPERATIONAL_INCIDENT",
            f"INCIDENT_{outcome.row['incident_ref'][:16].upper()}",
        )
        after = (
            self._safety.critical_stop(at=observed_at, reason_codes=reason)
            if critical
            else self._safety.downgrade(at=observed_at, reason_codes=reason)
        )
        self._store.bind_incident_policy_controls(
            outcome.row["incident_ref"],
            before_ref=before.policy_snapshot_id,
            after_ref=after.policy_snapshot_id,
            at=observed_at,
        )


__all__ = ["ObservationResult", "RepositoryReliabilityObserver"]
