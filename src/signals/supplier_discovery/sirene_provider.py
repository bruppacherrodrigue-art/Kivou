"""SIRENE-backed supplier organization provider for acquisition runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from signals.companies.sirene import SireneCompanySearch, SireneSearchCriteria
from signals.supplier_directory.store import SupplierDirectoryStore
from signals.supplier_discovery.contracts import (
    SireneOrganizationCandidate,
    SupplierSearchPage,
    SupplierSearchProfile,
)
from signals.supplier_discovery.families import load_supplier_family_catalog


class SireneOrganizationSearchProvider:
    """Return named, active SIRENE companies; it never calls Apollo organizations."""

    def __init__(
        self,
        search: SireneCompanySearch | None = None,
        *,
        directory: SupplierDirectoryStore | None = None,
    ) -> None:
        self._search = search or SireneCompanySearch()
        self._directory = directory

    def search_page(
        self,
        profile: SupplierSearchProfile,
        *,
        page: int,
        observed_at: dt.datetime,
    ) -> SupplierSearchPage:
        if page != 1 or not profile.sirene_naf_codes or not profile.sirene_departments:
            return SupplierSearchPage(
                page=page,
                per_page=profile.per_page,
                total_entries=0,
                total_pages=1,
                candidates=(),
                rejections=(),
            )
        by_key = {
            family.key: family
            for families in load_supplier_family_catalog().values()
            for family in families
        }
        family_keys = profile.supplier_family_keys or ("__all__",)
        families = (
            tuple(by_key[key] for key in family_keys if key in by_key)
            if family_keys != ("__all__",)
            else ()
        )
        naf_groups = (
            tuple((family.key, family.naf_codes) for family in families)
            if families
            else (("__all__", profile.sirene_naf_codes),)
        )
        companies = []
        for family_key, naf_codes in naf_groups:
            companies.extend(
                (family_key, company)
                for company in self._search.find(
                    SireneSearchCriteria(
                        naf_codes=naf_codes,
                        departments=profile.sirene_departments,
                        min_employees=5,
                        max_employees=250,
                        limit=25,
                    )
                )
            )
        candidates = []
        for family_key, company in companies:
            if self._directory is not None:
                self._directory.upsert_identity(
                    siren=company.siren,
                    legal_name=company.legal_name,
                    naf_code=company.naf_code,
                    family_key=family_key,
                    department=company.department,
                    city=company.city,
                    employees=company.employees,
                    observed_at=company.observed_at,
                )
            canonical = {
                "provider": "sirene",
                "provider_organization_id": company.siren,
                "display_name": company.legal_name,
                "normalized_name": " ".join(company.legal_name.casefold().split()),
                "primary_domain": None,
                "website_url": None,
                "linkedin_company_url": None,
                "country_code": "FR",
                "location": company.city,
                "industry": f"{family_key}:{company.naf_code or ''}",
            }
            candidates.append(
                SireneOrganizationCandidate(
                    **canonical,
                    provider_observed_at=observed_at,
                    source_fingerprint=hashlib.sha256(
                        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                )
            )
        return SupplierSearchPage(
            page=1,
            per_page=profile.per_page,
            total_entries=len(candidates),
            total_pages=1,
            candidates=tuple(candidates),
            rejections=(),
        )


__all__ = ["SireneOrganizationSearchProvider"]
