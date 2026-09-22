"""Versioned French company activity proof without provider calls."""

import datetime as dt

import pytest
from test_milomail_policy import NOW, ready_input

from signals.acquisition_programs.activity_evidence import (
    ActivityEvidenceInput,
    LeaderAffiliationProof,
    OfficialActivityProof,
    WebsiteIdentityProof,
    evaluate_activity_evidence,
)
from signals.acquisition_programs.qualification import RecipientCapacity
from signals.compliance.milomail_rules import (
    POLICY_VERSION_V2,
    evaluate_b0_activity_replay,
    evaluate_milomail,
)


def _v2(**changes):
    value = ready_input()
    program = value.program.model_copy(update={"policy_version": POLICY_VERSION_V2})
    return value.model_copy(update={"program": program, "company_active": None, **changes})


def _official(status: str = "ACTIVE", *, observed_at: dt.datetime = NOW):
    return OfficialActivityProof(
        status=status,
        source_type="ANNUAIRE_ENTREPRISES_SIRENE",
        source_url="https://annuaire-entreprises.data.gouv.fr/entreprise/123456789",
        evidence_id="sirene:123456789:v2",
        observed_at=observed_at,
        expires_at=observed_at + dt.timedelta(days=7),
    )


def _leader(*, email_domain: str = "cabinet.example", evidence_id: str = "apollo:leader"):
    return LeaderAffiliationProof(
        source_type="APOLLO_VERIFIED_BUSINESS_CONTACT",
        evidence_id=evidence_id,
        observed_at=NOW,
        expires_at=NOW + dt.timedelta(days=90),
        company_domain="cabinet.example",
        email_domain=email_domain,
        role="founder",
        email_verified=True,
    )


def _website(*, accessible: bool = True, evidence_id: str = "site:identity"):
    return WebsiteIdentityProof(
        source_url="https://cabinet.example/mentions-legales",
        evidence_id=evidence_id,
        observed_at=NOW,
        expires_at=NOW + dt.timedelta(days=7),
        company_domain="cabinet.example",
        accessible=accessible,
        identity_matches=True,
    )


def _operational(**changes):
    values = {
        "company_domain": "cabinet.example",
        "leader": _leader(),
        "website": _website(),
        **changes,
    }
    return ActivityEvidenceInput(**values)


def _decision(activity: ActivityEvidenceInput, **changes):
    value = ready_input()
    ids = (*value.evidence_ids, "sirene:123456789:v2", "apollo:leader", "site:identity")
    return evaluate_milomail(_v2(activity_evidence=activity, evidence_ids=ids, **changes))


def test_v1_remains_frozen_without_new_activity_evidence() -> None:
    decision = evaluate_milomail(ready_input())
    assert decision.decision == "SEND"
    assert decision.policy_version == "milomail-fr-b2b-v1"


def test_v2_accepts_current_official_active_proof() -> None:
    decision = _decision(
        ActivityEvidenceInput(company_domain="cabinet.example", official=_official())
    )
    assert decision.decision == "SEND"
    assert decision.policy_version == POLICY_VERSION_V2
    assert "sirene:123456789:v2" in decision.evidence_ids


def test_v2_official_ceased_is_no_send_even_with_operational_signals() -> None:
    activity = _operational(official=_official("CEASED"))
    decision = _decision(activity)
    assert decision.decision == "NO_SEND"
    assert "OFFICIAL_CEASED" in decision.reason_codes


def test_v2_dated_official_ceased_remains_no_send_after_proof_ttl() -> None:
    old = NOW - dt.timedelta(days=8)
    decision = _decision(_operational(official=_official("CEASED", observed_at=old)))
    assert decision.decision == "NO_SEND"
    assert "OFFICIAL_CEASED" in decision.reason_codes


def test_v2_independent_current_operational_composite_can_send() -> None:
    decision = _decision(_operational())
    assert decision.decision == "SEND"
    assert {"apollo:leader", "site:identity"}.issubset(decision.evidence_ids)


