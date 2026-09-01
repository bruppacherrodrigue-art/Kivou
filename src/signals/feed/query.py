"""La requête du feed — elle part du compte, jamais de la table des signaux.

L'ordre des jointures est une garantie de sécurité (§2)
──────────────────────────────────────────────────────
`FROM target_icp JOIN materialized_signal ON …` avec `account_id` dans le
`WHERE` ne peut structurellement pas rendre un signal non lié : un signal
d'avant les comptes n'a aucune ligne `target_icp` à joindre. La forme
inverse — tout lire puis filtrer — dépendrait d'un `WHERE` qu'un futur
appelant peut oublier. SPEC-011 a posé la règle ; ce module l'applique.

La fraîcheur COURANTE ne peut pas être triée en SQL (§6)
───────────────────────────────────────────────────────
Elle se recalcule des dates brutes à un `as_of` explicite. La trier en base
exigerait de la figer, c'est-à-dire de rendre au client l'instantané que
SPEC-010 interdit d'exposer. La lecture se fait donc en deux temps : SQL
borne et présélectionne sur les dates brutes, Python réévalue, filtre, trie
et pagine. Le plafond de lecture est annoncé, jamais silencieux.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.feed import policy
from signals.feed.history import (
    HistoryDateKind,
    cursor_for_signal,
    decode_history_cursor,
    effective_history_date,
    encode_history_cursor,
)
from signals.persistence.repository import (
    SIGNAL_SELECT,
    StoredSignal,
    load_evidence,
    signal_from_row,
)
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.recency import AwardRecency

#: §19 — un identifiant stable ne remplace pas un nom. Un attributaire réduit à
#: un SIRET reste interne : « Company: 44284979000013 » n'est pas une identité.
_IDENTIFIER_LIKE = str.maketrans("", "", " -.·/")


def _looks_like_identifier(name: str, identifier: str | None) -> bool:
    """Un nom qui n'est qu'un numéro, ou l'identifiant recopié, n'est pas un nom."""
    stripped = name.strip().translate(_IDENTIFIER_LIKE)
    if not stripped:
        return True
    if stripped.isdigit():
        return True
    reference = (identifier or "").strip().translate(_IDENTIFIER_LIKE)
    return bool(reference) and stripped == reference


def is_customer_display_name(name: str | None, identifier: str | None) -> bool:
    """Whether a published winner value is a real display name under feed policy."""
    cleaned = (name or "").strip()
    return bool(cleaned) and not _looks_like_identifier(cleaned, identifier)


def is_customer_ready(signal: StoredSignal) -> bool:
    """La révision courante porte-t-elle elle-même un nom d'entreprise affichable ?

    Non pour un nom vide, et non pour un nom qui n'est que l'identifiant
    recopié — le cas exact des notifications DECP 2022, qui publient le SIRET
    du titulaire sans sa dénomination sociale (SPEC-009E).
    """
    return is_customer_display_name(signal.winner_name, signal.winner_identifier_value)


@dataclasses.dataclass(frozen=True)
class DisplayIdentity:
    """L'identité affichable de l'attributaire, et la source qui la publie."""

    name: str
    country: str | None
    identifier_scheme: str | None
    identifier_value: str | None
    #: La représentation source d'où vient le NOM. Elle n'est pas toujours celle
    #: qui a produit la révision courante : c'est tout l'objet du repli.
    from_award_key: str


def _named_identity(awardee_parties: list[dict[str, Any]]) -> tuple[str, str | None, Any] | None:
    """Le premier attributaire portant un vrai nom, ou `None`."""
    for party in awardee_parties or []:
        for member in party.get("members") or []:
            organization = member.get("organization") or {}
            name = (organization.get("legal_name") or "").strip()
            identifiers = organization.get("identifiers") or []
            identifier = identifiers[0] if identifiers else None
            value = (identifier or {}).get("value")
            if is_customer_display_name(name, value):
                return name, organization.get("country"), identifier
    return None


def resolve_display_identity(
    connection: sa.Connection, signals: list[StoredSignal]
) -> dict[str, DisplayIdentity]:
    """Le nom affichable de chaque signal — le sien, sinon celui d'une SŒUR.

    Une opportunité peut porter plusieurs représentations sources. La révision
    courante vient de la dernière écrite, et rien ne garantit qu'elle nomme
    l'attributaire : une notification DECP 2022 publie le SIRET sans la
    dénomination sociale, et prendrait alors la place d'un avis BOAMP qui, lui,
    la publie. Effacer le nom parce qu'une seconde source est arrivée ferait
    disparaître du feed un signal déjà servi (§28.4).

    Le repli ne fabrique rien : il relit un nom DÉJÀ PUBLIÉ par une autre
    représentation du même contrat, et conserve de quelle représentation il
    vient. Une seule requête couvre tous les signaux, donc pas de N+1 (§31).
    """
    resolved: dict[str, DisplayIdentity] = {}
    pending: dict[str, list[str]] = {}
    for signal in signals:
        if is_customer_ready(signal):
            resolved[signal.signal_key] = DisplayIdentity(
                name=(signal.winner_name or "").strip(),
                country=signal.winner_country,
                identifier_scheme=signal.winner_identifier_scheme,
                identifier_value=signal.winner_identifier_value,
                from_award_key=signal.materialization_award_key,
            )
        else:
            pending.setdefault(signal.opportunity_key, []).append(signal.signal_key)
    if not pending:
        return resolved

    rows = connection.execute(
        sa.select(
            opportunity_representation.c.opportunity_key,
            contract_award.c.award_key,
            contract_award.c.awardee_parties,
        )
        .select_from(
            opportunity_representation.join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            )
        )
        .where(opportunity_representation.c.opportunity_key.in_(list(pending)))
        .order_by(opportunity_representation.c.opportunity_key, contract_award.c.award_key)
    ).all()

    for row in rows:
        keys = pending.get(row.opportunity_key)
        if not keys:
            continue
        found = _named_identity(row.awardee_parties)
        if found is None:
            continue
        name, country, identifier = found
        identity = DisplayIdentity(
            name=name,
            country=country,
            identifier_scheme=(identifier or {}).get("scheme"),
            identifier_value=(identifier or {}).get("value"),
            from_award_key=row.award_key,
        )
        for key in keys:
            resolved.setdefault(key, identity)
    return resolved


@dataclasses.dataclass(frozen=True)
class FeedSignal:
    """Un signal du compte, avec la fraîcheur réévaluée au jour de la lecture."""

    signal: StoredSignal
    recency: AwardRecency
    account_id: str
    target_icp_label: str
    #: `None` quand aucune représentation du contrat ne nomme l'attributaire.
    display: DisplayIdentity | None = None

    @property
    def status(self) -> str:
        return self.recency.status

    @property
    def event_date(self) -> dt.date | None:
        """La date de l'horloge qui a décidé du statut — celle que le client lit."""
        clock = policy.STATUS_CLOCK.get(self.status)
        return self.recency.clocks[clock].date if clock else None

    @property
    def sort_key(self) -> tuple[int, int, str]:
        """§5 — pertinence courante, puis date décroissante, puis clé stable.

        Une date absente passe après les dates connues du même rang : elle ne
        peut pas prétendre à une place qu'aucune donnée ne justifie.
        """
        date = self.event_date
        return (
            policy.rank_of(self.status),
            -date.toordinal() if date else 1,
            self.signal.signal_key,
        )

    @property
    def history_date(self) -> dt.date | None:
        """Date factuelle utilisée par le parcours historique."""
        return effective_history_date(self.signal)[0]

    @property
    def history_date_kind(self) -> HistoryDateKind:
        """Horloge factuelle de l'historique, explicitement annoncée."""
        return effective_history_date(self.signal)[1]


