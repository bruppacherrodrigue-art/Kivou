from __future__ import annotations

import datetime as dt
import time

import pytest

from signals.acquisition.contracts import Decision
from signals.company_research.contracts import CompanySizeBand, ResearchCompleteness
from signals.decision_engine.evaluator import evaluate_decision
from signals.decision_engine.input import (
    build_acquisition_decision_input,
    build_public_decision_context,
)
from signals.decision_engine.policy import DECISION_POLICY_V1
from signals.supplier_discovery.contracts import SupplierIdentityStatus

AS_OF = dt.date(2026, 8, 20)


def _input(
    *,
    age_days: int | None = 10,
    current_identity=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
    profile_identity=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
    completeness=ResearchCompleteness.COMPLETE,
    size_band=CompanySizeBand.SMB,
    role_tier=1,
    basis="award",
):
    if age_days is None:
        dates = {
            "award_date": None,
            "contract_notification_date": None,
            "publication_date": None,
        }
    else:
        selected = AS_OF - dt.timedelta(days=age_days)
        dates = {
            "award_date": selected if basis == "award" else None,
            "contract_notification_date": selected if basis == "notification" else None,
            "publication_date": selected if basis == "publication" else AS_OF,
        }
    context = build_public_decision_context(
        opportunity_key="public-opp-1",
        representative_award_key="award-1",
        source_event_key="simap:notice-1:",
        public_evidence_refs=(
            "source-event:simap:notice-1:",
            "contract-award:award-1",
        ),
        **dates,
    )
    return build_acquisition_decision_input(
        acquisition_opportunity_id="acq-1",
        signal_ref="procurement-opportunity:public-opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        company_prebuild_version="acquisition-prospect-prebuild-v1",
        company_prebuild_fingerprint="a" * 64,
        size_band_version="company-size-v1",
        profile_supplier_identity_status=profile_identity,
        current_supplier_identity_status=current_identity,
        profile_contact_role_profile_version="decision-maker-search-v1",
        profile_contact_role_tier=1,
        current_contact_role_profile_version="decision-maker-search-v1",
        current_contact_role_tier=role_tier,
        current_contact_verification_state="PROVIDER_VERIFIED",
        current_contact_verification_provider="apollo",
        current_contact_provider_email_status="verified",
        research_completeness=completeness,
        research_gaps=(),
        size_band=size_band,
        public_context=context,
        as_of_date=AS_OF,
        policy_config=DECISION_POLICY_V1,
    )


@pytest.mark.parametrize(
    ("age_days", "expected"),
    ((59, Decision.SEND), (60, Decision.SEND), (61, Decision.NO_SEND)),
)
def test_frozen_sixty_day_boundary_is_inclusive(age_days, expected) -> None:
    proposal = evaluate_decision(_input(age_days=age_days), DECISION_POLICY_V1)

    assert proposal.proposed_decision is expected


def test_supplier_snapshot_mismatch_is_first_review_rule() -> None:
    proposal = evaluate_decision(
        _input(
            age_days=61,
            profile_identity=SupplierIdentityStatus.DOMAIN_CONFLICT,
            current_identity=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        ),
        DECISION_POLICY_V1,
    )

    assert proposal.proposed_decision is Decision.REVIEW
    assert proposal.reason_codes == ("SUPPLIER_IDENTITY_CHANGED_SINCE_RESEARCH",)


def test_domain_conflict_precedes_staleness() -> None:
    proposal = evaluate_decision(
        _input(
            age_days=61,
            current_identity=SupplierIdentityStatus.DOMAIN_CONFLICT,
            profile_identity=SupplierIdentityStatus.DOMAIN_CONFLICT,
        ),
        DECISION_POLICY_V1,
    )

    assert proposal.proposed_decision is Decision.REVIEW
    assert proposal.reason_codes == ("SUPPLIER_DOMAIN_CONFLICT",)


def test_unresolved_and_future_timing_route_to_review() -> None:
    unresolved = evaluate_decision(_input(age_days=None), DECISION_POLICY_V1)
    future = evaluate_decision(_input(age_days=-1), DECISION_POLICY_V1)

    assert unresolved.proposed_decision is Decision.REVIEW
    assert unresolved.reason_codes == ("RECENCY_UNRESOLVED",)
    assert future.proposed_decision is Decision.REVIEW
    assert future.reason_codes == ("PUBLIC_TIMING_INCONSISTENT",)


