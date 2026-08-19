"""Persistance SaaS — la plus petite couche durable au-dessus du moteur.

    SOURCE → AWARD → RECENCY → UNDERSTANDING → NEEDS → ICP MATCH → SIGNAL STOCKÉ

Quatre tables, une frontière : trois ne contiennent que des faits publiés, une
seule contient ce que Kivou en déduit. SQLAlchemy est employé en mode **Core**
uniquement — le modèle canonique reste pydantic, et aucune classe du domaine ne
devient une entité de base.
"""

from signals.persistence.database import (
    DATABASE_URL_ENV,
    create_database_engine,
    current_revision,
    migrate_to_latest,
    resolve_database_url,
)
from signals.persistence.identity import award_key, event_key, signal_key
from signals.persistence.materialization import (
    FactPersistenceResult,
    MaterializationResult,
    content_fingerprint,
    materialize_signal,
    persist_award_facts,
)
from signals.persistence.opportunity import (
    OpportunityConflict,
    ResolvedOpportunity,
    opportunity_of,
    resolve_or_create_opportunity,
)
from signals.persistence.repository import (
    StoredAward,
    StoredEvent,
    StoredEvidence,
    StoredSignal,
    get_signal,
    list_signals,
)
from signals.persistence.schema import METADATA

__all__ = [
    "DATABASE_URL_ENV",
    "METADATA",
    "FactPersistenceResult",
    "MaterializationResult",
    "OpportunityConflict",
    "ResolvedOpportunity",
    "StoredAward",
    "StoredEvent",
    "StoredEvidence",
    "StoredSignal",
    "award_key",
    "content_fingerprint",
    "create_database_engine",
    "current_revision",
    "event_key",
    "get_signal",
    "list_signals",
    "materialize_signal",
    "migrate_to_latest",
    "opportunity_of",
    "persist_award_facts",
    "resolve_database_url",
    "resolve_or_create_opportunity",
    "signal_key",
]
