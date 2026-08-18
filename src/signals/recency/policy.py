"""La fraîcheur d'une attribution — la seule chose que Kivou promet vraiment.

SPEC-009D a montré l'écart : le moteur filtrait sur `published_at`, la date à
laquelle l'**avis** a paru, pendant que le produit disait « vient de gagner ».
Sur le banc suisse l'écart médian était de huit jours ; sur un quart du feed il
dépassait le mois, et sept signaux sur cent dix étaient publiés frais sur une
attribution vieille de plus de deux mois.

Ce module rend cet écart lisible et opposable. Il ne classe pas un signal :
il constate ce que les dates permettent d'affirmer.

    award_date        quand l'entreprise a réellement obtenu le marché
    publication_date  quand l'avis est devenu public
    discovered_at     quand Kivou l'a appris

Les trois ne sont jamais interchangeables (§6). En particulier, une
`award_date` absente le reste : la remplacer par la date de parution ferait
passer une décision de mai pour une décision du jour (§7). Le module ne reçoit
d'ailleurs aucune date de signature — c'est un autre événement, et l'accepter
ici serait le premier pas vers la confusion que §7 interdit.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Literal

RECENCY_POLICY_VERSION = "award-recency-v0.3"
"""§9 — le seuil est un paramètre versionné, jamais une constante cachée dans l'UI.

v0.2 (R1) ajoute `recently_notified_contract`.

v0.3 (R2) sépare les **horloges**. Jusque-là, les états étaient mutuellement
exclusifs et une décision périmée effaçait une notification fraîche : un marché
attribué il y a quatre-vingt-dix jours et notifié hier ressortait `stale_award`,
et le seul fait commercialement exploitable disparaissait. Les trois horloges
sont désormais évaluées indépendamment, et l'événement produit en est **dérivé**.

`recent_award` garde sa définition au jour près, et garde la priorité : une
notification ne devient jamais une fraîcheur d'attribution.
"""

RECENT_AWARD_DAYS = 30
"""Au-delà, l'entreprise ne « vient » plus de gagner."""

AGING_AWARD_DAYS = 60
"""Frontière haute du feed secondaire (§10). Au-delà, le signal sort des nouveautés."""

RECENT_PUBLICATION_DAYS = 30
"""§12 — une parution au-delà n'est plus une découverte, c'est un fonds d'archive."""

RECENT_NOTIFICATION_DAYS = 30
"""R1 §3 — au-delà, un contrat notifié n'est plus un événement commercial frais.

Aligné sur `RECENT_AWARD_DAYS` sans être le même paramètre : les deux mesurent
des actes différents et pourront diverger sans se contredire."""

PUBLICATION_TOLERANCE_DAYS = 1
"""Un jour d'écart entre décision et parution reste plausible : fuseaux, arrondis.

Au-delà, une attribution postérieure à sa propre publication décrit une source
incohérente, pas un événement.
"""

IMPLAUSIBLE_AWARD_AGE_DAYS = 3650
"""Dix ans. Au-delà, c'est une erreur de saisie, pas un marché ancien.

Deux cas réels ont motivé ce garde-fou : `2002-08-17` publié le 2026-08-18 sur
SIMAP (SPEC-009D), et les remplissages `2000-01-01` / `1970-01-01` que BOAMP
place dans `cac:TenderResult/cbc:AwardDate` sur 96 % de ses avis eForms.
"""

AwardRecencyStatus = Literal[
    "recent_award",
    "aging_award",
    "stale_award",
    "recently_notified_contract",
    "recently_published_award",
    "award_date_unknown",
    "invalid_award_date",
]
"""L'événement **dérivé** — ce que Kivou met en avant pour un signal donné.

Il ne décrit pas l'état d'une horloge : il dit laquelle des trois parle le plus
fort. L'état de chaque horloge se lit sur `ClockAssessment`, et les deux ne se
confondent pas."""

ClockStatus = Literal["recent", "aging", "stale", "unknown", "invalid"]
"""L'état d'UNE horloge, indépendamment des autres.

`unknown` signifie que la source ne publie pas cette date ; `invalid` qu'elle en
publie une que rien ne rend crédible. Les deux sont des faits distincts, et
aucun ne s'emprunte à une autre horloge."""

