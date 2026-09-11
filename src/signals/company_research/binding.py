"""Durable resolution from a SIRENE supplier identity to one Apollo organisation."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.engine import Engine

from signals.company_research.contracts import CompanyResearchProviderError
from signals.company_research.domain import (
    CompanyDomainResolver,
    DomainResolution,
    DomainResolutionTemporaryFailure,
)
from signals.company_research.profile import build_company_research_profile
from signals.company_research.provider import CompanyResearchProvider
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import sirene_apollo_binding
from signals.supplier_directory.store import SupplierDirectoryStore
from signals.supplier_discovery.contracts import SireneOrganizationCandidate

logger = logging.getLogger(__name__)


class BindingStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    LEGACY = "legacy"


class SireneApolloBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    siren: Annotated[str, StringConstraints(pattern=r"^\d{9}$")]
    apollo_organization_id: str | None = None
    resolved_at: dt.datetime | None = None
    resolution_method: str
    confidence_score: Decimal | None = Field(default=None, ge=0, le=1)
    domain: str | None = None
    website_url: str | None = None
    domain_source: str | None = None
    domain_query: str | None = None
    domain_observed_at: dt.datetime | None = None
    status: BindingStatus
    created_at: dt.datetime
    updated_at: dt.datetime


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def _binding(row) -> SireneApolloBinding:
    values = dict(row)
    for field in ("resolved_at", "domain_observed_at", "created_at", "updated_at"):
        values[field] = _aware(values[field])
    return SireneApolloBinding.model_validate(values)


class SireneApolloBindingStore:
    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._clock = clock

    def get(self, siren: str) -> SireneApolloBinding | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(sirene_apollo_binding).where(sirene_apollo_binding.c.siren == siren)
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _binding(row)

    def put(
        self,
        *,
        siren: str,
        apollo_organization_id: str | None,
        resolution_method: str,
        confidence_score: Decimal | None,
        status: BindingStatus,
        domain_resolution: DomainResolution | None = None,
    ) -> SireneApolloBinding:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("binding clock must be timezone-aware")
        values = {
            "siren": siren,
            "apollo_organization_id": apollo_organization_id,
            "resolved_at": now if status is BindingStatus.RESOLVED else None,
            "resolution_method": resolution_method,
            "confidence_score": confidence_score,
            "domain": domain_resolution.domain if domain_resolution else None,
            "website_url": domain_resolution.website_url if domain_resolution else None,
            "domain_source": domain_resolution.source if domain_resolution else None,
            "domain_query": domain_resolution.query if domain_resolution else None,
            "domain_observed_at": domain_resolution.observed_at if domain_resolution else None,
            "status": status.value,
            "created_at": now,
            "updated_at": now,
        }
        with self._engine.begin() as connection:
            created = insert_if_absent(
                connection,
                sirene_apollo_binding,
                values,
                index_elements=[sirene_apollo_binding.c.siren],
            )
            if not created:
                connection.execute(
                    sa.update(sirene_apollo_binding)
                    .where(sirene_apollo_binding.c.siren == siren)
                    .values(**{key: value for key, value in values.items() if key != "created_at"})
                )
            row = (
                connection.execute(
                    sa.select(sirene_apollo_binding).where(sirene_apollo_binding.c.siren == siren)
                )
                .mappings()
                .one()
            )
        return _binding(row)


class SireneApolloResolver:
    """Resolve one named SIRENE company; never performs a broad Apollo search."""

    def __init__(
        self,
        engine: Engine,
        *,
        provider: CompanyResearchProvider,
        store: SireneApolloBindingStore | None = None,
        domain_resolver: CompanyDomainResolver | None = None,
        directory: SupplierDirectoryStore | None = None,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._provider = provider
        self._store = store or SireneApolloBindingStore(engine)
        self._domain_resolver = domain_resolver
        self._directory = directory
        self._clock = clock

    def resolve(self, identity: SireneOrganizationCandidate) -> SireneApolloBinding:
        now = self._clock()
        existing = self._store.get(identity.provider_organization_id)
        if (
            self._directory is None
            and existing is not None
            and existing.status is BindingStatus.RESOLVED
            and (self._domain_resolver is None or existing.domain is not None)
        ):
            return existing
        cached_domain = (
            self._directory.fresh_domain(identity.provider_organization_id, at=now)
            if self._directory is not None
            else None
        )
        permanently_without_website = bool(
            self._directory is not None
            and self._directory.permanently_without_website(identity.provider_organization_id)
        )
        if permanently_without_website:
            logger.info(
                "supplier_directory_provider_call_avoided",
                extra={"provider": "serper", "siren": identity.provider_organization_id},
            )
            domain_resolution = None
        elif cached_domain is not None:
            logger.info(
                "supplier_directory_provider_call_avoided",
                extra={"provider": "serper", "siren": identity.provider_organization_id},
            )
            domain_resolution = DomainResolution(
                domain=cached_domain.domain,
                website_url=cached_domain.website_url or f"https://{cached_domain.domain}",
                source=cached_domain.domain_source or "serper",
                validation_method=cached_domain.domain_validation_method,
                validation_evidence_url=cached_domain.domain_validation_evidence_url,
                observed_at=cached_domain.domain_observed_at or now,
            )
        else:
            try:
                domain_resolution = (
                    self._domain_resolver.resolve(identity)
                    if self._domain_resolver is not None
                    else None
                )
            except DomainResolutionTemporaryFailure:
                domain_resolution = None
                if self._directory is not None:
                    self._directory.record_website_connection_failure(
                        identity.provider_organization_id, observed_at=now
                    )
            if self._directory is not None and domain_resolution is not None:
                recorded = self._directory.record_domain(
                    identity.provider_organization_id,
                    domain=domain_resolution.domain,
                    website_url=domain_resolution.website_url,
                    source=domain_resolution.source,
                    validation_method=domain_resolution.validation_method,
                    validation_evidence_url=domain_resolution.validation_evidence_url,
                    observed_at=domain_resolution.observed_at,
                )
                if not recorded:
                    domain_resolution = None
            elif (
                self._directory is not None
                and self._domain_resolver is not None
                and domain_resolution is None
            ):
                self._directory.mark_without_website(
                    identity.provider_organization_id,
                    search_queries_completed=int(
                        getattr(self._domain_resolver, "search_queries_completed", 0)
                    ),
                    search_results_examined=int(
                        getattr(self._domain_resolver, "search_results_examined", 0)
                    ),
                    observed_at=now,
                )
        domain = domain_resolution.domain if domain_resolution is not None else None
        if self._directory is not None and self._directory.permanently_without_website(
            identity.provider_organization_id
        ):
            return self._store.put(
                siren=identity.provider_organization_id,
                apollo_organization_id=None,
                resolution_method="no_website",
                confidence_score=None,
                status=BindingStatus.UNRESOLVED,
                domain_resolution=None,
            )
        cached_apollo = (
            self._directory.fresh_apollo(identity.provider_organization_id, at=now)
            if self._directory is not None
            else None
        )
        if cached_apollo is not None and existing is not None:
            logger.info(
                "supplier_directory_provider_call_avoided",
                extra={
                    "provider": "apollo_organization",
                    "siren": identity.provider_organization_id,
                },
            )
            if domain_resolution is None and existing.domain is not None:
                existing = self._store.put(
                    siren=identity.provider_organization_id,
                    apollo_organization_id=existing.apollo_organization_id,
                    resolution_method=existing.resolution_method,
                    confidence_score=existing.confidence_score,
                    status=existing.status,
                    domain_resolution=None,
                )
            elif domain_resolution is not None and existing.domain != domain_resolution.domain:
                existing = self._store.put(
                    siren=identity.provider_organization_id,
                    apollo_organization_id=existing.apollo_organization_id,
                    resolution_method=existing.resolution_method,
                    confidence_score=existing.confidence_score,
                    status=existing.status,
                    domain_resolution=domain_resolution,
                )
            return existing
        method = "domain" if domain else "name_city"
        confidence = Decimal("0.95") if domain else Decimal("0.80")
        profile = build_company_research_profile(
            identity.provider_organization_id,
            siren=identity.provider_organization_id,
            organization_name=identity.display_name,
            organization_city=identity.location,
            organization_domain=domain,
        )
        try:
            observation = self._provider.fetch_organization(profile)
        except CompanyResearchProviderError as error:
            if error.category != "not_found":
                raise
            binding = self._store.put(
                siren=identity.provider_organization_id,
                apollo_organization_id=None,
                resolution_method=method,
                confidence_score=None,
                status=BindingStatus.UNRESOLVED,
                domain_resolution=domain_resolution,
            )
            if self._directory is not None:
                self._directory.record_apollo(
                    identity.provider_organization_id,
                    organization_id=None,
                    status="unresolved",
                    observed_at=now,
                )
            return binding
        binding = self._store.put(
            siren=identity.provider_organization_id,
            apollo_organization_id=observation.provider_organization_id,
            resolution_method=observation.resolution_method or method,
            confidence_score=observation.resolution_confidence_score or confidence,
            status=BindingStatus.RESOLVED,
            domain_resolution=domain_resolution,
        )
        if self._directory is not None:
            self._directory.record_apollo(
                identity.provider_organization_id,
                organization_id=binding.apollo_organization_id,
                status="resolved",
                observed_at=now,
            )
        return binding


__all__ = [
    "BindingStatus",
    "SireneApolloBinding",
    "SireneApolloBindingStore",
    "SireneApolloResolver",
]
