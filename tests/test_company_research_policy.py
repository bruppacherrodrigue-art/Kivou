from signals.policy.registry import COMMAND_POLICIES, RiskClass, TargetScope


def test_enrich_company_has_company_research_provider_controls() -> None:
    policy = COMMAND_POLICIES["enrich_company"]

    assert policy.risk_class is RiskClass.PREPARATORY
    assert policy.target_scope is TargetScope.OPPORTUNITY
    assert policy.required_evidence == (
        "SUPPLIER",
        "VERIFIED_CONTACT",
        "COMPANY_RESEARCH_PROFILE",
    )
    assert policy.uses_budget is True
    assert policy.uses_provider_quota is True
    assert policy.requires_control_plane is True
    assert policy.uses_send_controls is False
    assert policy.requires_compliance is False