@pytest.mark.parametrize(
    "official",
    [
        _official("UNKNOWN"),
        _official("ACTIVE", observed_at=NOW - dt.timedelta(days=8)),
    ],
)
def test_v2_operational_composite_resolves_unknown_or_stale_official_status(
    official: OfficialActivityProof,
) -> None:
    decision = _decision(_operational(official=official))
    assert decision.decision == "SEND"
    assert "OPERATIONAL_ACTIVITY_CORROBORATED" in decision.reason_codes


@pytest.mark.parametrize(
    "activity,reason",
    [
        (ActivityEvidenceInput(company_domain="cabinet.example"), "LEADER_AFFILIATION_MISSING"),
        (_operational(contradictions=("contradiction:ceased-page",)), "ACTIVITY_CONTRADICTION"),
        (_operational(website=_website(accessible=False)), "WEBSITE_IDENTITY_UNCONFIRMED"),
        (_operational(leader=_leader(email_domain="other.example")), "LEADER_DOMAIN_MISMATCH"),
        (
            _operational(leader=_leader(evidence_id="site:identity")),
            "ACTIVITY_SOURCES_NOT_INDEPENDENT",
        ),
    ],
)
def test_v2_unknown_activity_holds(activity: ActivityEvidenceInput, reason: str) -> None:
    decision = _decision(activity)
    assert decision.decision == "HOLD"
    assert reason in decision.reason_codes


def test_v2_expired_official_and_operational_proofs_hold() -> None:
    old = NOW - dt.timedelta(days=8)
    activity = ActivityEvidenceInput(
        company_domain="cabinet.example", official=_official(observed_at=old)
    )
    decision = _decision(activity)
    assert decision.decision == "HOLD"
    assert "OFFICIAL_ACTIVITY_EVIDENCE_EXPIRED" in decision.reason_codes


def test_v2_missing_audit_reference_holds() -> None:
    decision = evaluate_milomail(
        _v2(
            activity_evidence=_operational(),
            evidence_ids=ready_input().evidence_ids,
        )
    )
    assert decision.decision == "HOLD"
    assert "ACTIVITY_EVIDENCE_NOT_RECORDED" in decision.reason_codes


def test_v2_does_not_infer_sender_or_notice_readiness_from_activity() -> None:
    decision = _decision(_operational(), opt_out_ready=False)
    assert decision.decision == "HOLD"
    assert "OPT_OUT_MISSING" in decision.reason_codes


def test_evidence_evaluator_is_deterministic_for_same_dated_inputs() -> None:
    activity = _operational()
    provider = ready_input().provider
    first = evaluate_activity_evidence(
        activity,
        provider=provider,
        allowed_roles=ready_input().program.target_roles,
        at=NOW,
    )
    second = evaluate_activity_evidence(
        activity,
        provider=provider,
        allowed_roles=ready_input().program.target_roles,
        at=NOW,
    )
    assert first == second
    assert first.status == "OPERATIONALLY_ACTIVE"


def _b0_result(*, status: str = "ACTIVE", legal_page: bool = True) -> dict:
    return {
        "classification": "GOOGLE_WORKSPACE_EMAIL",
        "email": "founder@cabinet.example",
        "person": {
            "provider_organization_id": "org-1",
            "business_email": "founder@cabinet.example",
            "provider_email_status": "verified",
            "provider_observed_at": NOW.isoformat(),
            "source_fingerprint": "person-source-hash",
        },
        "official": {
            "match_confidence": "CONFIRMED_MATCH",
            "legal_status": status,
            "source_reference": "https://annuaire-entreprises.data.gouv.fr/entreprise/123456789",
            "siren": "123456789",
            "matcher_version": "milomail-fr-company-v2",
            "observed_at": NOW.isoformat(),
            "legal_page_source_url": (
                "https://cabinet.example/mentions-legales" if legal_page else None
            ),
            "legal_page_observed_at": NOW.isoformat() if legal_page else None,
        },
    }


def _candidate() -> dict:
    return {
        "provider_organization_id": "org-1",
        "primary_domain": "cabinet.example",
        "display_name": "Cabinet Exemple",
    }


