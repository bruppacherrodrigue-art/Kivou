"""Signed visible unsubscribe flow for assisted prospect messages."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring, suppression_evidence_ref
from signals.conversion.source import AttributionSourceResolver
from signals.conversion.token import AttributionTokenKeyring
from signals.persistence.schema import prospect_target, supplier_directory


class ProspectUnsubscribeService:
    def __init__(
        self,
        engine: Engine,
        *,
        attribution_keyring: AttributionTokenKeyring,
        suppression_keyring: SuppressionIdentityKeyring,
    ) -> None:
        self._engine = engine
        self._attribution = attribution_keyring
        self._sources = AttributionSourceResolver(engine)
        self._suppressions = SuppressionStore(engine, suppression_keyring)

    def verify(self, raw_token: str, *, at: dt.datetime) -> str:
        with self._engine.connect() as connection:
            return self._target_id(connection, raw_token=raw_token, at=at)

    def unsubscribe(self, raw_token: str, *, at: dt.datetime) -> str:
        with self._engine.begin() as connection:
            target_id = self._target_id(connection, raw_token=raw_token, at=at)
            row = connection.execute(
                sa.select(prospect_target)
                .where(prospect_target.c.target_id == target_id)
                .with_for_update()
            ).mappings().one()
            if row["unsubscribed_at"] is None:
                self._suppressions.record_for_email_in_transaction(
                    connection,
                    str(row["email_address"]),
                    source=SuppressionSource.UNSUBSCRIBE,
                    reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                    evidence_ref=suppression_evidence_ref(
                        "assisted-visible-unsubscribe", str(row["target_id"])
                    ),
                    received_at=at,
                )
                connection.execute(
                    sa.update(prospect_target)
                    .where(prospect_target.c.target_id == target_id)
                    .values(
                        delivery_status="unsubscribed",
                        unsubscribed_at=at,
                        version=prospect_target.c.version + 1,
                        updated_at=at,
                    )
                )
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(suppressed_at=at, updated_at=at)
                )
            return target_id

    def _target_id(
        self,
        connection: sa.Connection,
        *,
        raw_token: str,
        at: dt.datetime,
    ) -> str:
        lookup = self._attribution.parse(raw_token)
        payload = self._sources.for_member(connection, lookup.member_ref)
        verified = self._attribution.verify(raw_token, payload=payload, at=at)
        target_id = connection.scalar(
            sa.select(prospect_target.c.target_id).where(
                prospect_target.c.attribution_member_ref == verified.payload.member_ref
            )
        )
        if target_id is None:
            raise ValueError("unsubscribe target is unavailable")
        return str(target_id)


__all__ = ["ProspectUnsubscribeService"]
