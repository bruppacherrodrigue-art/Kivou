"""Deterministic, non-network Apollo substitutes for staging shadow runs."""

from __future__ import annotations

import datetime as dt
import hashlib

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_connectivity.contracts import ApolloIdentityEvidence
from signals.companies.sirene import SireneCompany
from signals.company_research.contracts import ApolloOrganizationObservation
from signals.contact_discovery.contracts import (
    ApolloEnrichedPerson,
    PeopleSearchCandidate,
    PeopleSearchPage,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierSearchPage


class FakeSireneCompanySearch:
    """Deterministic SIRENE-shaped identities for offline staging mechanics."""

    def find(self, criteria):
        companies = []
        for index, naf_code in enumerate(criteria.naf_codes[:5]):
            material = f"{naf_code}:{','.join(criteria.departments)}:{index}"
            siren = str(int(_fingerprint(material)[:14], 16))[:9].ljust(9, "0")
            companies.append(
                SireneCompany(
                    legal_name=f"Entreprise test {naf_code} {index + 1}",
                    siren=siren,
                    siret=f"{siren}00010",
                    city="Lyon",
                    department=criteria.departments[0],
                    employees=25,
                    naf_code=naf_code,
                    observed_at=dt.datetime.now(dt.UTC),
                    naf_label=(
                        "Béton prêt à l'emploi armatures ferraillage gros œuvre maçonnerie "
                        "coffrage échafaudage étanchéité charpente couverture zinguerie "
                        "isolation menuiserie plomberie électricité chauffage ventilation "
                        "travaux routiers enrobé signalisation terrassement démolition déchets"
                    ),
                )
            )
        return tuple(companies[: criteria.limit])


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeApolloOrganizationSearch:
    def search_page(self, profile, *, page: int, observed_at: dt.datetime) -> SupplierSearchPage:
        key = profile.signal_ref.rsplit(":", 1)[-1]
        org_id = f"fake-org-{_fingerprint(key)[:20]}"
        name = f"Entreprise {key[:12]}"
        candidate = ApolloOrganizationCandidate(
            provider_organization_id=org_id,
            display_name=name,
            normalized_name=name.casefold(),
            primary_domain=f"{org_id}.example.test",
            website_url=f"https://{org_id}.example.test",
            country_code="FR",
            location=profile.organization_locations[0]
            if profile.organization_locations
            else "France",
            industry="Building materials",
            provider_observed_at=observed_at,
            source_fingerprint=_fingerprint(org_id),
        )
        return SupplierSearchPage(
            page=page,
            per_page=profile.per_page,
            total_entries=1,
            total_pages=1,
            candidates=(candidate,),
            rejections=(),
        )


class FakeApolloContactDiscovery:
    def search_people(self, profile, *, observed_at: dt.datetime) -> PeopleSearchPage:
        person_id = f"fake-person-{profile.provider_organization_id}"
        return PeopleSearchPage(
            total_entries=1,
            candidates=(
                PeopleSearchCandidate(
                    provider_person_id=person_id,
                    first_name="Camille",
                    last_name_obfuscated="D.",
                    title="Directeur commercial",
                    provider_position=0,
                    organization_name="Entreprise staging",
                    provider_refreshed_at=observed_at,
                    has_email=True,
                ),
            ),
            rejections=(),
            observed_at=observed_at,
        )

    def enrich_person(self, provider_person_id: str, *, observed_at: dt.datetime):
        organization_id = provider_person_id.removeprefix("fake-person-")
        return ApolloEnrichedPerson(
            provider_person_id=provider_person_id,
            provider_organization_id=organization_id,
            first_name="Camille",
            last_name="Dupont",
            display_name="Camille Dupont",
            title="Directeur commercial",
            business_email=f"camille.{organization_id[:8]}@example.test",
            provider_email_status="verified",
            provider_observed_at=observed_at,
            source_fingerprint=_fingerprint(provider_person_id),
        )


class FakeApolloCompanyResearch:
    def fetch_organization(self, profile):
        org = (
            f"fake-org-{_fingerprint(profile.siren)[:20]}"
            if profile.siren
            else profile.provider_organization_id
        )
        return ApolloOrganizationObservation(
            provider_organization_id=org,
            provider_company_name="Entreprise staging",
            provider_primary_domain=f"{org}.example.test",
            provider_website_url=f"https://{org}.example.test",
            provider_country="France",
            provider_industry="Building materials",
            provider_employee_count=25,
            provider_short_description="Entreprise de bâtiment",
            provider_keywords=("bardage", "couverture"),
            provider_observed_at=dt.datetime.now(dt.UTC),
            provider_source_fingerprint=_fingerprint(org),
        )


class FakeApolloIdentity:
    def check(self) -> ApolloIdentityEvidence:
        return ApolloIdentityEvidence(acting_profile_fingerprint=_fingerprint("fake-apollo"))


def build_fake_apollo_components() -> ApolloComponents:
    return ApolloComponents(
        organization_search=FakeApolloOrganizationSearch(),
        contact_discovery=FakeApolloContactDiscovery(),
        company_research=FakeApolloCompanyResearch(),
        identity=FakeApolloIdentity(),
    )


__all__ = ["FakeSireneCompanySearch", "build_fake_apollo_components"]
