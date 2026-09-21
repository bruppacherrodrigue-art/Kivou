"""Program metrics separate funnel milestones and never infer paid from a click."""

import datetime as dt

from test_milomail_attribution import prepared, signed
from test_milomail_policy import NOW

from signals.acquisition_programs.attribution import (
    MilomailConversionIngress,
    ProgramAttributionKeyring,
    ProgramAttributionService,
)
from signals.acquisition_programs.metrics import read_program_metrics
from signals.compliance.suppression import SuppressionIdentityKeyring


def test_program_metrics_group_wedge_and_keep_click_out_of_paid() -> None:
    engine, acquisition, program_id, opportunity_id = prepared()
    keys = ProgramAttributionKeyring(
        current_key_version="v1",
        keys={"v1": b"token-test-secret-0123456789"},
    )
    suppression_keys = SuppressionIdentityKeyring(
        current_key_version="v1",
        keys={"v1": b"suppression-test-secret"},
    )
    token = ProgramAttributionService(engine, keys, suppression_keys).issue(
        program_id=program_id,
        opportunity_id=opportunity_id,
        campaign_ref="milomail:metrics",
        recipient_email="founder@cabinet.example",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=30),
    )
    secret = b"webhook-test-secret-0123456789"
    ingress = MilomailConversionIngress(
        engine,
        acquisition,
        program_id=program_id,
        webhook_secret=secret,
    )
    body = {
        "event_id": "click-1",
        "event_type": "landing_clicked",
        "attribution_token": token,
        "occurred_at": NOW.isoformat(),
    }
    raw, headers = signed(body, secret, NOW)
    ingress.ingest(raw, headers=headers, received_at=NOW)
    metrics = read_program_metrics(engine, program_id=program_id, wedge_key="consulting")
    assert metrics.prospects_studied == 1
    assert metrics.decision_counts == {"SEND": 1}
    assert metrics.provider_counts == {"GOOGLE_WORKSPACE": 1}
    assert metrics.conversion_counts == {"landing_clicked": 1}
    assert metrics.paid_count == 0
    assert metrics.mrr_chf is None
    assert metrics.cost_per_studied_chf is None
    assert (
        read_program_metrics(
            engine, program_id=program_id, wedge_key="recruiting_agency"
        ).prospects_studied
        == 0
    )