@dataclasses.dataclass(frozen=True)
class FeedPage:
    """Une page de feed, et ce qui a été écarté pour l'obtenir."""

    items: tuple[FeedSignal, ...]
    limit: int
    offset: int
    has_more: bool
    #: §17, §31 — vrai quand le plafond de lecture a été atteint. Une troncature
    #: tue reviendrait à dire « voilà tout » alors qu'il en restait.
    scan_truncated: bool
    #: §19 — combien de signaux possédés ont été retirés faute de nom affichable.
    excluded_without_display_name: int
    #: Combien ont été retirés par le mode de fraîcheur demandé.
    excluded_by_freshness: int


@dataclasses.dataclass(frozen=True)
class HistoryFeedPage:
    """One stable keyset page through all persisted awards owned by an account."""

    items: tuple[FeedSignal, ...]
    limit: int
    cursor: str | None
    next_cursor: str | None
    has_more: bool
    scan_truncated: bool
    excluded_without_display_name: int
    excluded_by_filters: int


@dataclasses.dataclass(frozen=True)
class OwnedTargetIcp:
    target_icp_id: str
    label: str
    status: str


#: §25.7 — seul un profil ACTIF alimente un feed. Un brouillon ne produit pas de
#: profil moteur valide (`to_target_icp` refuse), donc rien ne devrait s'y
#: matérialiser ; le feed le vérifie quand même, parce qu'une donnée héritée ou
#: un profil retombé en brouillon ne doit pas continuer à servir des signaux
#: alors que le compte est redevenu `icp_incomplete`.
FEEDING_ICP_STATUS = "active"


