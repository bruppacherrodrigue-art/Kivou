"""Relire un signal stocké — le strict nécessaire pour prouver que la persistance tient.

Deux fonctions, `get_signal` et `list_signals`, et un filtre volontairement
pauvre. Le moteur de recherche du produit n'existe pas encore ; construire
maintenant une pagination, un classement et une indexation full-text
reviendrait à figer des choix avant d'avoir un seul client.

Ce que le lecteur rend n'est pas une ligne de base mais une vue reconstituée :
les faits d'un côté, les inférences de l'autre.

    L'instantané n'est pas la vérité du jour (closeout §1)
    ──────────────────────────────────────────────────────
    `materialized_recency_status` décrit ce qui a été constaté **le jour de la
    matérialisation**. Il reste figé, et c'est ce qui le rend utile pour l'audit
    et la reproductibilité — mais un marché matérialisé « vient de remporter »
    le 18 août ne l'est plus le 18 octobre.

    Toute affirmation client passe donc par `current_recency(as_of=…)`, qui
    réévalue les **dates brutes** rechargées, et par `claim(lang=…, as_of=…)`
    qui en découle. `as_of` est obligatoire : aucune horloge système n'est lue
    ici, sans quoi un test cesserait de tester quoi que ce soit dès le
    lendemain.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from signals.persistence.schema import (
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)
from signals.recency import AwardRecency


@dataclasses.dataclass(frozen=True)
class StoredEvent:
    """La publication d'origine, telle qu'elle a été constatée."""

    event_key: str
    source_system: str
    source_notice_id: str
    notice_version: str | None
    source_country: str
    source_url: str | None
    published_at: dt.date | dt.datetime | None
    published_on: dt.date | None
    published_precision: str | None
    discovered_at: dt.datetime | None
    #: L'identifiant de procédure publié — utile pour remonter à la source.
    source_procedure_id: str | None = None
    #: Les acheteurs publics de la procédure, tels que la source les publie.
    procedure_buyers: list[dict[str, Any]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class StoredAward:
    """Le contrat attribué — que des faits publiés."""

    award_key: str
    source_award_id: str | None
    lot_identifier: str | None
    title: str | None
    cpv_main: str | None
    amount: Decimal | None
    currency: str | None
    place_country: str | None
    award_date: dt.date | None
    contract_signature_date: dt.date | None
    contract_notification_date: dt.date | None
    contract_start_date: dt.date | None
    contract_end_date: dt.date | None
    awardee_parties: list[dict[str, Any]]
    lot_title: str | None = None
    contract_reference: str | None = None
    place_of_performance: dict[str, Any] | None = None


@dataclasses.dataclass(frozen=True)
class StoredEvidence:
    """Un ancrage vérifiable."""

    anchors_kind: str
    anchors_ref: str
    source_system: str
    source_kind: str
    source_notice_id: str | None
    source_url: str | None
    path: str | None
    excerpt: str | None
    engine_version: str | None
    source_procedure_id: str | None = None
    retrieved_at: dt.datetime | None = None


@dataclasses.dataclass(frozen=True)
class StoredSignal:
    """Un signal client rechargé — faits, inférences et horloges séparés."""

    signal_key: str
    opportunity_key: str
    #: La représentation source qui a produit la révision courante — pas
    #: l'identité logique du signal, qui est `opportunity_key`.
    materialization_award_key: str
    target_icp_id: str
    revision: int
    content_fingerprint: str
    event: StoredEvent
    award: StoredAward
    evidence: tuple[StoredEvidence, ...]

    # ── l'INSTANTANÉ, figé au jour de la matérialisation ──────────────────────
    materialized_recency_status: str
    materialized_primary_event: str | None
    materialized_award_clock_status: str
    materialized_notification_clock_status: str
    materialized_publication_clock_status: str
    materialized_award_age_days: int | None
    materialized_notification_age_days: int | None
    materialized_publication_age_days: int | None
    materialized_as_of: dt.date
    recency_policy_version: str

    winner_name: str | None
    winner_country: str | None
    winner_identifier_scheme: str | None
    winner_identifier_value: str | None

    inferred_contract_type: str | None
    inferred_sector: str | None
    inferred_trade_domain: str | None
    inferred_contract_summary: str | None
    plausible_needs: list[dict[str, Any]]

    icp_match_decision: str | None
    icp_match_band: str | None
    icp_match_confidence: str | None
    icp_match_normalized_score: int | None
    icp_matched_needs: list[str]

    engine_versions: dict[str, str]
    materialized_at: dt.datetime

    def current_recency(self, *, as_of: dt.date) -> AwardRecency:
        """Réévalue la fraîcheur à une date donnée, depuis les dates BRUTES stockées.

        C'est la seule lecture qui ait une valeur commerciale. L'instantané
        `materialized_*` dit ce qui était vrai le jour J ; celle-ci dit ce qui
        l'est aujourd'hui, et les deux divergent dès le lendemain.

        `as_of` est obligatoire — pas de valeur par défaut, pas d'horloge lue en
        douce. La couche de persistance ne décide pas quel jour il est.
        """
        from signals.recency import assess_recency

        return assess_recency(
            award_date=self.award.award_date,
            contract_notification_date=self.award.contract_notification_date,
            publication_date=self.event.published_on,
            discovered_at=self.event.discovered_at.date() if self.event.discovered_at else None,
            as_of=as_of,
        )

    def claim(self, *, as_of: dt.date, lang: str = "fr") -> str:
        """La phrase client, régénérée de la fraîcheur RÉÉVALUÉE à `as_of`.

        Deux raisons de ne jamais la stocker : elle divergerait le jour où la
        politique de formulation change, et surtout elle vieillirait avec la
        ligne. Un signal matérialisé « vient de remporter » en août dirait
        encore la même chose en octobre.
        """
        from signals.recency.claim import claim_for_status

        return claim_for_status(
            self.current_recency(as_of=as_of).status, company=self.winner_name or "", lang=lang
        )

    def current_primary_event(self, *, as_of: dt.date) -> str | None:
        """Le type d'événement MVP tel qu'il vaut aujourd'hui."""
        from signals.recency.claim import mvp_event_type

        return mvp_event_type(self.current_recency(as_of=as_of).status)


