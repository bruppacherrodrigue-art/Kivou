"""Program-to-Apollo profile mapping; Apollo remains a bounded data adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.contact_discovery.contracts import DecisionMakerSearchProfile
from signals.contact_discovery.profile import build_decision_maker_profile


@dataclass(frozen=True)
class ProgramOrganizationSearchProfile:
    profile_ref: str
    employee_ranges: tuple[str, ...]
    organization_locations: tuple[str, ...]
    organization_not_locations: tuple[str, ...]
    keyword_tags: tuple[str, ...]
    max_pages: int
    per_page: int


def build_program_search_profile(
    config: AcquisitionProgramConfig,
) -> ProgramOrganizationSearchProfile:
    locations = {"FR": "France"}
    if config.target_country not in locations:
        raise ValueError("program country has no Apollo location mapping")
    return ProgramOrganizationSearchProfile(
        profile_ref=f"acquisition-program:{config.program_key}:{config.schema_version}",
        employee_ranges=(f"{config.target_company_size_min},{config.target_company_size_max}",),
        organization_locations=(locations[config.target_country],),
        organization_not_locations=(),
        keyword_tags=config.apollo_organization_keywords,
        max_pages=config.apollo_max_pages,
        per_page=config.apollo_per_page,
    )


def build_program_contact_profile(
    config: AcquisitionProgramConfig,
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    provider_organization_id: str,
    organization_domain: str,
) -> DecisionMakerSearchProfile:
    base = build_decision_maker_profile(
        acquisition_opportunity_id=acquisition_opportunity_id,
        supplier_ref=supplier_ref,
        provider_organization_id=provider_organization_id,
        organization_domain=organization_domain,
    )
    values = base.model_dump(mode="json", exclude={"profile_fingerprint"})
    values.update(
        profile_version=f"{config.program_key}-contact-v1",
        person_titles=config.apollo_person_titles,
        person_seniorities=config.apollo_person_seniorities,
        per_page=min(config.apollo_per_page, 25),
    )
    fingerprint = hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DecisionMakerSearchProfile.model_validate({**values, "profile_fingerprint": fingerprint})


__all__ = [
    "ProgramOrganizationSearchProfile",
    "build_program_contact_profile",
    "build_program_search_profile",
]
