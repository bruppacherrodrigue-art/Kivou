"""L'identité d'une opportunité commerciale — **créée une fois, jamais recalculée**.

    award_key         une REPRÉSENTATION porteuse de faits
                      « l'avis BOAMP 26-79799, lot 1 »
    opportunity_key   le CONTRAT RÉEL montré au client

La distinction n'est pas théorique : SPEC-009E a démontré quatre rapprochements
forts BOAMP × DECP en une seule semaine. Sans elle, un client verrait deux fois
le même marché — une fois « vient de remporter », une fois « vient d'être
notifié ».

    Pourquoi l'identité est PERSISTÉE et non dérivée
    ────────────────────────────────────────────────
    Une version antérieure calculait `opportunity_key = hash(ensemble trié des
    award_key)`. Indépendant de l'ordre, oui — mais seulement si l'ensemble
    complet est connu d'emblée. Il ne l'est jamais :

        jour 1   A arrive          → opportunité = f(A)
        jour 2   B rapproché de A  → opportunité = f(A, B)   ← elle a CHANGÉ

    Le signal aurait été renommé sous les pieds du client. L'identité est donc
    **écrite une fois** dans `opportunity_representation`, puis relue. Attacher
    une représentation tardive ajoute une ligne ; elle ne recalcule rien.

    Ce qui a le droit de réunir deux représentations
    ────────────────────────────────────────────────
    Uniquement un rapprochement **fort** au sens de `france-link-v0.3` : mêmes
    parties, date compatible, au moins un corroborant indépendant du contrat.
    Un `probable` n'a jamais autorisé une fusion de faits.

    Aucune comparaison floue n'existe ici. Pas de similitude de raison sociale,
    pas de score, pas de seuil : un rapprochement que le produit n'a pas déjà
    démontré ne réunit rien.

    Deux opportunités déjà séparées ne fusionnent pas toutes seules
    ──────────────────────────────────────────────────────────────
    Si A appartient à O1, B à O2, et qu'un lien fort apparaît ensuite entre eux,
    le résolveur **lève**. Fusionner reviendrait à réécrire l'identité d'un
    signal déjà servi, et à faire disparaître l'un des deux. La sûreté des faits
    passe avant la déduplication automatique ; un mécanisme de fusion explicite
    pourra traiter le cas si l'usage réel le réclame.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
from collections.abc import Sequence

import sqlalchemy as sa

from signals.domain.awards import ContractAward
from signals.persistence.identity import award_key
from signals.persistence.schema import opportunity_representation

#: Les forces de lien qui autorisent la réunion de deux représentations.
#: Une seule, et c'est délibéré.
COLLAPSIBLE_LINK_STRENGTHS: frozenset[str] = frozenset({"strong"})

_SEPARATOR = "\x1f"


class OpportunityConflict(RuntimeError):
    """Deux opportunités déjà persistées qu'un lien tardif voudrait réunir."""


@dataclasses.dataclass(frozen=True)
class ResolvedOpportunity:
    """Un contrat réel, et les représentations sources qui lui sont rattachées."""

    opportunity_key: str
    representations: tuple[str, ...]
    created: bool

    @property
    def is_cross_source(self) -> bool:
        return len(self.representations) > 1


def opportunity_of(connection: sa.Connection, award_reference: str) -> str | None:
    """L'opportunité à laquelle une représentation est rattachée, ou `None`."""
    return connection.execute(
        sa.select(opportunity_representation.c.opportunity_key).where(
            opportunity_representation.c.award_key == award_reference
        )
    ).scalar_one_or_none()


def _representations(connection: sa.Connection, opportunity_key: str) -> tuple[str, ...]:
    rows = connection.execute(
        sa.select(opportunity_representation.c.award_key)
        .where(opportunity_representation.c.opportunity_key == opportunity_key)
        .order_by(opportunity_representation.c.award_key)
    ).scalars()
    return tuple(rows)


def _new_opportunity_key(award_reference: str) -> str:
    """Une identité neuve, dérivée de la représentation qui la crée.

    Déterministe pour être reproductible, et distincte de l'`award_key` pour
    qu'aucun lecteur ne prenne l'une pour l'autre. Deux bases construites dans
    des ordres d'arrivée différents obtiendront des valeurs différentes — ce qui
    est sans conséquence, l'identité n'ayant de sens qu'à l'intérieur d'une base.
    """
    seed = _SEPARATOR.join(("opportunity", award_reference))
    return "opp_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:36]


def resolve_or_create_opportunity(
    connection: sa.Connection,
    award: ContractAward,
    *,
    now: dt.datetime,
    linked_to: Sequence[ContractAward] = (),
    link_strength: str = "unresolved",
) -> ResolvedOpportunity:
    """Rattache une représentation à son contrat réel, en créant l'identité si besoin.

    Trois cas, dans cet ordre :

        A — la représentation est déjà rattachée   → on rend son opportunité
        B — un lien FORT la relie à une représentation déjà rattachée
                                                   → on l'attache à celle-là
        C — rien n'est encore rattaché             → on crée une identité, une fois

    `linked_to` ne sert qu'à **retrouver** une opportunité existante ; ces
    représentations ne sont pas rattachées ici, car leurs faits n'ont pas
    forcément encore été écrits. Chacune se rattache lors de sa propre
    matérialisation.

    Un lien non fort n'empêche rien : la représentation obtient simplement sa
    propre opportunité, comme n'importe quel marché mono-source.
    """
    reference = award_key(award)
    mine = opportunity_of(connection, reference)

    candidates: set[str] = set()
    if link_strength in COLLAPSIBLE_LINK_STRENGTHS:
        for other in linked_to:
            existing = opportunity_of(connection, award_key(other))
            if existing is not None:
                candidates.add(existing)

    if mine is not None:
        conflicting = candidates - {mine}
        if conflicting:
            raise OpportunityConflict(
                f"réconciliation requise : la représentation {reference} appartient à "
                f"{mine}, et un lien fort la relie à {sorted(conflicting)}. Aucune "
                "fusion automatique n'est faite — les deux opportunités et tous "
                "leurs faits sont conservés."
            )
        return ResolvedOpportunity(mine, _representations(connection, mine), created=False)

    if len(candidates) > 1:
        raise OpportunityConflict(
            f"réconciliation requise : la représentation {reference} est liée fortement "
            f"à plusieurs opportunités déjà distinctes {sorted(candidates)}. Aucune "
            "fusion automatique n'est faite."
        )

    key = next(iter(candidates)) if candidates else _new_opportunity_key(reference)
    connection.execute(
        sa.insert(opportunity_representation).values(
            award_key=reference, opportunity_key=key, created_at=now
        )
    )
    return ResolvedOpportunity(key, _representations(connection, key), created=not candidates)