def test_b0_replay_returns_versioned_official_activity_and_closed_policy() -> None:
    replay = evaluate_b0_activity_replay(
        _b0_result(),
        _candidate(),
        policy_input=_v2(opt_out_ready=False),
    )
    assert replay.activity.status == "OFFICIAL_ACTIVE"
    assert replay.policy.policy_version == POLICY_VERSION_V2
    assert replay.policy.decision == "HOLD"
    assert "OPT_OUT_MISSING" in replay.policy.reason_codes


def test_b0_replay_can_use_operational_composite_when_official_status_unknown() -> None:
    replay = evaluate_b0_activity_replay(
        _b0_result(status="UNKNOWN"),
        _candidate(),
        policy_input=_v2(),
    )
    assert replay.activity.status == "OPERATIONALLY_ACTIVE"
    assert replay.policy.decision == "SEND"
    assert "apollo-person:person-source-hash" in replay.policy.evidence_ids


def test_b0_replay_without_validated_website_holds() -> None:
    replay = evaluate_b0_activity_replay(
        _b0_result(status="UNKNOWN", legal_page=False),
        _candidate(),
        policy_input=_v2(),
    )
    assert replay.activity.status == "UNKNOWN"
    assert replay.policy.decision == "HOLD"
    assert "WEBSITE_IDENTITY_MISSING" in replay.policy.reason_codes


def test_b0_replay_accepts_later_dated_public_website_proof() -> None:
    replay = evaluate_b0_activity_replay(
        _b0_result(status="UNKNOWN", legal_page=False),
        _candidate(),
        policy_input=_v2(),
        website_proof=_website(),
    )
    assert replay.activity.status == "OPERATIONALLY_ACTIVE"
    assert replay.policy.decision == "SEND"
    assert "site:identity" in replay.policy.evidence_ids


def test_b0_replay_rechecks_professional_capacity_after_operational_proof() -> None:
    unconfirmed = ready_input().capacity.model_copy(
        update={"capacity": RecipientCapacity.UNKNOWN, "reasons": ("COMPANY_ACTIVE_UNKNOWN",)}
    )
    replay = evaluate_b0_activity_replay(
        _b0_result(status="UNKNOWN", legal_page=False),
        _candidate(),
        policy_input=_v2(capacity=unconfirmed),
        website_proof=_website(),
    )
    assert replay.activity.status == "OPERATIONALLY_ACTIVE"
    assert replay.policy.decision == "SEND"


def test_b0_replay_rejects_website_proof_for_another_domain() -> None:
    foreign = _website().model_copy(update={"company_domain": "other.example"})
    replay = evaluate_b0_activity_replay(
        _b0_result(status="UNKNOWN", legal_page=False),
        _candidate(),
        policy_input=_v2(),
        website_proof=foreign,
    )
    assert replay.activity.status == "UNKNOWN"
    assert replay.policy.decision == "HOLD"
    assert "WEBSITE_IDENTITY_UNCONFIRMED" in replay.policy.reason_codes


def test_b0_replay_official_ceased_blocks_operational_composite() -> None:
    replay = evaluate_b0_activity_replay(
        _b0_result(status="CEASED"),
        _candidate(),
        policy_input=_v2(),
    )
    assert replay.activity.status == "OFFICIAL_CEASED"
    assert replay.policy.decision == "NO_SEND"


def test_b0_replay_preserves_known_suppression() -> None:
    result = _b0_result()
    result["classification"] = "SUPPRESSED"
    replay = evaluate_b0_activity_replay(result, _candidate(), policy_input=_v2())
    assert replay.policy.decision == "NO_SEND"
    assert "SUPPRESSION_MATCH" in replay.policy.reason_codes


def test_b0_replay_malformed_ceased_proof_cannot_be_overridden_by_operational_signals() -> None:
    result = _b0_result(status="CEASED")
    result["official"]["source_reference"] = None
    replay = evaluate_b0_activity_replay(result, _candidate(), policy_input=_v2())
    assert replay.activity.status == "UNKNOWN"
    assert replay.policy.decision == "HOLD"
    assert "ACTIVITY_CONTRADICTION" in replay.policy.reason_codes


def test_b0_replay_rejects_v1_input() -> None:
    with pytest.raises(ValueError, match="v2"):
        evaluate_b0_activity_replay(
            _b0_result(),
            _candidate(),
            policy_input=ready_input(),
        )
