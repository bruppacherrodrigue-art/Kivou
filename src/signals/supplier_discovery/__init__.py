"""Kivou-owned bounded supplier discovery contracts and Apollo boundary."""

from signals.supplier_discovery.contracts import (
    ApolloOrganizationCandidate,
    ApolloProviderError,
    CandidateRejection,
    DiscoveryRunStatus,
    SupplierIdentityStatus,
    SupplierRecord,
    SupplierSearchPage,
    SupplierSearchProfile,
    SupplierTargetingConfig,
)
from signals.supplier_discovery.profile import build_supplier_search_profile

__all__ = [
    "ApolloOrganizationCandidate",
    "ApolloProviderError",
    "CandidateRejection",
    "DiscoveryRunStatus",
    "SupplierIdentityStatus",
    "SupplierRecord",
    "SupplierSearchPage",
    "SupplierSearchProfile",
    "SupplierTargetingConfig",
    "build_supplier_search_profile",
]
