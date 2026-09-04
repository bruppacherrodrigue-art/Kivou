from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from typing import Any, Protocol

import sqlalchemy as sa

from signals.accounts.icp_input import TargetIcpInput, to_target_icp
from signals.accounts.schema import target_icp
from signals.documents.early_capture import resolve_award_documents
from signals.ingestion.sources import AcquiredPublication
from signals.matching import MatchingEngine
from signals.needs import NeedGraphEngine
from signals.persistence import OpportunityConflict, materialize_signal, persist_award_facts
from signals.recency import assess_recency
from signals.understanding import ContractUnderstandingEngine

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class LinkResolution:
    linked_to: tuple[Any, ...] = ()
    strength: str = "unresolved"


class Linker(Protocol):
    def resolve(self, connection: sa.Connection, *, event: Any, award: Any) -> LinkResolution: ...


class NoLinker:
    def resolve(self, connection: sa.Connection, *, event: Any, award: Any) -> LinkResolution:
        return LinkResolution()


@dataclasses.dataclass(frozen=True)
class PipelineResult:
    records_persisted: int = 0
    representations_linked: int = 0
    opportunity_conflicts: int = 0
    signals_materialized: int = 0


class PipelineFailure(RuntimeError):
    """A processing failure carrying the work already committed durably."""

    def __init__(self, cause: Exception, *, partial: PipelineResult) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.partial = partial

    @property
    def category(self) -> Any:
        return getattr(self.cause, "category", None)

    @property
    def status_code(self) -> Any:
        return getattr(self.cause, "status_code", None)


def _active_targets(connection: sa.Connection) -> tuple[Any, ...]:
    rows = connection.execute(
        sa.select(
            target_icp.c.target_icp_id,
            target_icp.c.label,
            target_icp.c.matching_revision,
            target_icp.c.customer_input,
        )
        .where(
            target_icp.c.status == "active",
            target_icp.c.plan_limit_code.is_(None),
        )
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
    ).all()
    targets = []
    for row in rows:
        customer_input = TargetIcpInput.model_validate(row.customer_input)
        targets.append(
            (
                to_target_icp(
                    customer_input,
                    target_icp_id=row.target_icp_id,
                    label=row.label,
                ),
                row.matching_revision,
            )
        )
    return tuple(targets)


def _publication_date(event: Any) -> dt.date | None:
    published = event.published_at
    if isinstance(published, dt.datetime):
        return published.date()
    return published


class IngestionPipeline:
    """Compose existing approved engines around durable source facts."""

    def __init__(self, engine: sa.Engine, *, linker: Linker | None = None) -> None:
        self.engine = engine
        self.linker = linker or NoLinker()
        self.understanding = ContractUnderstandingEngine()
        self.needs = NeedGraphEngine()
        self.matching = MatchingEngine()

    def _materialize_for_targets(
        self,
        publication: AcquiredPublication,
        persisted_awards: list[tuple[Any, LinkResolution]],
        *,
        as_of: dt.date,
        persisted_at: dt.datetime,
        materialized_progress: list[int],
    ) -> int:
        with self.engine.connect() as connection:
            active_targets = _active_targets(connection)
        materialized = 0
        for award, resolution in persisted_awards:
            with self.engine.begin() as connection:
                document_resolution = resolve_award_documents(
                    connection,
                    event=publication.event,
                    award=award,
                )
            requirements = (
                tuple(document_resolution.analysis.requirements)
                if document_resolution.analysis is not None
                else ()
            )
            understanding = (
                self.understanding.understand(
                    award,
                    publication.event,
                    document_requirements=requirements,
                )
                if requirements
                else self.understanding.understand(award, publication.event)
            )
            needs = self.needs.derive(understanding)
            recency = assess_recency(
                award_date=award.award_date,
                contract_notification_date=award.contract_notification_date,
                publication_date=_publication_date(publication.event),
                discovered_at=(
                    publication.event.provenance.retrieved_at.date()
                    if publication.event.provenance.retrieved_at
                    else None
                ),
                as_of=as_of,
            )
            for profile, target_revision in active_targets:
                match = self.matching.match(understanding, needs, profile, as_of=as_of)
                # Eligibility is the approved engine decision. The runtime adds no
                # threshold, entitlement, or copied interpretation of `show`.
                if match.decision != "show":
                    continue
                with self.engine.begin() as connection:
                    result = materialize_signal(
                        connection,
                        event=publication.event,
                        award=award,
                        understanding=understanding,
                        needs=needs,
                        match=match,
                        recency=recency,
                        as_of=as_of,
                        materialized_at=persisted_at,
                        linked_to=resolution.linked_to,
                        link_strength=resolution.strength,
                        target_icp_revision=target_revision,
                    )
                delta = result.created or result.updated
                materialized += delta
                materialized_progress[0] += delta
        return materialized

    def process(
        self,
        publication: AcquiredPublication,
        *,
        as_of: dt.date,
        persisted_at: dt.datetime,
    ) -> PipelineResult:
        persisted = linked = conflicts = materialized = 0
        persisted_awards: list[tuple[Any, LinkResolution]] = []
        for award in publication.awards:
            try:
                with self.engine.begin() as connection:
                    resolution = self.linker.resolve(
                        connection, event=publication.event, award=award
                    )
                    try:
                        persist_award_facts(
                            connection,
                            event=publication.event,
                            award=award,
                            persisted_at=persisted_at,
                            linked_to=resolution.linked_to,
                            link_strength=resolution.strength,
                        )
                    except OpportunityConflict as error:
                        conflicts += 1
                        logger.warning(
                            "opportunity conflict: %s",
                            error,
                            extra={
                                "source_system": publication.event.provenance.source_system,
                                "source_notice_id": (
                                    publication.event.provenance.source_notice_id
                                ),
                                "source_award_id": award.source_award_id,
                            },
                        )
                        resolution = LinkResolution()
                        persist_award_facts(
                            connection,
                            event=publication.event,
                            award=award,
                            persisted_at=persisted_at,
                        )
                    else:
                        linked += bool(
                            resolution.linked_to and resolution.strength == "strong"
                        )
                    persisted += 1
            except Exception as error:
                raise PipelineFailure(
                    error,
                    partial=PipelineResult(
                        records_persisted=persisted,
                        representations_linked=linked,
                        opportunity_conflicts=conflicts,
                        signals_materialized=materialized,
                    ),
                ) from error
            persisted_awards.append((award, resolution))

        # Public facts are committed before customer-specific work. Matching or
        # materialization failure therefore cannot erase an otherwise valid
        # source representation; the unchanged checkpoint lets a retry resume.
        try:
            materialized_progress = [0]
            materialized += self._materialize_for_targets(
                publication,
                persisted_awards,
                as_of=as_of,
                persisted_at=persisted_at,
                materialized_progress=materialized_progress,
            )
        except Exception as error:
            raise PipelineFailure(
                error,
                partial=PipelineResult(
                    records_persisted=persisted,
                    representations_linked=linked,
                    opportunity_conflicts=conflicts,
                    signals_materialized=materialized + materialized_progress[0],
                ),
            ) from error
        return PipelineResult(
            records_persisted=persisted,
            representations_linked=linked,
            opportunity_conflicts=conflicts,
            signals_materialized=materialized,
        )