CLOCKS: tuple[str, ...] = ("award", "notification", "publication")


@dataclasses.dataclass(frozen=True)
class ClockAssessment:
    """Une horloge, son état, sa date brute et son âge — rien d'emprunté ailleurs."""

    clock: str
    status: ClockStatus
    date: dt.date | None
    age_days: int | None
    reason: str

    @property
    def is_recent(self) -> bool:
        return self.status == "recent"

    @property
    def is_dated(self) -> bool:
        """La source publie-t-elle cette date, et est-elle crédible ?"""
        return self.status in {"recent", "aging", "stale"}


#: Les seuls états qui autorisent la formulation « vient de remporter » (§9, §31).
CLAIMABLE_JUST_WON: frozenset[str] = frozenset({"recent_award"})


@dataclasses.dataclass(frozen=True)
class AwardRecency:
    """Le constat temporel d'un signal, avec ses dates brutes conservées.

    Aucune date n'est réécrite, même invalide : `invalid_award_date` garde sa
    valeur d'origine pour que la provenance reste vérifiable (§13).
    """

    status: AwardRecencyStatus
    reason: str
    policy_version: str
    award_clock: ClockAssessment
    notification_clock: ClockAssessment
    publication_clock: ClockAssessment
    award_date: dt.date | None
    contract_notification_date: dt.date | None
    publication_date: dt.date | None
    discovered_at: dt.date | None
    award_age_days: int | None
    notification_age_days: int | None
    publication_age_days: int | None
    publication_delay_days: int | None
    notification_delay_days: int | None
    discovery_delay_from_publication: int | None
    discovery_delay_from_award: int | None

    @property
    def clocks(self) -> dict[str, ClockAssessment]:
        """Les trois horloges, lisibles par nom pour le reporting."""
        return {
            "award": self.award_clock,
            "notification": self.notification_clock,
            "publication": self.publication_clock,
        }

    @property
    def may_claim_just_won(self) -> bool:
        """§31 — la seule porte vers « vient de remporter »."""
        return self.status in CLAIMABLE_JUST_WON

    @property
    def is_datable(self) -> bool:
        """L'attribution porte-t-elle une date de DÉCISION exploitable ?

        `recently_notified_contract` n'en fait pas partie : il est daté, mais par
        un autre acte. Les mélanger reconstituerait exactement la confusion que
        R1 §6 interdit de faire dans les métriques.
        """
        return self.status in {"recent_award", "aging_award", "stale_award"}

    @property
    def is_notification_dated(self) -> bool:
        return self.notification_clock.is_dated

    @property
    def has_recent_notification(self) -> bool:
        """Vrai même quand l'événement mis en avant est une attribution récente."""
        return self.notification_clock.is_recent


def _assess_clock(
    clock: str,
    value: dt.date | None,
    *,
    as_of: dt.date,
    recent_days: int,
    aging_days: int,
    not_after: dt.date | None = None,
    tolerance_days: int = PUBLICATION_TOLERANCE_DAYS,
) -> ClockAssessment:
    """L'état d'une horloge, jugée sur sa seule date.

    Aucune horloge n'emprunte à une autre : c'est ce qui permet à une décision
    périmée et à une notification fraîche de coexister sans que l'une efface
    l'autre (R2 §1). `not_after` sert uniquement à détecter une incohérence
    interne — une décision publiée après sa propre parution — et jamais à
    remplacer une date manquante.
    """
    if value is None:
        return ClockAssessment(
            clock=clock,
            status="unknown",
            date=None,
            age_days=None,
            reason=f"aucune date de {clock} publiée par la source",
        )

    age = (as_of - value).days
    if age < 0:
        return ClockAssessment(
            clock=clock,
            status="invalid",
            date=value,
            age_days=age,
            reason=f"date de {clock} dans le futur ({value.isoformat()})",
        )
    if age > IMPLAUSIBLE_AWARD_AGE_DAYS:
        return ClockAssessment(
            clock=clock,
            status="invalid",
            date=value,
            age_days=age,
            reason=f"âge invraisemblable : {age} jours ({value.isoformat()})",
        )
    if not_after is not None and (value - not_after).days > tolerance_days:
        return ClockAssessment(
            clock=clock,
            status="invalid",
            date=value,
            age_days=age,
            reason=(
                f"date de {clock} postérieure à sa propre publication de "
                f"{(value - not_after).days} jours"
            ),
        )

    status: ClockStatus = (
        "recent" if age <= recent_days else ("aging" if age <= aging_days else "stale")
    )
    return ClockAssessment(
        clock=clock,
        status=status,
        date=value,
        age_days=age,
        reason=f"date de {clock} il y a {age} jours",
    )


