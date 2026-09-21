"""Authenticated Instantly event simulation for one-prospect SHADOW bindings.

This module deliberately has no public webhook route or provider write method.
Future grouped campaigns require a separately reviewed lead identity binding.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import EventType
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.webhooks import (
    ProviderEventType,
    normalize_instantly_webhook_payload,
)
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.persistence.schema import (
    acquisition_event,
    acquisition_program,
    acquisition_program_attribution,
)
from signals.prospection_actions.suppression import EmailSuppressionChecker

_ACCEPTED = frozenset(
    {
        ProviderEventType.EMAIL_SENT,
        ProviderEventType.EMAIL_BOUNCED,
        ProviderEventType.REPLY_RECEIVED,
        ProviderEventType.AUTO_REPLY_RECEIVED,
        ProviderEventType.LEAD_UNSUBSCRIBED,
    }
)
_STOP = frozenset(
    {
        ProviderEventType.EMAIL_BOUNCED.value,
        ProviderEventType.REPLY_RECEIVED.value,
        ProviderEventType.AUTO_REPLY_RECEIVED.value,
        ProviderEventType.LEAD_UNSUBSCRIBED.value,
    }
)


class MilomailInstantlyEventSimulation:
    def __init__(
        self,
        engine: Engine,
        acquisition: AcquisitionStore,
        *,
        program_id: str,
        workspace_ref: str,
        webhook_secret: str,
        suppression_keyring: SuppressionIdentityKeyring,
    ) -> None:
        if not webhook_secret or len(webhook_secret.encode()) < 16:
            raise ValueError("Milo Mail Instantly webhook secret is unavailable")
        self._engine = engine
        self._acquisition = acquisition
        self._program_id = program_id
        self._workspace = workspace_ref
        self._secret = webhook_secret
        self._keyring = suppression_keyring
        self._suppressions = SuppressionStore(
            engine,
            suppression_keyring,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )
        self._checker = EmailSuppressionChecker(
            suppression_keyring,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )

    def ingest(
        self,
        raw: dict[str, object],
        *,
        supplied_secret: str,
        received_at: dt.datetime,
    ) -> str:
        if not hmac.compare_digest(supplied_secret.encode(), self._secret.encode()):
            raise ValueError("Milo Mail Instantly webhook authentication failed")
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("provider event reception must be timezone-aware")
        try:
            payload = normalize_instantly_webhook_payload(raw)
        except (TypeError, ValueError):
            raise ValueError("invalid Milo Mail Instantly event") from None
        if payload.provider_workspace_ref != self._workspace:
            raise ValueError("Milo Mail Instantly workspace mismatch")
        if payload.event_type not in _ACCEPTED:
            raise ValueError("provider event type is not supported in simulation")
        if abs(received_at - payload.timestamp) > dt.timedelta(days=7):
            raise ValueError("provider event outside accepted time bound")
        if not payload.lead_email_transient or not payload.provider_email_event_id:
            raise ValueError("provider event needs a bound lead and opaque event ID")
        recipient_identity = self._keyring.identities_for_email(
            payload.lead_email_transient,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )[self._keyring.current_key_version]
        event_key = hmac.new(
            self._secret.encode(),
            b"milomail:instantly-event:v1\0"
            + payload.provider_workspace_ref.encode()
            + b"\0"
            + payload.provider_campaign_id.encode()
            + b"\0"
            + payload.event_type.value.encode()
            + b"\0"
            + recipient_identity.encode()
            + b"\0"
            + payload.provider_email_event_id.encode()
            + b"\0"
            + payload.timestamp.isoformat().encode(),
            hashlib.sha256,
        ).hexdigest()
        with self._engine.begin() as connection:
            program = (
                connection.execute(
                    sa.select(acquisition_program).where(
                        acquisition_program.c.program_id == self._program_id
                    )
                )
                .mappings()
                .one()
            )
            if (
                program["program_key"] != "milomail"
                or program["mode"] != "SHADOW"
                or program["config_snapshot"].get("instantly_workspace_ref") != self._workspace
            ):
                raise ValueError("Milo Mail program/workspace binding mismatch")
            bindings = (
                connection.execute(
                    sa.select(acquisition_program_attribution)
                    .where(
                        acquisition_program_attribution.c.program_id == self._program_id,
                        acquisition_program_attribution.c.campaign_ref
                        == payload.provider_campaign_id,
                    )
                    .limit(2)
                )
                .mappings()
                .all()
            )
            if len(bindings) != 1:
                raise ValueError("simulated campaign must bind exactly one prospect")
            binding = bindings[0]
            if (
                binding["recipient_identity_key_version"] not in self._keyring.keys
                or self._keyring.identities_for_email(
                    payload.lead_email_transient,
                    scope=MILOMAIL_SUPPRESSION_SCOPE,
                )[binding["recipient_identity_key_version"]]
                != binding["recipient_identity_hmac"]
            ):
                raise ValueError("provider lead identity mismatch")
            opportunity_id = binding["acquisition_opportunity_id"]
            current = self._acquisition.get_opportunity_in_transaction(
                connection,
                opportunity_id,
                for_update=True,
            )
            appended = self._acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.POLICY_EVALUATED,
                expected_version=current.stream_version,
                idempotency_key=event_key,
                payload={
                    "kind": "program_provider_event",
                    "program_id": self._program_id,
                    "attribution_id": binding["attribution_id"],
                    "campaign_ref": binding["campaign_ref"],
                    "event_type": payload.event_type.value,
                    "recipient_identity_hmac": recipient_identity,
                },
                reason_codes=(payload.event_type.value.upper(),),
                policy_version="milomail-provider-event-v1",
                occurred_at=payload.timestamp,
            )
            if appended.replayed:
                return event_key
            if payload.event_type is ProviderEventType.LEAD_UNSUBSCRIBED:
                self._suppressions.record_for_email_in_transaction(
                    connection,
                    payload.lead_email_transient,
                    source=SuppressionSource.UNSUBSCRIBE,
                    reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                    evidence_ref=suppression_evidence_ref("INSTANTLY_UNSUBSCRIBE", event_key),
                    received_at=received_at,
                )
        return event_key

    def follow_up_allowed(self, email: str, *, at: dt.datetime) -> bool:
        """SHADOW denies export after inspecting suppression and stop events."""
        with self._engine.begin() as connection:
            if self._checker.is_suppressed(connection, email=email, at=at):
                return False
            identities = self._keyring.identities_for_email(
                email,
                scope=MILOMAIL_SUPPRESSION_SCOPE,
            )
            stop_events = connection.execute(
                sa.select(acquisition_event.c.payload).where(
                    acquisition_event.c.payload["kind"].as_string() == "program_provider_event",
                )
            ).scalars()
            if any(
                payload.get("program_id") == self._program_id
                and payload.get("recipient_identity_hmac") in identities.values()
                and payload.get("event_type") in _STOP
                for payload in stop_events
            ):
                return False
        return False  # SHADOW is an unconditional final export guard.


__all__ = ["MilomailInstantlyEventSimulation"]