def _as_date(value: Any) -> dt.date | None:
    """SQLite rend des chaînes là où PostgreSQL rend des dates."""
    if value is None or isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    return dt.date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any) -> dt.datetime | None:
    """Un instant conscient de son fuseau, quel que soit le moteur.

    PostgreSQL rend un `timestamptz` déjà situé ; SQLite n'a pas de fuseau et
    rend un instant nu. Tous les horodatages écrits ici sont en UTC, donc
    rattacher UTC à un instant nu restitue exactement ce qui a été stocké — et
    évite qu'un test passe sur un moteur et échoue sur l'autre.
    """
    if value is None:
        return None
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _published_instant(raw: str | None, precision: str | None) -> dt.date | dt.datetime | None:
    """Reconstitue la précision réellement publiée (§ SPEC-005)."""
    if raw is None:
        return None
    return dt.date.fromisoformat(raw) if precision == "date" else dt.datetime.fromisoformat(raw)


def _event(row: sa.Row) -> StoredEvent:
    return StoredEvent(
        event_key=row.event_key,
        source_system=row.source_system,
        source_notice_id=row.source_notice_id,
        notice_version=row.notice_version,
        source_country=row.source_country,
        source_url=row.source_url,
        published_at=_published_instant(row.published_at_raw, row.published_precision),
        published_on=_as_date(row.published_on),
        published_precision=row.published_precision,
        discovered_at=_as_datetime(row.discovered_at),
        source_procedure_id=row.source_procedure_id,
        procedure_buyers=row.procedure_buyers,
    )


def _award(row: sa.Row) -> StoredAward:
    return StoredAward(
        award_key=row.award_key,
        source_award_id=row.source_award_id,
        lot_identifier=row.lot_identifier,
        title=row.title,
        cpv_main=row.cpv_main,
        amount=Decimal(str(row.amount)) if row.amount is not None else None,
        currency=row.currency,
        place_country=row.place_country,
        award_date=_as_date(row.award_date),
        contract_signature_date=_as_date(row.contract_signature_date),
        contract_notification_date=_as_date(row.contract_notification_date),
        contract_start_date=_as_date(row.contract_start_date),
        contract_end_date=_as_date(row.contract_end_date),
        awardee_parties=row.awardee_parties,
        lot_title=row.lot_title,
        contract_reference=row.contract_reference,
        place_of_performance=row.place_of_performance,
    )