class ForeignTargetIcp(LookupError):
    """L'ICP demandé n'appartient pas au compte — ou n'existe pas.

    Une seule exception pour les deux cas : les distinguer dirait au demandeur
    quels identifiants existent ailleurs.
    """


def owned_target_icps(connection: sa.Connection, *, account_id: str) -> dict[str, OwnedTargetIcp]:
    """Les profils du compte, indexés par identifiant. Le point de départ obligé."""
    rows = connection.execute(
        sa.select(target_icp.c.target_icp_id, target_icp.c.label, target_icp.c.status)
        .where(target_icp.c.account_id == account_id)
        .order_by(target_icp.c.created_at, target_icp.c.target_icp_id)
    ).all()
    return {
        row.target_icp_id: OwnedTargetIcp(row.target_icp_id, row.label, row.status) for row in rows
    }


def _ownership_scoped(account_id: str) -> sa.Select:
    """`SIGNAL_SELECT` restreint par une jointure qui PART du profil du compte.

    L'ordre de lecture est inversé par rapport à `SIGNAL_SELECT` : quand le
    plafond de lecture tronque, ce sont les lignes les plus anciennement
    matérialisées qui tombent, jamais les plus fraîches. Il reste total, donc
    deux lectures identiques rendent la même page.
    """
    return (
        SIGNAL_SELECT.join(
            target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
        )
        .where(
            target_icp.c.account_id == account_id,
            target_icp.c.status == FEEDING_ICP_STATUS,
            target_icp.c.plan_limit_code.is_(None),
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        )
        .order_by(None)
        .order_by(materialized_signal.c.materialized_at.desc(), materialized_signal.c.signal_key)
    )


def _date_window(as_of: dt.date, days: int) -> sa.ColumnElement[bool]:
    """La présélection SQL : au moins une des trois horloges dans la fenêtre."""
    floor = as_of - dt.timedelta(days=days)
    return sa.or_(
        contract_award.c.award_date >= floor,
        contract_award.c.contract_notification_date >= floor,
        source_event.c.published_on >= floor,
    )


def _reassess(row: sa.Row, owned: dict[str, OwnedTargetIcp], account_id: str, as_of: dt.date):
    signal = signal_from_row(row)
    profile = owned[signal.target_icp_id]
    return FeedSignal(
        signal=signal,
        recency=signal.current_recency(as_of=as_of),
        account_id=account_id,
        target_icp_label=profile.label,
    )


