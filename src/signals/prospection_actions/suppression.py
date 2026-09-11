"""Email-wide suppression checks for Founder-assisted delivery."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.compliance.suppression import SUPPRESSION_SCOPE, SuppressionIdentityKeyring
from signals.persistence.schema import acquisition_contact_suppression


class EmailSuppressionChecker:
    def __init__(self, keyring: SuppressionIdentityKeyring) -> None:
        self._keyring = keyring

    def is_suppressed(
        self,
        connection: sa.Connection,
        *,
        email: str,
        at: dt.datetime,
    ) -> bool:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("suppression assessment time must be timezone-aware")
        identities = self._keyring.identities_for_email(email)
        retained = tuple(
            connection.execute(
                sa.select(acquisition_contact_suppression.c.identity_key_version)
                .where(acquisition_contact_suppression.c.scope == SUPPRESSION_SCOPE)
                .distinct()
            ).scalars()
        )
        self._keyring.require_versions_covered(retained)
        predicates = tuple(
            sa.and_(
                acquisition_contact_suppression.c.identity_key_version == version,
                acquisition_contact_suppression.c.identity_hmac == identity,
            )
            for version, identity in identities.items()
        )
        return bool(
            connection.scalar(
                sa.select(sa.literal(1))
                .where(
                    acquisition_contact_suppression.c.scope == SUPPRESSION_SCOPE,
                    acquisition_contact_suppression.c.effective_at <= at,
                    sa.or_(*predicates),
                )
                .limit(1)
            )
        )


__all__ = ["EmailSuppressionChecker"]
