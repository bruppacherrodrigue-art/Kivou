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
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.domain.french_departments import location_subdivision
from signals.engagement.status import UNIFIED_STATUSES
from signals.feed import policy
from signals.feed.history import (
    HistoryDateKind,
    cursor_for_signal,
    decode_history_cursor,
    effective_history_date,
    encode_history_cursor,
)
from signals.feed.text import normalize_text
from signals.persistence.repository import (
    SIGNAL_SELECT,
    StoredSignal,
    load_evidence,
    signal_from_row,
)
from signals.persistence.schema import (
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.personalization.for_you import POLICY_VERSION
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
    for_you_sentence: str | None = None
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
    #: Les quatre statuts unifiés, comptés sur l'ensemble sélectionné AVANT le
    #: filtre de statut. Toujours les quatre clés, même à zéro.
    status_counts: dict[str, int] = dataclasses.field(
        default_factory=lambda: {status: 0 for status in UNIFIED_STATUSES}
    )
    #: Vrai quand le balayage QUI ALIMENTE `status_counts` s'est arrêté sur le
    #: plafond avant d'épuiser les candidats — distinct de `scan_truncated`,
    #: qui parle de la LISTE rendue, pas du dénombrement.
    counts_truncated: bool = False
    #: Combien d'items par ailleurs admissibles ont été écartés par le filtre
    #: de statut unifié (`?status=`) — comptés APRÈS `status_counts`.
    excluded_by_status: int = 0
    #: Toujours vrai ici : la vue Récentes relit l'ensemble sélectionné à chaque
    #: appel, donc elle compte toujours. Le champ existe pour que la réponse
    #: publique ait la MÊME forme que celle de l'historique, qui ne compte, lui,
    #: que sur la première page.
    counts_available: bool = True
    #: Fix round 2 (F1) — l'ensemble sélectionné ENTIER, après `admit`,
    #: `published_since`, le filtre de statut et le tri, mais AVANT la découpe
    #: en page. Un agrégat (le tableau de bord) doit compter et classer sur
    #: TOUT ce que le compte possède, pas sur les cinquante premiers items
    #: qu'une page rend : lire `items` pour compter plafonnait silencieusement
    #: chaque nombre à `MAXIMUM_PAGE_SIZE`.
    matched: tuple[FeedSignal, ...] = ()
    #: PR2b tâche 3 — combien de candidats par ailleurs affichables ont été
    #: écartés par `subdivision_code` ou `q`, AVANT d'occuper une place du
    #: plafond de candidats : exactement le rôle que joue déjà ce compteur en
    #: historique.
    excluded_by_filters: int = 0


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
    #: Les quatre statuts unifiés, comptés sur l'ensemble sélectionné AVANT le
    #: filtre de statut. Toujours les quatre clés, même à zéro. Le balayage qui
    #: les alimente continue au-delà de la page pleine, jusqu'à `scan_cap` ou
    #: épuisement — les compteurs ne dépendent donc jamais de `limit`.
    status_counts: dict[str, int] = dataclasses.field(
        default_factory=lambda: {status: 0 for status in UNIFIED_STATUSES}
    )
    #: Vrai quand ce balayage prolongé s'est arrêté sur `scan_cap` avant
    #: d'épuiser les candidats — distinct de `scan_truncated`, qui parle de la
    #: LISTE rendue (pagination), pas du dénombrement.
    counts_truncated: bool = False
    #: Combien d'items par ailleurs admissibles ont été écartés par le filtre
    #: de statut unifié (`?status=`) — comptés APRÈS `status_counts`.
    excluded_by_status: int = 0
    #: Fix round 2 (F7/F8) — `status_counts` n'est calculé que sur la PREMIÈRE
    #: page (`cursor is None`). Ailleurs, les compteurs restent à zéro et ce
    #: drapeau le dit : un dénombrement qui repart du curseur ne compterait que
    #: la queue de l'historique, donc un nombre DIFFÉRENT à chaque page — pire
    #: qu'une absence, puisque le client ne pourrait pas le savoir.
    counts_available: bool = True


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
    persisted_for_you = (
        sa.select(for_you_sentence.c.sentence)
        .where(
            for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
            for_you_sentence.c.target_icp_id == target_icp.c.target_icp_id,
            for_you_sentence.c.signal_fingerprint
            == materialized_signal.c.content_fingerprint,
            for_you_sentence.c.policy_version == POLICY_VERSION,
        )
        .order_by(for_you_sentence.c.created_at.desc())
        .limit(1)
        .correlate(materialized_signal, target_icp)
        .scalar_subquery()
    )
    return (
        SIGNAL_SELECT.add_columns(persisted_for_you.label("for_you_sentence")).join(
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


RECENT_SCAN_BATCH = 200
"""Lignes relues par lot dans la vue Récentes, avant résolution d'identité."""

RECENT_SCAN_ROW_FACTOR = 10
"""Plafond absolu de lignes lues = `scan_cap × RECENT_SCAN_ROW_FACTOR`.

Le plafond `CANDIDATE_SCAN_CAP` compte les candidats AFFICHABLES : une
notification DECP sans dénomination sociale ne doit pas consommer la place d'un
signal nommé matérialisé avant elle (staging, 2026-09-02 : 491 lignes sans nom
pour 8 rendues). Le coût reste borné par ce second plafond, et son dépassement
est annoncé comme n'importe quelle troncature.
"""


def _date_window(as_of: dt.date, days: int) -> sa.ColumnElement[bool]:
    """La présélection SQL : au moins une des trois horloges dans la fenêtre."""
    floor = as_of - dt.timedelta(days=days)
    return sa.or_(
        contract_award.c.award_date >= floor,
        contract_award.c.contract_notification_date >= floor,
        source_event.c.published_on >= floor,
    )


#: Mirrors `feed.factual_display._MAX_OBJECT_LENGTH` — kept in sync manually
#: rather than imported : `factual_display` imports `FeedSignal` from this
#: module, so the reverse import would be a cycle.
_TEXT_OBJECT_LIMIT = 180


def _object_short(title: str | None) -> str | None:
    """Le même objet court que `factual_display.object_short` — nettoyé, tronqué."""
    if not title:
        return None
    cleaned = " ".join(title.split())
    if not cleaned:
        return None
    if len(cleaned) > _TEXT_OBJECT_LIMIT:
        return f"{cleaned[: _TEXT_OBJECT_LIMIT - 1].rstrip()}…"
    return cleaned


def _text_haystack(signal: StoredSignal, display: DisplayIdentity | None) -> list[str]:
    """§28.3bis — le nom affiché, le titre publié et l'objet court qui en dérive.

    Jamais l'identifiant, jamais l'acheteur : `q` cherche l'affaire telle
    qu'un commercial la lirait, pas un numéro interne.
    """
    parts: list[str] = []
    if display is not None and display.name:
        parts.append(display.name)
    title = signal.award.title
    if title:
        parts.append(title)
        short = _object_short(title)
        if short is not None:
            parts.append(short)
    return parts


def _matches_text_query(signal: StoredSignal, display: DisplayIdentity | None, needle: str) -> bool:
    return any(needle in normalize_text(part) for part in _text_haystack(signal, display))


def _reassess(row: sa.Row, owned: dict[str, OwnedTargetIcp], account_id: str, as_of: dt.date):
    signal = signal_from_row(row)
    profile = owned[signal.target_icp_id]
    return FeedSignal(
        signal=signal,
        recency=signal.current_recency(as_of=as_of),
        account_id=account_id,
        target_icp_label=profile.label,
        for_you_sentence=row.for_you_sentence,
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
    #: PR2b tâche 3 — même sémantique que dans `history_page` : comparé à la
    #: subdivision DÉRIVÉE (`location_subdivision`), jamais à une valeur brute
    #: éventuellement absente. Filtre Python, appliqué candidat par candidat.
    subdivision_code: str | None = None,
    #: PR2b tâche 3 — `contract_award.cpv_main LIKE 'préfixe%'`, en SQL comme en
    #: historique.
    cpv_prefix: str | None = None,
    #: PR2b tâche 3 — bornes sur la même expression que `history_page`
    #: (`_history_date_expression` : décision, sinon notification, sinon
    #: parution), en SQL.
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    #: PR2b tâche 3 — `contract_award.amount >= min_amount`, en SQL. Un montant
    #: absent (`NULL`) n'y répond jamais : `NULL >= x` n'est vrai pour aucun
    #: `x` en SQL, la ligne est donc exclue sans code supplémentaire.
    min_amount: Decimal | None = None,
    #: PR2b tâche 3 — recherche plein texte, insensible casse et accents, sur
    #: le nom d'attributaire affiché, `award.title` et l'objet court qui en
    #: dérive (`factual_display.object_short`). Filtre Python : il a besoin de
    #: l'identité affichable, résolue après lecture.
    text_query: str | None = None,
    winner: str | None = None,
    limit: int = policy.DEFAULT_PAGE_SIZE,
    offset: int = 0,
    #: `None` = le plafond du module, relu à CHAQUE appel. Le figer comme valeur
    #: par défaut le capturerait à l'import, et un plafond qu'on ne peut plus
    #: changer est un plafond qu'on ne peut plus tester.
    scan_cap: int | None = None,
    #: `signal_key -> statut unifié`. `None` = tout compte comme `new` et aucun
    #: filtre de statut ne s'applique.
    status_of: Callable[[str], str] | None = None,
    #: `None` = pas de filtre de statut ; sinon les statuts admis dans la page.
    statuses: frozenset[str] | None = None,
    #: Fix round 1 (C1/I1) — le droit du PLAN, appliqué APRÈS la propriété et la
    #: fraîcheur, AVANT `status_counts` et le filtre de statut : un compte non
    #: payant sans déblocage Discovery ne doit voir ni item, ni compte, ni carte
    #: pour un signal que `access.is_unlocked` refuse. `None` = aucune
    #: restriction (usage interne uniquement — aucune route publique ne doit
    #: omettre ce paramètre).
    admit: Callable[[FeedSignal], bool] | None = None,
    #: Fix round 1 (I2) — présélection par date de PARUTION, dans la MÊME portée
    #: que le feed (propriété, identité affichable, droit du plan). `None` =
    #: aucune borne. Un signal sans `published_on` n'y répond jamais.
    published_since: dt.date | None = None,
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
    if cpv_prefix is not None:
        query = query.where(contract_award.c.cpv_main.like(f"{cpv_prefix}%"))
    if date_from is not None or date_to is not None:
        effective = _history_date_expression()
        if date_from is not None:
            query = query.where(effective >= date_from)
        if date_to is not None:
            query = query.where(effective <= date_to)
    if min_amount is not None:
        query = query.where(contract_award.c.amount >= min_amount)
    window = policy.candidate_window_days(freshness)
    if window is not None:
        query = query.where(_date_window(as_of, window))
    if published_since is not None:
        # Fix round 2 (F3) — la borne de parution est aussi une PRÉSÉLECTION.
        # Filtrée en Python seulement, elle laissait les signaux hors fenêtre
        # consommer le plafond de candidats : mille parutions anciennes
        # matérialisées ce matin suffisaient à faire rendre zéro à une fenêtre
        # de sept jours pourtant peuplée. Le garde Python reste en place — il
        # est la définition, celle-ci n'en est que l'accélérateur.
        query = query.where(source_event.c.published_on >= published_since)

    #: PR2b tâche 3 — normalisé une seule fois, pas à chaque candidat.
    needle = normalize_text(text_query) if text_query is not None else None

    row_ceiling = scan_cap * RECENT_SCAN_ROW_FACTOR
    rows_read = 0
    displayable: list[FeedSignal] = []
    without_name = 0
    excluded_by_filters = 0
    truncated = False
    # §31 — un curseur de clé plutôt qu'un `OFFSET` : l'ordre de
    # `_ownership_scoped` est total (`materialized_at DESC, signal_key ASC`),
    # donc chaque lot repart exactement où le précédent s'est arrêté. Un
    # `OFFSET` relirait et jetterait toutes les lignes déjà vues à chaque lot,
    # ce qui fait rejouer l'intégralité de la jointure au dernier appel.
    last_at: dt.datetime | None = None
    last_key: str | None = None
    while True:
        batch_limit = min(RECENT_SCAN_BATCH, row_ceiling - rows_read)
        batch_query = query
        if last_key is not None:
            batch_query = batch_query.where(
                sa.or_(
                    materialized_signal.c.materialized_at < last_at,
                    sa.and_(
                        materialized_signal.c.materialized_at == last_at,
                        materialized_signal.c.signal_key > last_key,
                    ),
                )
            )
        # Une ligne de plus que le lot : c'est ainsi qu'on SAIT s'il en reste.
        rows = connection.execute(batch_query.limit(batch_limit + 1)).all()
        more_rows = len(rows) > batch_limit
        rows = rows[:batch_limit]
        rows_read += len(rows)
        if rows:
            last_row = rows[-1]
            last_at = last_row.materialized_at
            last_key = last_row.signal_key
        candidates = [_reassess(row, owned, account_id, as_of) for row in rows]
        identities = resolve_display_identity(connection, [item.signal for item in candidates])
        for item in candidates:
            display = identities.get(item.signal.signal_key)
            if display is None:
                without_name += 1
                continue
            # PR2b tâche 3 — `subdivision_code` et `q` sont des filtres Python
            # (le premier dérive d'un JSON, le second a besoin de l'identité
            # affichable). Comme `subdivision_code` en historique, ils
            # s'appliquent AVANT que le candidat n'occupe une place du plafond
            # de candidats affichables : sinon, un candidat qu'ils écartent
            # consommerait quand même la place d'un candidat qui, lui, passe.
            place = item.signal.award.place_of_performance or {}
            if (
                subdivision_code is not None
                and location_subdivision(place) != subdivision_code
            ) or (needle is not None and not _matches_text_query(item.signal, display, needle)):
                excluded_by_filters += 1
                continue
            if len(displayable) == scan_cap:
                truncated = True
                break
            displayable.append(dataclasses.replace(item, display=display))
        if truncated or not more_rows:
            break
        if rows_read >= row_ceiling:
            truncated = True
            break

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

    # Fix round 1 (C1/I1/I2) — droit du plan puis fenêtre de parution, APRÈS la
    # fraîcheur et AVANT `status_counts` : ni les compteurs, ni la page, ni le
    # filtre de statut (`?status=`) ne doivent jamais voir un item que le plan
    # refuse ou qu'une fenêtre de lecture exclut.
    if admit is not None:
        selected = [item for item in selected if admit(item)]
    if published_since is not None:
        selected = [
            item
            for item in selected
            if item.signal.event.published_on is not None
            and item.signal.event.published_on >= published_since
        ]

    resolver = status_of or (lambda _signal_key: "new")
    status_counts = {status: 0 for status in UNIFIED_STATUSES}
    for item in selected:
        status_counts[resolver(item.signal.signal_key)] += 1
    excluded_by_status = 0
    if statuses is not None:
        admitted_by_status = []
        for item in selected:
            if resolver(item.signal.signal_key) in statuses:
                admitted_by_status.append(item)
            else:
                excluded_by_status += 1
        selected = admitted_by_status

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
        status_counts=status_counts,
        counts_truncated=truncated,
        excluded_by_status=excluded_by_status,
        matched=tuple(selected),
        excluded_by_filters=excluded_by_filters,
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
    primary_event: str | None = None,
    country: str | None = None,
    subdivision_code: str | None = None,
    status: str | None = None,
    cpv_prefix: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    #: PR2b tâche 3 — `contract_award.amount >= min_amount`, en SQL. Un montant
    #: absent exclut la ligne, comme dans `feed_page`.
    min_amount: Decimal | None = None,
    #: PR2b tâche 3 — même filtre plein texte que `feed_page`, même portée
    #: (nom affiché, `award.title`, objet court).
    text_query: str | None = None,
    winner: str | None = None,
    limit: int = policy.DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    #: `None` = le plafond du module, relu à CHAQUE appel — comme `feed_page`.
    #: Le figer comme valeur par défaut le capturerait à l'import, et un
    #: plafond qu'on ne peut plus changer est un plafond qu'on ne peut plus
    #: tester.
    scan_cap: int | None = None,
    #: `signal_key -> statut unifié`. `None` = tout compte comme `new` et aucun
    #: filtre de statut ne s'applique.
    status_of: Callable[[str], str] | None = None,
    #: `None` = pas de filtre de statut ; sinon les statuts admis dans la page.
    statuses: frozenset[str] | None = None,
) -> HistoryFeedPage:
    """Walk the complete owned history by factual date and a stable key.

    Unlike the recent feed, the history order is directly expressible from raw
    source dates.  Keyset pagination can therefore advance through bounded SQL
    batches without freezing the current recency classification.

    Fix round 2 (F7/F8) — `status_counts` n'est calculé QUE sur la première
    page (`cursor is None`), et `counts_available` le dit. Le balayage prolongé
    qui les alimente ne tourne donc qu'une fois par parcours, au lieu de relire
    tout l'historique à chaque page. Repartir du curseur ne compterait que la
    queue restante : le même parcours rendrait des compteurs décroissants,
    c'est-à-dire faux. Une fois la page pleine ET un item admis vu derrière
    elle (la preuve exacte que `has_more` exige), le balayage s'arrête : ni
    `has_more`, ni `next_cursor`, ni `scan_truncated` n'en changent.
    """
    scan_cap = HISTORY_SCAN_CAP if scan_cap is None else scan_cap
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
    if country is not None:
        base = base.where(source_event.c.source_country == country)
    if winner is not None:
        base = base.where(
            sa.or_(
                materialized_signal.c.winner_identifier_value == winner,
                materialized_signal.c.winner_name == winner,
            )
        )
    if cpv_prefix is not None:
        base = base.where(contract_award.c.cpv_main.like(f"{cpv_prefix}%"))
    if date_from is not None:
        base = base.where(effective >= date_from)
    if date_to is not None:
        base = base.where(effective <= date_to)
    if min_amount is not None:
        base = base.where(contract_award.c.amount >= min_amount)

    #: PR2b tâche 3 — normalisé une seule fois, pas à chaque candidat.
    needle = normalize_text(text_query) if text_query is not None else None

    selected: list[FeedSignal] = []
    excluded_without_name = 0
    excluded_by_filters = 0
    excluded_by_status = 0
    status_counts = {status: 0 for status in UNIFIED_STATUSES}
    resolver = status_of or (lambda _signal_key: "new")
    scanned = 0
    position = decoded
    exhausted = False
    last_returned = None
    #: Fix round 2 (F7/F8) — seule la première page compte. Les pages suivantes
    #: rendent les quatre clés à zéro, et l'annoncent.
    counts_available = cursor is None
    #: Vrai quand le balayage s'est arrêté de lui-même, page pleine et
    #: `found_more` acquis, sans avoir touché `scan_cap` : ce n'est PAS une
    #: troncature, c'est un travail terminé plus tôt.
    stopped_early = False
    #: §2 (fix round 1) — vrai dès qu'un item ADMIS (tous les filtres, statut
    #: compris) est rencontré APRÈS que la page a atteint `limit`. C'est la
    #: seule preuve directe qu'une page suivante rendrait quelque chose : une
    #: page exactement pleine, sans rien d'admissible derrière, reste
    #: `has_more = False`.
    found_more = False

    while scanned < scan_cap:
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
            place = signal.award.place_of_performance or {}
            if (
                (
                    subdivision_code is not None
                    and location_subdivision(place) != subdivision_code
                )
                or (status is not None and item.status != status)
                or (
                    primary_event is not None
                    and policy.customer_event_type(item.status) != primary_event
                )
                or (needle is not None and not _matches_text_query(signal, display, needle))
            ):
                excluded_by_filters += 1
                continue
            # §2 (fix round 1) — sur la PREMIÈRE page, le dénombrement continue
            # même une fois la page pleine : arrêter ici ferait dépendre
            # `counts` de `limit`, ce que la spec interdit explicitement.
            unified = resolver(signal.signal_key)
            if counts_available:
                status_counts[unified] += 1
            if statuses is not None and unified not in statuses:
                excluded_by_status += 1
                continue
            if len(selected) < limit:
                selected.append(item)
                last_returned = current_position
            else:
                # Cet item aurait été retenu ; il ne l'est pas faute de place,
                # mais sa seule existence prouve qu'une page suivante rendrait
                # quelque chose. Ni lui ni ses successeurs ne déplacent
                # `last_returned` : la page suivante doit le revoir.
                found_more = True
                if not counts_available:
                    # Rien ne reste à apprendre : la page est pleine et
                    # `has_more` est acquis. Continuer relirait l'historique
                    # pour des compteurs que cette page ne rendra pas.
                    stopped_early = True
                    break
        if stopped_early:
            break
        if len(rows) < batch_limit:
            exhausted = True
            break

    if exhausted:
        # Tout l'historique possédé (sous les filtres donnés) a été vu : la
        # seule preuve qu'il resterait quelque chose est un item ADMIS
        # rencontré après que la page a atteint `limit` — `found_more`. Sans
        # cela, une page exactement pleine reste `has_more = False` : rien de
        # plus n'existe, inutile de le faire deviner au client.
        has_more = found_more
        next_cursor = encode_history_cursor(last_returned) if found_more else None
    else:
        # §2 (fix round 2) — le plafond `scan_cap` a été atteint AVANT
        # d'épuiser les candidats : on IGNORE s'il en reste au-delà, donc on
        # reste conservateur (`has_more = True`, comme avant le round 1) pour
        # ne jamais couper l'accès au reste de l'historique. Le curseur avance
        # au dernier item RENDU si la page est pleine (pour que l'item qui a
        # débordé soit revu), sinon à la dernière position SCANNÉE — c'est le
        # comportement d'origine, restauré après que le round 1 l'a cassé en
        # aliasant `has_more` sur `found_more` dans les deux branches.
        has_more = True
        if len(selected) == limit:
            next_cursor = encode_history_cursor(last_returned)
        elif position is not None:
            next_cursor = encode_history_cursor(position)
        else:  # pragma: no cover - un balayage qui progresse a toujours une position
            next_cursor = encode_history_cursor(last_returned) if last_returned else None
    #: Le sens ORIGINAL de `scan_truncated` : le balayage (page ET
    #: dénombrement) s'est arrêté sur `scan_cap` avant d'épuiser les
    #: candidats. Un arrêt VOLONTAIRE (`stopped_early`) n'en est pas un : la
    #: page est complète et son curseur mène au reste.
    scan_truncated = not exhausted and not stopped_early
    return HistoryFeedPage(
        items=tuple(selected),
        limit=limit,
        cursor=cursor,
        next_cursor=next_cursor,
        has_more=has_more,
        scan_truncated=scan_truncated,
        excluded_without_display_name=excluded_without_name,
        excluded_by_filters=excluded_by_filters,
        status_counts=status_counts,
        counts_truncated=scan_truncated and counts_available,
        excluded_by_status=excluded_by_status,
        counts_available=counts_available,
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