#: R2 §1 — l'ordre dans lequel les horloges prennent la parole. Une décision
#: récente prime toujours ; c'est ce qui garantit que `recent_award` n'est pas
#: affaibli par l'ajout de la notification.
def _primary_status(
    award: ClockAssessment,
    notification: ClockAssessment,
    publication: ClockAssessment,
) -> tuple[AwardRecencyStatus, str]:
    if award.is_recent:
        return "recent_award", award.reason
    if notification.is_recent:
        return "recently_notified_contract", notification.reason
    if award.status == "aging":
        return "aging_award", award.reason
    if award.status == "stale":
        return "stale_award", award.reason
    if award.status == "invalid":
        return "invalid_award_date", award.reason
    if publication.is_recent:
        return "recently_published_award", publication.reason
    return "award_date_unknown", "aucune horloge exploitable"


def assess_recency(
    *,
    award_date: dt.date | None,
    contract_notification_date: dt.date | None = None,
    publication_date: dt.date | None = None,
    discovered_at: dt.date | None = None,
    as_of: dt.date,
    recent_award_days: int = RECENT_AWARD_DAYS,
    aging_award_days: int = AGING_AWARD_DAYS,
    recent_publication_days: int = RECENT_PUBLICATION_DAYS,
    recent_notification_days: int = RECENT_NOTIFICATION_DAYS,
) -> AwardRecency:
    """Trois horloges jugées séparément, puis un événement dérivé.

    C'est la correction de R2 §1. Jusqu'en v0.2, les états étaient mutuellement
    exclusifs : un marché attribué il y a quatre-vingt-dix jours et notifié hier
    ressortait `stale_award`, et le seul fait commercialement exploitable était
    perdu. Chaque horloge répond maintenant pour elle-même, et l'événement mis
    en avant se dérive de l'ensemble.

    L'ordre de dérivation dit la doctrine produit :

        décision récente        ce que le client veut vraiment savoir
        notification récente    un acte réel, daté, mais qui n'est pas une victoire
        décision datée          exacte, mais plus une nouveauté
        parution récente        une date sur le document, pas sur l'entreprise
    """
    award = _assess_clock(
        "award",
        award_date,
        as_of=as_of,
        recent_days=recent_award_days,
        aging_days=aging_award_days,
        not_after=publication_date,
    )
    notification = _assess_clock(
        "notification",
        contract_notification_date,
        as_of=as_of,
        recent_days=recent_notification_days,
        aging_days=aging_award_days,
    )
    publication = _assess_clock(
        "publication",
        publication_date,
        as_of=as_of,
        recent_days=recent_publication_days,
        aging_days=aging_award_days,
    )
    status, reason = _primary_status(award, notification, publication)

    publication_delay = (
        (publication_date - award_date).days if award_date and publication_date else None
    )
    notification_delay = (
        (publication_date - contract_notification_date).days
        if contract_notification_date and publication_date
        else None
    )
    return AwardRecency(
        status=status,
        reason=reason,
        policy_version=RECENCY_POLICY_VERSION,
        award_clock=award,
        notification_clock=notification,
        publication_clock=publication,
        award_date=award_date,
        contract_notification_date=contract_notification_date,
        publication_date=publication_date,
        discovered_at=discovered_at,
        award_age_days=award.age_days,
        notification_age_days=notification.age_days,
        publication_age_days=publication.age_days,
        publication_delay_days=publication_delay,
        notification_delay_days=notification_delay,
        discovery_delay_from_publication=(
            (discovered_at - publication_date).days if discovered_at and publication_date else None
        ),
        discovery_delay_from_award=(
            (discovered_at - award_date).days if discovered_at and award_date else None
        ),
    )
