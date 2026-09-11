"""Project verified Instantly events onto assisted prospect targets."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json

import sqlalchemy as sa

from signals.campaigns.webhooks import (
    InstantlyWebhookPayload,
    ProviderEventType,
    WebhookBindingError,
    WebhookFingerprintKeyring,
    WebhookIngestResult,
)
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    prospect_delivery_event,
    prospect_target,
    supplier_directory,
)


class AssistedProspectWebhookProjector:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        provider_workspace_ref: str,
        fingerprint_keyring: WebhookFingerprintKeyring,
        suppression_keyring: SuppressionIdentityKeyring,
    ) -> None:
        self._engine = engine
        self._workspace = provider_workspace_ref
        self._fingerprints = fingerprint_keyring
        self._suppressions = SuppressionStore(engine, suppression_keyring)

    def handles(self, payload: InstantlyWebhookPayload) -> bool:
        with self._engine.connect() as connection:
            return bool(
                connection.scalar(
                    sa.select(sa.literal(1))
                    .where(
                        prospect_target.c.provider_campaign_id
                        == payload.provider_campaign_id
                    )
                    .limit(1)
                )
            )

    def _fingerprint(self, payload: InstantlyWebhookPayload) -> str:
        stable = {
            "kind": "assisted-prospect-provider-event-v1",
            "event_type": payload.event_type_transport_only,
            "workspace": payload.provider_workspace_ref,
            "campaign_id": payload.provider_campaign_id,
            "email_id": payload.provider_email_event_id,
            "lead_email": payload.lead_email_transient,
            "timestamp": payload.timestamp.astimezone(dt.UTC).isoformat(),
            "reply": (
                payload.reply_text_transient
                or payload.reply_text_snippet_transient
                or payload.reply_subject_transient
            ),
        }
        encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
        key = self._fingerprints.keys[self._fingerprints.current_key_version]
        return hmac.new(
            key,
            b"kivou:assisted-prospect-event:v1\0" + encoded,
            hashlib.sha256,
        ).hexdigest()

    def ingest_payload(
        self,
        payload: InstantlyWebhookPayload,
        *,
        received_at: dt.datetime,
    ) -> WebhookIngestResult:
        if payload.provider_workspace_ref != self._workspace:
            raise WebhookBindingError("Instantly workspace mismatch")
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("webhook received_at must be timezone-aware")
        if abs(received_at - payload.timestamp.astimezone(dt.UTC)) > dt.timedelta(days=7):
            raise WebhookBindingError("Instantly event timestamp is outside the accepted bound")
        fingerprint = self._fingerprint(payload)
        with self._engine.begin() as connection:
            if connection.scalar(
                sa.select(prospect_delivery_event.c.event_fingerprint).where(
                    prospect_delivery_event.c.event_fingerprint == fingerprint
                )
            ):
                return WebhookIngestResult(event_fingerprint=fingerprint, replayed=True)
            query = sa.select(prospect_target).where(
                prospect_target.c.provider_campaign_id == payload.provider_campaign_id
            )
            if payload.lead_email_transient is not None:
                query = query.where(
                    sa.func.lower(prospect_target.c.email_address)
                    == payload.lead_email_transient.casefold()
                )
            rows = tuple(connection.execute(query.limit(2)).mappings())
            member_required = payload.event_type not in {
                None,
                ProviderEventType.CAMPAIGN_COMPLETED,
                ProviderEventType.ACCOUNT_ERROR,
            }
            if member_required and len(rows) != 1:
                raise WebhookBindingError("unknown assisted provider lead binding")
            row = dict(rows[0]) if len(rows) == 1 else None
            inserted = insert_if_absent(
                connection,
                prospect_delivery_event,
                {
                    "event_fingerprint": fingerprint,
                    "target_id": row["target_id"] if row else None,
                    "provider_campaign_id": payload.provider_campaign_id,
                    "provider_event_type": payload.event_type_transport_only,
                    "occurred_at": payload.timestamp,
                    "received_at": received_at,
                },
                index_elements=[prospect_delivery_event.c.event_fingerprint],
            )
            if not inserted:
                return WebhookIngestResult(event_fingerprint=fingerprint, replayed=True)
            if row is not None:
                values = self._target_values(payload, row, received_at)
                connection.execute(
                    sa.update(prospect_target)
                    .where(prospect_target.c.target_id == row["target_id"])
                    .values(**values)
                )
                if payload.event_type is ProviderEventType.EMAIL_BOUNCED:
                    connection.execute(
                        sa.update(supplier_directory)
                        .where(supplier_directory.c.siren == row["siren"])
                        .values(
                            email_verification_status="mx_failed",
                            reverification_required_at=received_at,
                            reverification_reason="instantly_bounce",
                            updated_at=received_at,
                        )
                    )
                elif payload.event_type is ProviderEventType.LEAD_UNSUBSCRIBED:
                    self._suppressions.record_for_email_in_transaction(
                        connection,
                        str(row["email_address"]),
                        source=SuppressionSource.UNSUBSCRIBE,
                        reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                        evidence_ref=f"suppression-evidence:{fingerprint}",
                        received_at=payload.timestamp,
                    )
                    connection.execute(
                        sa.update(supplier_directory)
                        .where(supplier_directory.c.siren == row["siren"])
                        .values(suppressed_at=received_at, updated_at=received_at)
                    )
            elif payload.event_type is ProviderEventType.ACCOUNT_ERROR:
                connection.execute(
                    sa.update(prospect_target)
                    .where(
                        prospect_target.c.provider_campaign_id
                        == payload.provider_campaign_id
                    )
                    .values(delivery_error="instantly_account_error", updated_at=received_at)
                )
        return WebhookIngestResult(event_fingerprint=fingerprint, replayed=False)

    @staticmethod
    def _target_values(
        payload: InstantlyWebhookPayload,
        row: dict[str, object],
        received_at: dt.datetime,
    ) -> dict[str, object]:
        values: dict[str, object] = {
            "version": int(row["version"]) + 1,
            "updated_at": received_at,
        }
        event = payload.event_type
        if event is ProviderEventType.EMAIL_SENT:
            values.update(delivery_status="sent", sent_at=row.get("sent_at") or payload.timestamp)
        elif event is ProviderEventType.EMAIL_OPENED:
            values.update(delivery_status="opened", opened_at=row.get("opened_at") or payload.timestamp)
        elif event in {ProviderEventType.EMAIL_LINK_CLICKED, ProviderEventType.LINK_CLICKED}:
            values.update(delivery_status="clicked", clicked_at=row.get("clicked_at") or payload.timestamp)
        elif event is ProviderEventType.REPLY_RECEIVED:
            values.update(
                delivery_status="replied",
                replied_at=row.get("replied_at") or payload.timestamp,
                reply_classification="human_reply",
            )
        elif event is ProviderEventType.AUTO_REPLY_RECEIVED:
            values.update(
                delivery_status="replied",
                replied_at=row.get("replied_at") or payload.timestamp,
                reply_classification="auto_reply",
            )
        elif event is ProviderEventType.EMAIL_BOUNCED:
            values.update(delivery_status="bounced", bounced_at=payload.timestamp)
        elif event is ProviderEventType.LEAD_UNSUBSCRIBED:
            values.update(delivery_status="unsubscribed", unsubscribed_at=payload.timestamp)
        return values


__all__ = ["AssistedProspectWebhookProjector"]
