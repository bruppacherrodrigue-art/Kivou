from __future__ import annotations

import datetime as dt

from signals.companies.sirene import SireneCompany
from signals.supplier_discovery.contracts import SupplierSearchProfile
from signals.supplier_discovery.sirene_provider import SireneOrganizationSearchProvider


class FakeSearch:
    def __init__(self) -> None:
        self.calls = []

    def find(self, criteria):
        self.calls.append(criteria)
        return (
            SireneCompany(
                legal_name=f"Entreprise {criteria.naf_codes[0]}",
                siren="123456789",
                siret="12345678900010",
                city="Lyon",
                department="69",
                employees=20,
                naf_code=criteria.naf_codes[0],
                observed_at=dt.datetime(2026, 9, 9, tzinfo=dt.UTC),
                naf_label=(
                    "Fabrication de béton prêt à l'emploi"
                    if criteria.naf_codes[0] == "23.63Z"
                    else "Travaux de coffrage"
                ),
            ),
        )


def test_sirene_provider_searches_each_family_and_never_apollo_organizations() -> None:
    fake = FakeSearch()
    provider = SireneOrganizationSearchProvider(fake)
    profile = SupplierSearchProfile(
        signal_ref="procurement-opportunity:opp-1",
        representative_award_key="award-1",
        need_categories=("materials_or_components",),
        cpv_codes=("45262300",),
        keyword_tags=("béton",),
        sirene_naf_codes=("23.63Z", "43.99C"),
        sirene_departments=("69",),
        supplier_family_keys=("ready_mix_concrete", "formwork"),
        max_pages=1,
        per_page=25,
        candidate_cap=50,
        search_too_broad_threshold=200,
        profile_fingerprint="0" * 64,
    )

    page = provider.search_page(profile, page=1, observed_at=dt.datetime(2026, 9, 9, tzinfo=dt.UTC))

    assert [call.naf_codes for call in fake.calls] == [("23.63Z",), ("43.99C",)]
    assert len(page.candidates) == 2
    assert {candidate.department for candidate in page.candidates} == {"69"}
    assert {candidate.industry.split(":", 1)[0] for candidate in page.candidates} == {
        "ready_mix_concrete",
        "formwork",
    }
