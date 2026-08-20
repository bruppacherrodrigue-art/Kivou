"""Narrow replaceable company-research provider boundary."""

from __future__ import annotations

from typing import Protocol

from signals.company_research.contracts import (
    ApolloOrganizationObservation,
    CompanyResearchProfile,
)


class CompanyResearchProvider(Protocol):
    def fetch_organization(
        self, profile: CompanyResearchProfile
    ) -> ApolloOrganizationObservation: ...