def feed_page(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    freshness: str = policy.DEFAULT_FRESHNESS,
    target_icp_id: str | None = None,
    #: SPEC-013 §23 — le sous-ensemble d'ICP que le plan autorise à alimenter le
    #: feed. `None` = aucune restriction de plan. La restriction s'ajoute APRÈS
    #: la propriété : elle ne peut pas élargir ce que le compte possède.
    allowed_target_icp_ids: frozenset[str] | None = None,
    primary_event: str | None = None,
    country: str | None = None,
    winner: str | None = None,
    limit: int = policy.DEFAULT_PAGE_SIZE,
    offset: int = 0,
    #: `None` = le plafond du module, relu à CHAQUE appel. Le figer comme valeur
    #: par défaut le capturerait à l'import, et un plafond qu'on ne peut plus
    #: changer est un plafond qu'on ne peut plus tester.
    scan_cap: int | None = None,
) -> FeedPage:
    """Une page du feed de CE compte, à CETTE date.

    `primary_event` filtre sur le type d'événement CLIENT courant : seules les
    trois valeurs de `NEW_OPPORTUNITY_STATUSES` peuvent y correspondre, et un
    signal vieilli n'y répond plus, même s'il a été matérialisé comme neuf.

    `as_of` est obligatoire et sans défaut : aucune horloge n'est lue ici, sinon
    le feed cesserait d'être testable dès le lendemain.
    """
    admitted = policy.statuses_for(freshness)
    scan_cap = policy.CANDIDATE_SCAN_CAP if scan_cap is None else scan_cap
    limit = max(1, min(limit, policy.MAXIMUM_PAGE_SIZE))
    offset = max(0, offset)

    owned = owned_target_icps(connection, account_id=account_id)
    if target_icp_id is not None and target_icp_id not in owned:
        # Un profil d'un AUTRE compte et un profil inexistant se répondent
        # pareil ; un brouillon du compte lui-même, en revanche, existe — il ne
        # rend simplement aucun signal.
        raise ForeignTargetIcp(target_icp_id)
    if not any(profile.status == FEEDING_ICP_STATUS for profile in owned.values()):
        return FeedPage((), limit, offset, False, False, 0, 0)

    query = _ownership_scoped(account_id)
    if target_icp_id is not None:
        query = query.where(materialized_signal.c.target_icp_id == target_icp_id)
    if allowed_target_icp_ids is not None:
        if not allowed_target_icp_ids:
            return FeedPage((), limit, offset, False, False, 0, 0)
        query = query.where(materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)))
    if country is not None:
        query = query.where(source_event.c.source_country == country)
    if winner is not None:
        query = query.where(
            sa.or_(
                materialized_signal.c.winner_identifier_value == winner,
                materialized_signal.c.winner_name == winner,
            )
        )
    window = policy.candidate_window_days(freshness)
    if window is not None:
        query = query.where(_date_window(as_of, window))

    # Une ligne de plus que le plafond : c'est ainsi qu'on SAIT qu'on a tronqué.
    rows = connection.execute(query.limit(scan_cap + 1)).all()
    truncated = len(rows) > scan_cap
    rows = rows[:scan_cap]

    candidates = [_reassess(row, owned, account_id, as_of) for row in rows]
    identities = resolve_display_identity(connection, [item.signal for item in candidates])
    candidates = [
        dataclasses.replace(item, display=identities.get(item.signal.signal_key))
        for item in candidates
    ]

    displayable = [item for item in candidates if item.display is not None]
    without_name = len(candidates) - len(displayable)

    if admitted is not None:
        selected = [item for item in displayable if item.status in admitted]
    else:
        selected = list(displayable)
    if primary_event is not None:
        # CLOSEOUT §3 — le filtre porte sur le type d'événement COURANT, dérivé
        # de la fraîcheur réévaluée. Jamais sur `materialized_primary_event`,
        # qui décrit le jour de la matérialisation, ni sur le raccourci interne
        # qui étiquette une parution ancienne « publication récente ».
        selected = [
            item for item in selected if policy.customer_event_type(item.status) == primary_event
        ]
    dropped = len(displayable) - len(selected)

    selected.sort(key=lambda item: item.sort_key)
    page = selected[offset : offset + limit]
    return FeedPage(
        items=tuple(page),
        limit=limit,
        offset=offset,
        has_more=len(selected) > offset + limit,
        scan_truncated=truncated,
        excluded_without_display_name=without_name,
        excluded_by_freshness=dropped,
    )


HISTORY_SCAN_BATCH = 100
HISTORY_SCAN_CAP = 500


def _history_date_expression() -> sa.ColumnElement[dt.date]:
    return sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
        source_event.c.published_on,
    )


def _history_after(cursor) -> sa.ColumnElement[bool]:
    effective = _history_date_expression()
    if cursor.date is None:
        return sa.and_(
            effective.is_(None),
            materialized_signal.c.signal_key > cursor.signal_key,
        )
    return sa.or_(
        effective < cursor.date,
        sa.and_(
            effective == cursor.date,
            materialized_signal.c.signal_key > cursor.signal_key,
        ),
        effective.is_(None),
    )


