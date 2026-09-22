"""B1 can replay private contact checkpoints without new Apollo calls."""

import datetime as dt

import sqlalchemy as sa
from test_milomail_policy import ready_config

from signals.acquisition_programs.b1_decisions import B1DecisionStore
from signals.compliance.milomail_rules import POLICY_VERSION_V2
from signals.persistence.schema import (
    acquisition_census_b1_decision,
    acquisition_census_b1_entry,
    acquisition_census_b1_ready_lead,
    acquisition_census_candidate,
)

NOW = dt.datetime(2026, 9, 22, 11, tzinfo=dt.UTC)
COMPANY_ID = "a" * 64


def test_completed_b1_contact_replay_is_versioned_and_idempotent() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    for table in (acquisition_census_candidate, acquisition_census_b1_entry,
                  acquisition_census_b1_decision, acquisition_census_b1_ready_lead):
        table.create(engine)
    person = {
        "provider_organization_id": "synthetic-org-1",
        "business_email": "founder@cabinet.example",
        "provider_email_status": "verified",
        "provider_observed_at": NOW.isoformat(),
        "source_fingerprint": "b" * 64,
        "title": "Founder",
        "first_name": "Synthetic",
    }
    result = {
        "classification": "GOOGLE_WORKSPACE_EMAIL",
        "decision": "HOLD",
        "verified_email": True,
        "email": person["business_email"],
        "person": person,
        "reason_codes": ["COMPANY_ACTIVE_STATUS_UNRESOLVED"],
        "official": {
            "match_confidence": "CONFIRMED_MATCH", "legal_status": "ACTIVE",
            "source_reference": "https://annuaire-entreprises.data.gouv.fr/entreprise/123456789",
            "siren": "123456789", "matcher_version": "synthetic-v2",
            "observed_at": NOW.isoformat(),
        },
    }
    snapshot = {
        "provider_organization_id": "synthetic-org-1",
        "primary_domain": "cabinet.example", "display_name": "Cabinet Synthétique",
        "country_code": "FR",
    }
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_candidate).values(
            candidate_id=COMPANY_ID, census_id="synthetic-census",
            provider_organization_id="synthetic-org-1", primary_domain="cabinet.example",
            snapshot=snapshot, sector="consulting", provider="GOOGLE_WORKSPACE",
            provider_confidence="CONFIRMED", provider_evidence={
                "mx_records": ["smtp.google.com"], "source": "DNS_MX",
                "observed_at": NOW.isoformat(),
                "expires_at": (NOW + dt.timedelta(days=1)).isoformat(),
                "detector_version": "synthetic-mx-v1",
            },
            contact_found=True, leader_identified=True, email_verified=True,
            status="PENDING", reason_codes=[], created_at=NOW, updated_at=NOW,
        ))
        connection.execute(sa.insert(acquisition_census_b1_entry).values(
            plan_id="synthetic-b1-plan", candidate_id=COMPANY_ID,
            selection_rank=1, stratum={"sector": "consulting", "size_band": "1-3"},
            status="COMPLETE", result=result, completed_at=NOW,
        ))
    config = ready_config().model_copy(update={"policy_version": POLICY_VERSION_V2})
    store = B1DecisionStore(engine)
    first = store.replay_b1(plan_id="synthetic-b1-plan", config=config, at=NOW,
                            is_suppressed=lambda _email: False)
    second = store.replay_b1(plan_id="synthetic-b1-plan", config=config, at=NOW,
                             is_suppressed=lambda _email: False)
    assert first == second
    assert first["replayed"] == 1 and first["apollo_calls"] == 0
    assert first["activity"] == {"OFFICIAL_ACTIVE": 1}
    assert "RECIPIENT_CAPACITY_UNCONFIRMED" not in first["reason_codes"]
    assert first["decisions"] == {"HOLD": 1}  # sending gates stay closed
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(
            acquisition_census_b1_decision)) == 1
        lead = connection.execute(sa.select(acquisition_census_b1_ready_lead)).mappings().one()
    assert lead["decision"] == "HOLD"
    assert lead["ruleset_version"] == POLICY_VERSION_V2
