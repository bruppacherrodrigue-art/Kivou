from __future__ import annotations

import pytest

from signals.compliance.contracts import ComplianceJurisdiction
from signals.compliance.jurisdiction import (
    EU_MEMBER_CODES,
    JURISDICTION_VERSION,
    resolve_jurisdiction,
)


@pytest.mark.parametrize(
    ("supplier", "provider", "jurisdiction", "country"),
    (
        ("CH", "Switzerland", ComplianceJurisdiction.CH, "CH"),
        ("FR", "France", ComplianceJurisdiction.FR, "FR"),
        ("DE", "Germany", ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED, "DE"),
        ("BE", "Belgium", ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED, "BE"),
        ("LU", "Luxembourg", ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED, "LU"),
        ("US", "United States", ComplianceJurisdiction.OUT_OF_SCOPE, "US"),
        (None, "France", ComplianceJurisdiction.FR, "FR"),
        ("CH", None, ComplianceJurisdiction.CH, "CH"),
    ),
)
def test_jurisdiction_resolution_uses_only_durable_country_facts(
    supplier, provider, jurisdiction, country
) -> None:
    result = resolve_jurisdiction(
        supplier_country_code=supplier,
        provider_country=provider,
        supplier_ref="supplier-1",
        profile_ref="company-profile:opp-1",
    )

    assert result.jurisdiction is jurisdiction
    assert result.country_code == country
    assert result.resolver_version == JURISDICTION_VERSION


@pytest.mark.parametrize(
    ("supplier", "provider"),
    (("CH", "France"), (None, None), (None, "not a canonical country")),
)
def test_conflicting_or_missing_country_is_resolvable_unknown(supplier, provider) -> None:
    result = resolve_jurisdiction(
        supplier_country_code=supplier,
        provider_country=provider,
        supplier_ref="supplier-1",
        profile_ref="company-profile:opp-1",
    )

    assert result.jurisdiction is ComplianceJurisdiction.UNRESOLVED
    assert result.country_code is None
    assert result.resolvable is True


def test_language_or_email_tld_cannot_be_passed_as_jurisdiction_inputs() -> None:
    with pytest.raises(TypeError):
        resolve_jurisdiction(
            supplier_country_code=None,
            provider_country=None,
            supplier_ref="supplier-1",
            profile_ref="company-profile:opp-1",
            language="fr",
        )


@pytest.mark.parametrize("country", sorted(EU_MEMBER_CODES - {"FR"}))
def test_every_current_non_fr_eu_member_is_explicitly_unconfigured(country: str) -> None:
    result = resolve_jurisdiction(
        supplier_country_code=country,
        provider_country=None,
        supplier_ref="supplier-1",
        profile_ref="company-profile:opp-1",
    )

    assert result.jurisdiction is ComplianceJurisdiction.EU_MEMBER_STATE_UNCONFIGURED
    assert result.country_code == country