def history_page(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    target_icp_id: str | None = None,
    allowed_target_icp_ids: frozenset[str] | None = None,
    limit: int = policy.DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    scan_cap: int = HISTORY_SCAN_CAP,
) -> HistoryFeedPage:
    """Walk the complete owned history by factual date and a stable key.

    Unlike the recent feed, the history order is directly expressible from raw
    source dates.  Keyset pagination can therefore advance through bounded SQL
    batches without freezing the current recency classification.
    """
    if scan_cap < 1:
        raise ValueError("history scan cap must be positive")
    limit = max(1, min(limit, policy.MAXIMUM_PAGE_SIZE))
    decoded = None if cursor is None else decode_history_cursor(cursor)
    owned = owned_target_icps(connection, account_id=account_id)
    if target_icp_id is not None and target_icp_id not in owned:
        raise ForeignTargetIcp(target_icp_id)
    if not any(profile.status == FEEDING_ICP_STATUS for profile in owned.values()):
        return HistoryFeedPage((), limit, cursor, None, False, False, 0, 0)
    if allowed_target_icp_ids is not None and not allowed_target_icp_ids:
        return HistoryFeedPage((), limit, cursor, None, False, False, 0, 0)

    effective = _history_date_expression()
    null_rank = sa.case((effective.is_(None), 1), else_=0)
    base = (
        _ownership_scoped(account_id)
        .order_by(None)
        .order_by(null_rank, effective.desc(), materialized_signal.c.signal_key)
    )
    if target_icp_id is not None:
        base = base.where(materialized_signal.c.target_icp_id == target_icp_id)
    if allowed_target_icp_ids is not None:
        base = base.where(
            materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids))
        )

    selected: list[FeedSignal] = []
    excluded_without_name = 0
    excluded_by_filters = 0
    scanned = 0
    position = decoded
    exhausted = False
    last_returned = None

    while scanned < scan_cap and len(selected) <= limit:
        query = base
        if position is not None:
            query = query.where(_history_after(position))
        batch_limit = min(HISTORY_SCAN_BATCH, scan_cap - scanned)
        rows = connection.execute(query.limit(batch_limit)).all()
        if not rows:
            exhausted = True
            break
        signals = [signal_from_row(row) for row in rows]
        identities = resolve_display_identity(connection, signals)
        for signal in signals:
            current_position = cursor_for_signal(signal)
            position = current_position
            scanned += 1
            display = identities.get(signal.signal_key)
            if display is None:
                excluded_without_name += 1
                continue
            profile = owned[signal.target_icp_id]
            item = FeedSignal(
                signal=signal,
                recency=signal.current_recency(as_of=as_of),
                account_id=account_id,
                target_icp_label=profile.label,
                display=display,
            )
            if len(selected) == limit:
                return HistoryFeedPage(
                    items=tuple(selected),
                    limit=limit,
                    cursor=cursor,
                    next_cursor=encode_history_cursor(last_returned),
                    has_more=True,
                    scan_truncated=False,
                    excluded_without_display_name=excluded_without_name,
                    excluded_by_filters=excluded_by_filters,
                )
            selected.append(item)
            last_returned = current_position
        if len(rows) < batch_limit:
            exhausted = True
            break

    if exhausted:
        next_cursor = None
        has_more = False
        truncated = False
    else:
        next_position = position if position is not None else last_returned
        next_cursor = (
            None if next_position is None else encode_history_cursor(next_position)
        )
        has_more = next_cursor is not None
        truncated = has_more
    return HistoryFeedPage(
        items=tuple(selected),
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
        has_more=has_more,
        scan_truncated=truncated,
        excluded_without_display_name=excluded_without_name,
        excluded_by_filters=excluded_by_filters,
    )


def owned_signal(
    connection: sa.Connection,
    *,
    account_id: str,
    signal_key: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None = None,
) -> FeedSignal | None:
    """Le signal détaillé, si ce compte le possède. `None` sinon — jamais « interdit ».

    Un signal inexistant et un signal d'autrui rendent la même chose : distinguer
    les deux offrirait un annuaire qu'on parcourt clé par clé (§15).
    """
    query = _ownership_scoped(account_id).where(materialized_signal.c.signal_key == signal_key)
    if allowed_target_icp_ids is not None:
        if not allowed_target_icp_ids:
            return None
        query = query.where(materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)))
    row = connection.execute(query).one_or_none()
    if row is None:
        return None
    owned = owned_target_icps(connection, account_id=account_id)
    item = _reassess(row, owned, account_id, as_of)
    identities = resolve_display_identity(connection, [item.signal])
    return dataclasses.replace(
        item,
        display=identities.get(item.signal.signal_key),
        signal=dataclasses.replace(item.signal, evidence=load_evidence(connection, row.award_key)),
    )
