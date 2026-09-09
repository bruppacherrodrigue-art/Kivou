"""Durable resolution from a SIRENE supplier identity to one Apollo organisation."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy.engine import Engine

from signals.company_research.contracts import CompanyResearchProviderError
from signals.company_research.profile import build_company_research_profile
from signals.company_research.provider import CompanyResearchProvider
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import sirene_apollo_binding
from signals.supplier_discovery.contracts import SireneOrganizationCandidate


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
    status: BindingStatus
    created_at: dt.datetime
    updated_at: dt.datetime


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def _binding(row) -> SireneApolloBinding:
    values = dict(row)
    for field in ("resolved_at", "created_at", "updated_at"):
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
            row = connection.execute(
                sa.select(sirene_apollo_binding).where(
                    sirene_apollo_binding.c.siren == siren
                )
            ).mappings().one_or_none()
        return None if row is None else _binding(row)

    def put(
        self,
        *,
        siren: str,
        apollo_organization_id: str | None,
        resolution_method: str,
        confidence_score: Decimal | None,
        status: BindingStatus,
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
            row = connection.execute(
                sa.select(sirene_apollo_binding).where(
                    sirene_apollo_binding.c.siren == siren
                )
            ).mappings().one()
        return _binding(row)


class SireneApolloResolver:
    """Resolve one named SIRENE company; never performs a broad Apollo search."""

    def __init__(
        self,
        engine: Engine,
        *,
        provider: CompanyResearchProvider,
        store: SireneApolloBindingStore | None = None,
    ) -> None:
        self._provider = provider
        self._store = store or SireneApolloBindingStore(engine)

    def resolve(self, identity: SireneOrganizationCandidate) -> SireneApolloBinding:
        existing = self._store.get(identity.provider_organization_id)
        if existing is not None and existing.status is BindingStatus.RESOLVED:
            return existing
        method = "domain_name_city" if identity.primary_domain else "name_city"
        confidence = Decimal("0.95") if identity.primary_domain else Decimal("0.80")
        profile = build_company_research_profile(
            identity.provider_organization_id,
            siren=identity.provider_organization_id,
            organization_name=identity.display_name,
            organization_city=identity.location,
            organization_domain=identity.primary_domain,
        )
        try:
            observation = self._provider.fetch_organization(profile)
        except CompanyResearchProviderError as error:
            if error.category != "not_found":
                raise
            return self._store.put(
                siren=identity.provider_organization_id,
                apollo_organization_id=None,
                resolution_method=method,
                confidence_score=None,
                status=BindingStatus.UNRESOLVED,
            )
        return self._store.put(
            siren=identity.provider_organization_id,
            apollo_organization_id=observation.provider_organization_id,
            resolution_method=observation.resolution_method or method,
            confidence_score=observation.resolution_confidence_score or confidence,
            status=BindingStatus.RESOLVED,
        )


__all__ = [
    "BindingStatus",
    "SireneApolloBinding",
    "SireneApolloBindingStore",
    "SireneApolloResolver",
]