_SELECT = (
    sa.select(materialized_signal, contract_award, source_event)
    .select_from(
        materialized_signal.join(
            contract_award,
            materialized_signal.c.materialization_award_key == contract_award.c.award_key,
        ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
    )
    # Ordre total et déterministe : deux lectures rendent la même liste.
    .order_by(materialized_signal.c.materialized_at, materialized_signal.c.signal_key)
)


#: La sélection canonique d'un signal. Exposée pour que d'autres couches — le
#: feed client de SPEC-012, par exemple — composent leur propre restriction de
#: propriété PAR-DESSUS elle, au lieu de réécrire une seconde jointure qui
#: divergerait le jour où le schéma bouge.
SIGNAL_SELECT = _SELECT


def load_evidence(connection: sa.Connection, award_key: str) -> tuple[StoredEvidence, ...]:
    """Les ancrages d'un award. Séparé de l'hydratation pour que le feed puisse
    s'en passer : une liste n'a pas besoin des quarante preuves de chaque ligne.
    """
    anchors = connection.execute(
        sa.select(evidence)
        .where(evidence.c.award_key == award_key)
        .order_by(evidence.c.evidence_key)
    ).all()
    return tuple(
        StoredEvidence(
            anchors_kind=anchor.anchors_kind,
            anchors_ref=anchor.anchors_ref,
            source_system=anchor.source_system,
            source_kind=anchor.source_kind,
            source_notice_id=anchor.source_notice_id,
            source_url=anchor.source_url,
            path=anchor.path,
            excerpt=anchor.excerpt,
            engine_version=anchor.engine_version,
            source_procedure_id=anchor.source_procedure_id,
            retrieved_at=_as_datetime(anchor.retrieved_at),
        )
        for anchor in anchors
    )


def signal_from_row(row: sa.Row, *, evidence: tuple[StoredEvidence, ...] = ()) -> StoredSignal:
    """Reconstitue un signal depuis une ligne de `SIGNAL_SELECT`.

    Les preuves sont passées à part : sans elles la lecture reste une seule
    requête, ce qui évite le N+1 quand on liste (§31 SPEC-012).
    """
    return StoredSignal(
        signal_key=row.signal_key,
        opportunity_key=row.opportunity_key,
        materialization_award_key=row.materialization_award_key,
        target_icp_id=row.target_icp_id,
        revision=row.revision,
        content_fingerprint=row.content_fingerprint,
        event=_event(row),
        award=_award(row),
        evidence=evidence,
        materialized_recency_status=row.materialized_recency_status,
        materialized_primary_event=row.materialized_primary_event,
        materialized_award_clock_status=row.materialized_award_clock_status,
        materialized_notification_clock_status=row.materialized_notification_clock_status,
        materialized_publication_clock_status=row.materialized_publication_clock_status,
        materialized_award_age_days=row.materialized_award_age_days,
        materialized_notification_age_days=row.materialized_notification_age_days,
        materialized_publication_age_days=row.materialized_publication_age_days,
        materialized_as_of=_as_date(row.materialized_as_of),
        recency_policy_version=row.recency_policy_version,
        winner_name=row.winner_name,
        winner_country=row.winner_country,
        winner_identifier_scheme=row.winner_identifier_scheme,
        winner_identifier_value=row.winner_identifier_value,
        inferred_contract_type=row.inferred_contract_type,
        inferred_sector=row.inferred_sector,
        inferred_trade_domain=row.inferred_trade_domain,
        inferred_contract_summary=row.inferred_contract_summary,
        plausible_needs=row.plausible_needs,
        icp_match_decision=row.icp_match_decision,
        icp_match_band=row.icp_match_band,
        icp_match_confidence=row.icp_match_confidence,
        icp_match_normalized_score=row.icp_match_normalized_score,
        icp_matched_needs=row.icp_matched_needs,
        engine_versions=row.engine_versions,
        materialized_at=_as_datetime(row.materialized_at),
    )


def _hydrate(connection: sa.Connection, row: sa.Row) -> StoredSignal:
    return signal_from_row(row, evidence=load_evidence(connection, row.award_key))


def get_signal(connection: sa.Connection, signal_key: str) -> StoredSignal | None:
    """Un signal, ou `None`. Un identifiant inconnu n'est pas une erreur."""
    row = connection.execute(
        _SELECT.where(materialized_signal.c.signal_key == signal_key)
    ).one_or_none()
    return None if row is None else _hydrate(connection, row)


def list_signals(
    connection: sa.Connection,
    *,
    target_icp_id: str | None = None,
    country: str | None = None,
    materialized_primary_event: str | None = None,
    materialized_recency_status: str | None = None,
    winner_identifier_value: str | None = None,
    limit: int = 100,
) -> list[StoredSignal]:
    """Le jeu de filtres minimal que §10 demande, et rien de plus.

    Les filtres de fraîcheur portent le préfixe `materialized_` parce qu'ils
    interrogent l'INSTANTANÉ stocké, pas la fraîcheur du jour (closeout §1). Un
    paramètre nommé `recency_status` aurait laissé croire l'inverse — et un
    appelant aurait construit un feed « nouveautés » sur des lignes vieilles de
    trois mois. Pour la fraîcheur actuelle, chaque résultat expose
    `current_recency(as_of=…)`.

    `country` porte sur le pays de la **source**, pas sur le lieu d'exécution :
    c'est celui qu'un client lit comme « marché suisse » ou « marché français ».
    """
    query = _SELECT.limit(limit)
    conditions = {
        materialized_signal.c.target_icp_id: target_icp_id,
        source_event.c.source_country: country,
        materialized_signal.c.materialized_primary_event: materialized_primary_event,
        materialized_signal.c.materialized_recency_status: materialized_recency_status,
        materialized_signal.c.winner_identifier_value: winner_identifier_value,
    }
    for column, value in conditions.items():
        if value is not None:
            query = query.where(column == value)
    return [_hydrate(connection, row) for row in connection.execute(query).all()]
