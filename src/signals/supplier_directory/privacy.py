"""Recipient-requested removal with campaign-wide suppression propagation."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.persistence.schema import (
    acquisition_contact,
    acquisition_supplier,
    supplier_directory,
)


class SupplierDirectoryPrivacyService:
    def __init__(self, engine: Engine, *, keyring: SuppressionIdentityKeyring) -> None:
        self._engine = engine
        self._suppressions = SuppressionStore(engine, keyring)

    def suppress(self, siren: str, *, received_at: dt.datetime) -> int:
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        evidence_ref = suppression_evidence_ref("supplier_directory_request", siren)
        with self._engine.begin() as connection:
            directory = (
                connection.execute(
                    sa.select(supplier_directory)
                    .where(supplier_directory.c.siren == siren)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            contact_refs = tuple(
                connection.execute(
                    sa.select(acquisition_contact.c.contact_ref)
                    .select_from(
                        acquisition_contact.join(
                            acquisition_supplier,
                            acquisition_supplier.c.supplier_ref
                            == acquisition_contact.c.supplier_ref,
                        )
                    )
                    .where(
                        acquisition_supplier.c.provider == "sirene",
                        acquisition_supplier.c.provider_organization_id == siren,
                        acquisition_contact.c.business_email == directory["professional_email"],
                    )
                ).scalars()
            )
            for contact_ref in contact_refs:
                self._suppressions.record_for_contact_in_transaction(
                    connection,
                    contact_ref,
                    source=SuppressionSource.RECIPIENT_OBJECTION,
                    reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
                    evidence_ref=evidence_ref,
                    received_at=received_at,
                )
            connection.execute(
                sa.update(supplier_directory)
                .where(supplier_directory.c.siren == siren)
                .values(
                    directors=[],
                    directors_observed_at=received_at,
                    professional_email=None,
                    email_source=None,
                    email_verification_status=None,
                    email_contact_name=None,
                    email_contact_title=None,
                    email_observed_at=received_at,
                    suppressed_at=received_at,
                    updated_at=received_at,
                )
            )
        return len(contact_refs)


__all__ = ["SupplierDirectoryPrivacyService"]
