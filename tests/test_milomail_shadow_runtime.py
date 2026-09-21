"""The program reuses Kivou's event store without an outbound provider mutation."""

import datetime as dt

import pytest
import sqlalchemy as sa
from test_milomail_policy import NOW, ready_input

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.runtime import MilomailShadowRuntime
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import acquisition_event, acquisition_program_eligibility


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"Instantly provider called in SHADOW: {name}")


def test_shadow_records_send_theory_and_rechecks_suppression() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    created = acquisition.create_opportunity(
        identity_key="acquisition-program:milomail:synthetic-1",
        signal_ref="acquisition-program:milomail:synthetic-1",
        idempotency_key="milomail:synthetic-1",
        occurred_at=NOW,
    )
    keyring = SuppressionIdentityKeyring(
        current_key_version="test-v1", keys={"test-v1": b"test-secret-key"}
    )
    program_store = AcquisitionProgramStore(engine)
    policy_input = ready_input()
    program_id = program_store.register(policy_input.program, at=NOW)
    runtime = MilomailShadowRuntime(engine, acquisition, keyring, ForbiddenProvider())

    decision = runtime.evaluate(
        program_id=program_id,
        opportunity_id=created.projection.acquisition_opportunity_id,
        email="founder@cabinet.example",
        policy_input=policy_input,
    )
    assert decision.decision == "SEND"
    assert (
        runtime.evaluate(
            program_id=program_id,
            opportunity_id=created.projection.acquisition_opportunity_id,
            email="founder@cabinet.example",
            policy_input=policy_input,
        )
        == decision
    )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_program_eligibility)
            )
            == 1
        )
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_event)) == 2
    assert runtime.export_preview(decision) == "BLOCKED_SHADOW"

    suppression = SuppressionStore(engine, keyring, scope=MILOMAIL_SUPPRESSION_SCOPE)
    with engine.begin() as connection:
        suppression.record_for_email_in_transaction(
            connection,
            "founder@cabinet.example",
            source=SuppressionSource.UNSUBSCRIBE,
            reason_code=SuppressionReasonCode.UNSUBSCRIBED,
            evidence_ref=suppression_evidence_ref("UNSUBSCRIBE", "event-1"),
            received_at=NOW + dt.timedelta(minutes=1),
        )
    later = policy_input.model_copy(update={"assessed_at": NOW + dt.timedelta(minutes=2)})
    blocked = runtime.evaluate(
        program_id=program_id,
        opportunity_id=created.projection.acquisition_opportunity_id,
        email="founder@cabinet.example",
        policy_input=later,
    )
    assert blocked.decision == "NO_SEND"
    assert "SUPPRESSION_MATCH" in blocked.reason_codes
    assert runtime.export_preview(blocked) == "BLOCKED_SHADOW"


def test_shadow_rejects_cross_domain_provider_evidence() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    runtime = MilomailShadowRuntime(
        engine,
        AcquisitionStore(engine),
        SuppressionIdentityKeyring(current_key_version="v1", keys={"v1": b"test-secret-key"}),
        ForbiddenProvider(),
    )
    with pytest.raises(ValueError, match="domain evidence mismatch"):
        runtime.evaluate(
            program_id="unused",
            opportunity_id="unused",
            email="person@another.example",
            policy_input=ready_input(),
        )