@pytest.mark.parametrize(
    "award_date",
    (
        dt.date(2000, 1, 1),
        dt.date(1970, 1, 1),
        dt.date(2002, 8, 17),
    ),
)
def test_implausible_award_clock_routes_to_review_without_publication_fallback(
    award_date,
) -> None:
    decision_input = _input(age_days=(AS_OF - award_date).days)

    proposal = evaluate_decision(decision_input, DECISION_POLICY_V1)

    assert decision_input.recency_basis.value == "AWARD_DATE"
    assert decision_input.recency_date == award_date
    assert decision_input.public_timing_inconsistent is True
    assert proposal.proposed_decision is Decision.REVIEW
    assert proposal.reason_codes == ("PUBLIC_TIMING_INCONSISTENT",)


@pytest.mark.parametrize("basis", ("notification", "publication"))
def test_send_preserves_explicit_fallback_reason(basis) -> None:
    proposal = evaluate_decision(_input(age_days=10, basis=basis), DECISION_POLICY_V1)

    expected = (
        "RECENCY_NOTIFICATION_FALLBACK"
        if basis == "notification"
        else "RECENCY_PUBLICATION_FALLBACK"
    )
    assert proposal.proposed_decision is Decision.SEND
    assert proposal.reason_codes[-1] == expected


def test_limited_size_and_tier_four_are_context_only() -> None:
    proposal = evaluate_decision(
        _input(
            completeness=ResearchCompleteness.LIMITED,
            size_band=CompanySizeBand.MICRO,
            role_tier=4,
        ),
        DECISION_POLICY_V1,
    )

    assert proposal.proposed_decision is Decision.SEND


@pytest.mark.parametrize(
    ("decision", "next_action"),
    (
        (Decision.SEND, "prepare_campaign"),
        (Decision.REVIEW, "request_human_review"),
        (Decision.NO_SEND, None),
    ),
)
def test_decision_next_action_contract(decision, next_action) -> None:
    by_decision = {
        Decision.SEND: _input(age_days=10),
        Decision.REVIEW: _input(age_days=None),
        Decision.NO_SEND: _input(age_days=61),
    }
    proposal = evaluate_decision(by_decision[decision], DECISION_POLICY_V1)

    assert proposal.proposed_decision is decision
    assert proposal.next_action == next_action
    assert proposal.next_review_at is None
    assert proposal.confidence is None
    assert 1 <= len(proposal.reason_codes) <= 8
    assert 1 <= len(proposal.evidence_refs) <= 16


def test_v1_never_emits_hold_or_enrich() -> None:
    decisions = {
        evaluate_decision(_input(age_days=age), DECISION_POLICY_V1).proposed_decision
        for age in (None, -1, 0, 59, 60, 61, 10_000)
    }

    assert decisions <= {Decision.SEND, Decision.REVIEW, Decision.NO_SEND}
    assert Decision.HOLD not in decisions
    assert Decision.ENRICH not in decisions


def test_proposal_fingerprint_is_deterministic_and_output_sensitive() -> None:
    send = evaluate_decision(_input(age_days=60), DECISION_POLICY_V1)
    replay = evaluate_decision(_input(age_days=60), DECISION_POLICY_V1)
    no_send = evaluate_decision(_input(age_days=61), DECISION_POLICY_V1)

    assert send.proposal_fingerprint == replay.proposal_fingerprint
    assert send.proposal_fingerprint != no_send.proposal_fingerprint
    assert send.proposal_fingerprint != send.decision_input_fingerprint


def test_one_thousand_pure_decisions_are_measured_without_an_sla() -> None:
    started = time.perf_counter()
    proposals = [
        evaluate_decision(_input(age_days=index % 90), DECISION_POLICY_V1)
        for index in range(1_000)
    ]
    elapsed = time.perf_counter() - started

    assert len(proposals) == 1_000
    assert {proposal.proposed_decision for proposal in proposals} == {
        Decision.SEND,
        Decision.NO_SEND,
    }
    print(f"decision_engine_1000_elapsed_seconds={elapsed:.6f}")
