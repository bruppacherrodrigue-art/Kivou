from __future__ import annotations

import datetime as dt

from signals.companies.contracts import MAX_OFFICIAL_IDENTIFIERS
from signals.companies.identity import (
    IdentityMethod,
    company_key,
    official_company_identity,
)
from signals.feed.query import DisplayIdentity

OBSERVED_AT = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)


def _parties(
    *,
    name: str = "Entreprise SA",
    country: str | None = "CH",
    identifier: tuple[str, str] | None = ("CHE-UID", "CHE-123.456.789"),
    website: str | None = "https://entreprise.example/about",
) -> list[dict[str, object]]:
    identifiers = [] if identifier is None else [{"scheme": identifier[0], "value": identifier[1]}]
    return [
        {
            "members": [
                {
                    "organization": {
                        "legal_name": name,
                        "country": country,
                        "address": "Rue de la Gare 1, Lausanne",
                        "identifiers": identifiers,
                        "website": website,
                    }
                }
            ]
        }
    ]


def _display(
    *,
    name: str = "Entreprise SA",
    country: str | None = "CH",
    identifier: tuple[str, str] | None = ("CHE-UID", "CHE-123.456.789"),
) -> DisplayIdentity:
    return DisplayIdentity(
        name=name,
        country=country,
        identifier_scheme=identifier[0] if identifier else None,
        identifier_value=identifier[1] if identifier else None,
        from_award_key="award_1",
    )


def test_exact_identifier_has_priority_and_is_deterministic() -> None:
    first = official_company_identity(
        awardee_parties=_parties(),
        display=_display(),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )
    second = official_company_identity(
        awardee_parties=_parties(
            name="  ENTREPRISE   SA ",
            identifier=(" che-uid ", " CHE-123.456.789 "),
        ),
        display=_display(),
        opportunity_key="opp_2",
        observed_at=OBSERVED_AT,
    )

    assert first is not None
    assert second is not None
    assert first.identity_method is IdentityMethod.OFFICIAL_IDENTIFIER
    assert first.identity_fingerprint == second.identity_fingerprint
    assert first.validation_evidence == {
        "country": "CH",
        "identifier_scheme": "che-uid",
        "identifier_value": "che-123.456.789",
    }


def test_https_domain_is_used_only_without_official_identifier() -> None:
    identity = official_company_identity(
        awardee_parties=_parties(identifier=None),
        display=_display(identifier=None),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )

    assert identity is not None
    assert identity.identity_method is IdentityMethod.OFFICIAL_DOMAIN
    assert identity.validation_evidence == {
        "country": "CH",
        "domain": "entreprise.example",
    }
    assert identity.official.website_url == "https://entreprise.example/about"


def test_unsafe_website_falls_back_to_opportunity_scope() -> None:
    identity = official_company_identity(
        awardee_parties=_parties(identifier=None, website="javascript:alert(1)"),
        display=_display(identifier=None),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )

    assert identity is not None
    assert identity.identity_method is IdentityMethod.OPPORTUNITY
    assert identity.validation_evidence == {"opportunity_key": "opp_1"}
    assert identity.official.website_url is None


def test_name_only_homonyms_never_merge_across_opportunities() -> None:
    first = official_company_identity(
        awardee_parties=_parties(identifier=None, website=None),
        display=_display(identifier=None),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )
    second = official_company_identity(
        awardee_parties=_parties(identifier=None, website=None),
        display=_display(identifier=None),
        opportunity_key="opp_2",
        observed_at=OBSERVED_AT,
    )

    assert first is not None
    assert second is not None
    assert first.identity_fingerprint != second.identity_fingerprint


def test_identifier_without_country_falls_back_to_opportunity_scope() -> None:
    first = official_company_identity(
        awardee_parties=_parties(name="Alpha SA", country=None, website=None),
        display=_display(name="Alpha SA", country=None),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )
    second = official_company_identity(
        awardee_parties=_parties(name="Beta SA", country=None, website=None),
        display=_display(name="Beta SA", country=None),
        opportunity_key="opp_2",
        observed_at=OBSERVED_AT,
    )

    assert first is not None
    assert second is not None
    assert first.identity_method is IdentityMethod.OPPORTUNITY
    assert second.identity_method is IdentityMethod.OPPORTUNITY
    assert first.identity_fingerprint != second.identity_fingerprint


def test_untrusted_identifier_collection_is_bounded_before_contract_validation() -> None:
    parties = _parties()
    organization = parties[0]["members"][0]["organization"]
    organization["identifiers"] = [
        {"scheme": "REG", "value": f"identifier-{index}"}
        for index in range(MAX_OFFICIAL_IDENTIFIERS + 1)
    ]
    display = _display(identifier=("REG", "identifier-0"))

    identity = official_company_identity(
        awardee_parties=parties,
        display=display,
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )

    assert identity is not None
    assert len(identity.official.identifiers) == MAX_OFFICIAL_IDENTIFIERS


def test_unrepresentable_public_identity_omits_the_optional_profile() -> None:
    name = "A" * 513

    identity = official_company_identity(
        awardee_parties=_parties(name=name),
        display=_display(name=name),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )

    assert identity is None


def test_display_identity_must_match_an_exact_published_organization() -> None:
    identity = official_company_identity(
        awardee_parties=_parties(name="Other Company SA", identifier=None),
        display=_display(name="Entreprise SA", identifier=None),
        opportunity_key="opp_1",
        observed_at=OBSERVED_AT,
    )

    assert identity is None


def test_opaque_company_keys_are_random_and_contain_no_source_facts() -> None:
    first = company_key()
    second = company_key()

    assert first.startswith("cmp_")
    assert second.startswith("cmp_")
    assert first != second
    assert "entreprise" not in first
    assert "123.456.789" not in first
    assert len(first) <= 64
