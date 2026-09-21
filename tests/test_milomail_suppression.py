"""Program-wide Milo Mail opt-outs stay separate from Kivou opt-outs."""

import datetime as dt

import sqlalchemy as sa
from alembic import command

from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.persistence.database import alembic_config, migrate_to_latest
from signals.persistence.schema import acquisition_contact_suppression
from signals.prospection_actions.suppression import EmailSuppressionChecker

NOW = dt.datetime(2026, 9, 21, 12, tzinfo=dt.UTC)


def test_milomail_opt_out_idempotent_and_isolated_across_program_campaigns() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    keyring = SuppressionIdentityKeyring(
        current_key_version="test-v1", keys={"test-v1": b"test-secret-key"}
    )
    milomail = SuppressionStore(engine, keyring, scope=MILOMAIL_SUPPRESSION_SCOPE)
    evidence = suppression_evidence_ref("UNSUBSCRIBE", "opaque-event-1")
    with engine.begin() as connection:
        first = milomail.record_for_email_in_transaction(
            connection,
            "FOUNDER@cabinet.example",
            source=SuppressionSource.UNSUBSCRIBE,
            reason_code=SuppressionReasonCode.UNSUBSCRIBED,
            evidence_ref=evidence,
            received_at=NOW,
        )
        again = milomail.record_for_email_in_transaction(
            connection,
            "founder@cabinet.example",
            source=SuppressionSource.UNSUBSCRIBE,
            reason_code=SuppressionReasonCode.UNSUBSCRIBED,
            evidence_ref=evidence,
            received_at=NOW,
        )
        assert first["suppression_id"] == again["suppression_id"]
        assert EmailSuppressionChecker(keyring, scope=MILOMAIL_SUPPRESSION_SCOPE).is_suppressed(
            connection,
            email="founder@cabinet.example",
            at=NOW,
        )
        assert not EmailSuppressionChecker(keyring, scope=SUPPRESSION_SCOPE).is_suppressed(
            connection,
            email="founder@cabinet.example",
            at=NOW,
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
            )
            == 1
        )


def test_scope_migration_upgrade_and_downgrade() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    checks = sa.inspect(engine).get_check_constraints("acquisition_contact_suppression")
    scope = next(item for item in checks if item["name"] == "ck_suppression_scope")
    assert MILOMAIL_SUPPRESSION_SCOPE in scope["sqltext"]
    command.downgrade(alembic_config(engine), "0068_acquisition_program")
    checks = sa.inspect(engine).get_check_constraints("acquisition_contact_suppression")
    scope = next(item for item in checks if item["name"] == "ck_suppression_scope")
    assert MILOMAIL_SUPPRESSION_SCOPE not in scope["sqltext"]
