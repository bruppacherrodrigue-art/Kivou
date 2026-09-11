from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.compliance.suppression import SUPPRESSION_SCOPE, SuppressionIdentityKeyring
from signals.persistence.schema import METADATA, acquisition_contact_suppression
from signals.prospection_actions.suppression import EmailSuppressionChecker

NOW = dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC)


def test_email_suppression_checker_matches_email_without_legacy_contact() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    METADATA.create_all(engine)
    keyring = SuppressionIdentityKeyring(current_key_version="v1", keys={"v1": b"x" * 32})
    identity = keyring.identities_for_email("person@example.fr")["v1"]
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_contact_suppression).values(
                suppression_id="s" * 64,
                identity_hmac=identity,
                identity_key_version="v1",
                scope=SUPPRESSION_SCOPE,
                source="UNSUBSCRIBE",
                reason_code="UNSUBSCRIBED",
                evidence_ref="suppression-evidence:" + "e" * 64,
                received_at=NOW,
                effective_at=NOW,
                minimum_retention_until=NOW + dt.timedelta(days=365 * 3),
                created_at=NOW,
            )
        )
        checker = EmailSuppressionChecker(keyring)
        assert checker.is_suppressed(connection, email="PERSON@example.fr", at=NOW)
        assert not checker.is_suppressed(connection, email="other@example.fr", at=NOW)
