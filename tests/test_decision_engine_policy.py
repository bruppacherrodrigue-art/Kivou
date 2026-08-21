from signals.decision_engine.policy import DECISION_POLICY_V1
from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope
from signals.recency import IMPLAUSIBLE_AWARD_AGE_DAYS


def test_v1_reuses_the_authoritative_public_date_plausibility_guard() -> None:
    assert (
        DECISION_POLICY_V1.max_plausible_public_age_days
        == IMPLAUSIBLE_AWARD_AGE_DAYS
        == 3650
    )


def test_evaluate_opportunity_policy_metadata_is_internal_and_proposal_bound() -> None:
    policy = COMMAND_POLICIES["evaluate_opportunity"]

    assert policy.risk_class is RiskClass.PREPARATORY
    assert policy.target_scope is TargetScope.OPPORTUNITY
    assert policy.required_evidence == (
        "PUBLIC_OPPORTUNITY",
        "PUBLIC_EVIDENCE",
        "ACQUISITION_PROSPECT_PREBUILD",
        "VERIFIED_CONTACT",
        "DECISION_INPUT",
    )
    assert policy.uses_budget is False
    assert policy.uses_volume is False
    assert policy.uses_provider_quota is False
    assert policy.uses_send_controls is False
    assert policy.requires_control_plane is False
    assert policy.requires_compliance is False
    assert "RECENT_SIGNAL" not in policy.required_evidence
