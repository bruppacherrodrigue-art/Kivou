"""Synthetic decision corpus proves SHADOW has no outbound mutation."""

import datetime as dt
import hashlib
import hmac
import json

import sqlalchemy as sa
from test_milomail_attribution import synthetic_contact
from test_milomail_policy import NOW, ready_input

from signals.acquisition.store import AcquisitionStore
from signals.acquisition_programs.attribution import (
    MilomailConversionIngress,
    ProgramAttributionKeyring,
    ProgramAttributionService,
)
from signals.acquisition_programs.mail_provider import MailProviderDetector
from signals.acquisition_programs.qualification import (
    FitSignals,
    ProfessionalEvidenceInput,
    RecipientCapacity,
    classify_recipient,
    score_fit,
)
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
from signals.persistence.schema import acquisition_program_conversion_receipt


class MX:
    def __init__(self, records: tuple[str, ...] | None):
        self.records = records

    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
        if self.records is None:
            raise TimeoutError("synthetic DNS timeout")
        return self.records


class NoInstantly:
    def __getattr__(self, name):
        raise AssertionError(f"outbound Instantly call: {name}")


def test_e2e_synthetic_corpus_and_conversion_replay() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_input().program
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1",
        keys={"v1": b"synthetic-suppression-key"},
    )
    runtime = MilomailShadowRuntime(engine, acquisition, suppression_keys, NoInstantly())
    scenarios = (
        (
            "fr_workspace",
            "founder@cabinet.example",
            ("smtp.google.com",),
            "founder",
            "FR",
            True,
            False,
            False,
            "SEND",
        ),
        (
            "microsoft",
            "founder@cabinet.example",
            ("cabinet-example.mail.protection.outlook.com",),
            "founder",
            "FR",
            True,
            False,
            False,
            "NO_SEND",
        ),
        ("gmail_published", "founder@gmail.com", (), "founder", "FR", True, True, False, "NO_SEND"),
        ("gmail_unproven", "founder@gmail.com", (), "founder", "FR", True, False, False, "NO_SEND"),
        (
            "unknown_role",
            "founder@cabinet.example",
            ("aspmx.l.google.com",),
            None,
            "FR",
            True,
            False,
            False,
            "HOLD",
        ),
        (
            "germany",
            "founder@cabinet.example",
            ("smtp.google.com",),
            "founder",
            "DE",
            True,
            False,
            False,
            "NO_SEND",
        ),
        (
            "suppressed",
            "blocked@cabinet.example",
            ("smtp.google.com",),
            "founder",
            "FR",
            True,
            False,
            True,
            "NO_SEND",
        ),
        (
            "dns_timeout",
            "founder@cabinet.example",
            None,
            "founder",
            "FR",
            True,
            False,
            False,
            "HOLD",
        ),
        (
            "zero_budget",
            "founder@cabinet.example",
            ("smtp.google.com",),
            "founder",
            "FR",
            False,
            False,
            False,
            "HOLD",
        ),
    )
    send_opportunity = None
    for name, email, records, role, country, budget, published, suppressed, expected in scenarios:
        observed = NOW + dt.timedelta(minutes=len(name))
        supplier_ref, contact_ref = (
            synthetic_contact(engine, email, name, observed)
            if name == "fr_workspace"
            else (None, None)
        )
        created = acquisition.create_opportunity(
            identity_key=f"acquisition-program:milomail:corpus:{name}",
            signal_ref=f"acquisition-program:milomail:corpus:{name}",
            idempotency_key=f"corpus:{name}",
            supplier_ref=supplier_ref,
            contact_ref=contact_ref,
            occurred_at=observed,
        )
        opportunity_id = created.projection.acquisition_opportunity_id
        if suppressed:
            store = SuppressionStore(engine, suppression_keys, scope=MILOMAIL_SUPPRESSION_SCOPE)
            with engine.begin() as connection:
                store.record_for_email_in_transaction(
                    connection,
                    email,
                    source=SuppressionSource.UNSUBSCRIBE,
                    reason_code=SuppressionReasonCode.UNSUBSCRIBED,
                    evidence_ref=suppression_evidence_ref("UNSUBSCRIBE", "corpus-optout"),
                    received_at=NOW,
                )
        detector = MailProviderDetector(MX(records), attempts=1)
        provider = detector.detect_email(email, observed_at=observed)
        capacity = classify_recipient(
            ProfessionalEvidenceInput(
                email=email,
                company_domain="cabinet.example",
                company_id="company:synthetic",
                company_active=True,
                role=role,
                email_verified=True,
                professional_source_url="https://cabinet.example/equipe",
                professional_source_type="COMPANY_WEBSITE",
                professional_evidence_observed_at=NOW,
                email_explicitly_published=published,
            ),
            config=config,
            at=observed,
        )
        fit = score_fit(
            FitSignals(
                provider=provider.provider,
                provider_confirmed=provider.confidence.value == "CONFIRMED",
                sector="consulting",
                role=role,
                employee_count=5,
                recent_public_activity_source="https://cabinet.example/actualites",
                operational_decision_maker=role is not None,
            ),
            config=config,
        )
        value = ready_input().model_copy(
            update={
                "provider": provider,
                "capacity": capacity,
                "fit": fit,
                "country": country,
                "daily_remaining": 10 if budget else 0,
                "assessed_at": observed,
                "suppressed": False,
            }
        )
        decision = runtime.evaluate(
            program_id=program_id,
            opportunity_id=opportunity_id,
            email=email,
            policy_input=value,
        )
        assert decision.decision == expected, (name, decision.reason_codes)
        assert runtime.export_preview(decision) == "BLOCKED_SHADOW"
        if name == "gmail_published":
            assert capacity.capacity is RecipientCapacity.CONFIRMED_PROFESSIONAL
        if name == "gmail_unproven":
            assert capacity.capacity is RecipientCapacity.PERSONAL
        if name == "dns_timeout":
            assert provider.provider == "UNKNOWN"
        if name == "fr_workspace":
            send_opportunity = opportunity_id
    assert send_opportunity is not None
    token_keys = ProgramAttributionKeyring(
        current_key_version="v1",
        keys={"v1": b"synthetic-token-secret-0123456789"},
    )
    conversion_at = NOW + dt.timedelta(hours=1)
    token = ProgramAttributionService(engine, token_keys, suppression_keys).issue(
        program_id=program_id,
        opportunity_id=send_opportunity,
        campaign_ref="milomail:corpus-preview",
        recipient_email="founder@cabinet.example",
        issued_at=conversion_at,
        expires_at=conversion_at + dt.timedelta(days=30),
    )
    webhook_key = b"synthetic-webhook-secret-0123456789"
    event = {
        "event_id": "corpus-event-1",
        "event_type": "audit_started",
        "attribution_token": token,
        "occurred_at": conversion_at.isoformat(),
    }
    raw = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(conversion_at.timestamp()))
    signature = hmac.new(
        webhook_key,
        b"milomail-conversion-v1\0" + stamp.encode() + b"\0" + raw,
        hashlib.sha256,
    ).hexdigest()
    ingress = MilomailConversionIngress(
        engine,
        acquisition,
        program_id=program_id,
        webhook_secret=webhook_key,
    )
    headers = {"X-MiloMail-Timestamp": stamp, "X-MiloMail-Signature": signature}
    assert ingress.ingest(raw, headers=headers, received_at=conversion_at) == ingress.ingest(
        raw,
        headers=headers,
        received_at=conversion_at,
    )
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_program_conversion_receipt)
            )
            == 1
        )
