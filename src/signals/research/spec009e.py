"""SPEC-009E — mesurer ce que la France permet réellement de promettre.

SPEC-009D a établi la question : Kivou dit « vient de remporter » et filtrait
sur la date de parution de l'avis. La réponse suisse était confortable —
`award_date` publiée sur 100 % des avis SIMAP, huit jours de délai médian. La
question française restait ouverte.

Ce module est l'instrument de mesure, pas la mesure. Il ne décide rien : il
compte des faits sur des award-lots déjà convertis au modèle canonique par les
adapters, et laisse la politique de fraîcheur trancher les statuts.

Toutes les fonctions sont pures et hors ligne. L'acquisition vit dans
`spec009e_run.py`, ce qui rend ces mesures rejouables sur un corpus gelé.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any

from signals.recency import IMPLAUSIBLE_AWARD_AGE_DAYS, assess_recency

TARGET_FRANCE_SAMPLE = 100
"""§27 — la cible : cent award-lots français."""

MINIMUM_FRANCE_SAMPLE = 50
"""§27 — en dessous, l'échantillon ne porte plus de conclusion."""

NOTIFICATION_AGE_BUCKETS: tuple[int, ...] = (7, 30, 60, 90)
"""R1 §4 — les fenêtres cumulatives demandées pour la fraîcheur de notification."""

#: Les faits inventoriés par §28, dans l'ordre où ils se lisent.
INVENTORIED_FACTS: tuple[str, ...] = (
    "winner_name",
    "winner_siret",
    "buyer_name",
    "buyer_siret",
    "amount",
    "currency",
    "cpv",
    "award_date",
    "publication_date",
    "contract_signature_date",
    "contract_notification_date",
    "lot",
    "procedure_id",
    "contract_id",
    "place_known",
)


@dataclasses.dataclass(frozen=True)
class AwardFacts:
    """Ce qu'un award-lot porte réellement, réduit à ce que §28 demande de compter.

    Volontairement plat : l'inventaire doit rester lisible à côté du tableau
    qu'il produit, et rien ici ne doit pouvoir masquer une absence derrière une
    valeur par défaut.
    """

    signal_key: str
    source: str
    notice: str
    award_date: dt.date | None
    publication_date: dt.date | None
    contract_signature_date: dt.date | None
    contract_notification_date: dt.date | None
    winner_name: str | None
    winner_siret: str | None
    buyer_name: str | None
    buyer_siret: str | None
    amount: str | None
    currency: str | None
    cpv: str | None
    lot: str | None
    procedure_id: str | None
    contract_id: str | None
    place_known: bool


def _known(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return value is not None and value != ""


def fact_coverage(sample: Sequence[AwardFacts]) -> dict[str, dict[str, Any]]:
    """§28 — combien d'award-lots portent chaque fait, sur l'échantillon entier.

    Le dénominateur est toujours la taille de l'échantillon : rapporter une
    couverture sur les seules valeurs présentes rendrait toute source parfaite.
    """
    total = len(sample)
    coverage: dict[str, dict[str, Any]] = {}
    for field in INVENTORIED_FACTS:
        known = sum(1 for facts in sample if _known(getattr(facts, field)))
        coverage[field] = {
            "n": total,
            "known": known,
            "known_pct": round(100 * known / total, 1) if total else None,
        }
    return coverage


def recency_breakdown(sample: Sequence[AwardFacts], *, as_of: dt.date) -> dict[str, Any]:
    """§26 — la répartition des statuts de fraîcheur, award-lot par award-lot.

    C'est la politique de `signals.recency` qui tranche, pas ce module : une
    seconde règle de fraîcheur écrite ici finirait par diverger de la première.
    """
    statuses: collections.Counter[str] = collections.Counter()
    ages: list[int] = []
    for facts in sample:
        recency = assess_recency(
            award_date=facts.award_date,
            contract_notification_date=facts.contract_notification_date,
            publication_date=facts.publication_date,
            as_of=as_of,
        )
        statuses[recency.status] += 1
        if recency.is_datable and recency.award_age_days is not None:
            ages.append(recency.award_age_days)
    total = len(sample)
    return {
        "n": total,
        "statuses": dict(statuses),
        "recent_award_pct": round(100 * statuses["recent_award"] / total, 1) if total else None,
        "claimable_just_won": statuses["recent_award"],
        "award_age_days": _summary(ages),
    }


def notification_breakdown(sample: Sequence[AwardFacts], *, as_of: dt.date) -> dict[str, Any]:
    """R1 §4 — combien de contrats ont été notifiés dans chaque fenêtre.

    Les fenêtres sont **cumulatives** : « ≤ 30 jours » contient « ≤ 7 jours ».
    C'est la forme qu'une décision produit lit — « combien puis-je annoncer
    cette semaine, ce mois » — et non une partition en tranches disjointes.

    Cette mesure vit à part de `recency_breakdown` parce qu'elle décrit un
    **autre acte**. Les additionner reconstituerait la confusion que R1 §6
    interdit explicitement.
    """
    ages = [
        (as_of - facts.contract_notification_date).days
        for facts in sample
        if facts.contract_notification_date is not None
    ]
    plausible = [age for age in ages if 0 <= age <= IMPLAUSIBLE_AWARD_AGE_DAYS]
    return {
        "n": len(sample),
        "known": len(ages),
        "known_pct": round(100 * len(ages) / len(sample), 1) if sample else None,
        "within": {
            str(bucket): sum(1 for age in plausible if age <= bucket)
            for bucket in NOTIFICATION_AGE_BUCKETS
        },
        "notification_age_days": _summary(plausible),
    }


def notification_delay_summary(sample: Sequence[AwardFacts]) -> dict[str, Any]:
    """Le délai entre la notification et la publication de la donnée ouverte."""
    delays = [
        (facts.publication_date - facts.contract_notification_date).days
        for facts in sample
        if facts.contract_notification_date and facts.publication_date
    ]
    return _summary(delays)


def publication_delay_summary(sample: Sequence[AwardFacts]) -> dict[str, Any]:
    """§26 — le délai entre décision et parution, sur les seuls award-lots datés."""
    delays = [
        (facts.publication_date - facts.award_date).days
        for facts in sample
        if facts.award_date and facts.publication_date
    ]
    return _summary(delays)


def _summary(values: Sequence[int]) -> dict[str, Any]:
    """Percentiles par rang le plus proche — cohérent avec l'audit SPEC-009D."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def rank(pct: float) -> int:
        return ordered[max(0, math.ceil(pct * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "p25": rank(0.25),
        "median": rank(0.50),
        "p75": rank(0.75),
        "p90": rank(0.90),
        "max": ordered[-1],
    }


def sample_verdict(award_lots: int) -> str:
    """§27 — l'échantillon porte-t-il une conclusion ?"""
    if award_lots >= TARGET_FRANCE_SAMPLE:
        return "target reached"
    if award_lots >= MINIMUM_FRANCE_SAMPLE:
        return "minimum reached, documented shortfall"
    return "insufficient sample"


def payload_form_counts(records: Iterable[dict]) -> dict[str, int]:
    """§21 — ce qui est écarté doit être compté, sinon le taux de couverture ment."""
    from signals.connectors.boamp import payload_kind

    return dict(collections.Counter(payload_kind(record) for record in records))


def award_facts(event: Any, award: Any, *, source: str) -> AwardFacts:
    """Un award-lot canonique → la ligne plate que l'inventaire compte.

    Fonctionne indifféremment sur un avis BOAMP et sur un contrat DECP : c'est
    tout l'intérêt d'avoir gardé un seul modèle canonique. Les deux sources
    remplissent des colonnes différentes, et c'est précisément ce que la mesure
    doit rendre visible.
    """
    winners = [member for party in award.awardee_parties for member in party.members]
    winner = winners[0].organization if winners else None
    buyer = event.procedure_buyers[0] if event.procedure_buyers else None

    def siret(organization: Any) -> str | None:
        if organization is None:
            return None
        for identifier in organization.identifiers:
            if identifier.scheme == "SIRET":
                return identifier.value
        return None

    def named(organization: Any) -> str | None:
        """Le nom, seulement s'il en est un.

        DECP ne publie aucune raison sociale : l'adapter y place l'identifiant
        en guise de désignation. Le compter comme un nom ferait croire à une
        couverture de 100 % là où il n'y en a aucune.
        """
        if organization is None:
            return None
        name = organization.legal_name
        identifiers = {identifier.value for identifier in organization.identifiers}
        return None if name in identifiers else name

    published = event.published_at
    publication_date = published.date() if isinstance(published, dt.datetime) else published
    return AwardFacts(
        signal_key=f"{source}:{event.provenance.source_notice_id}:{award.source_award_id or ''}"
        f":{award.lot.identifier if award.lot else ''}",
        source=source,
        notice=event.provenance.source_notice_id,
        award_date=award.award_date,
        publication_date=publication_date,
        contract_signature_date=award.contract_signature_date,
        contract_notification_date=award.contract_notification_date,
        winner_name=named(winner),
        winner_siret=siret(winner),
        buyer_name=named(buyer),
        buyer_siret=siret(buyer),
        amount=str(award.value.amount) if award.value else None,
        currency=award.value.currency if award.value else None,
        cpv=award.cpv_main.code if award.cpv_main else None,
        lot=award.lot.identifier if award.lot else None,
        procedure_id=event.provenance.source_procedure_id,
        contract_id=award.source_award_id,
        place_known=award.place_of_performance is not None,
    )


def customer_facing_identity(sample: Sequence[AwardFacts]) -> dict[str, Any]:
    """R1 §6.C — combien d'événements portent de quoi désigner l'entreprise.

    Un signal client a besoin de savoir **à qui** il parle. Un nom sans
    identifiant se prospecte ; un identifiant sans nom se résout auprès d'un
    registre. Aucun des deux ne se déduit de rien.
    """
    total = len(sample)
    named = sum(1 for facts in sample if facts.winner_name)
    identified = sum(1 for facts in sample if facts.winner_siret)
    either = sum(1 for facts in sample if facts.winner_name or facts.winner_siret)
    both = sum(1 for facts in sample if facts.winner_name and facts.winner_siret)
    return {
        "n": total,
        "named": named,
        "identified": identified,
        "named_or_identified": either,
        "named_and_identified": both,
        "named_pct": round(100 * named / total, 1) if total else None,
        "identified_pct": round(100 * identified / total, 1) if total else None,
        "named_or_identified_pct": round(100 * either / total, 1) if total else None,
    }


def as_dict(facts: AwardFacts) -> dict[str, Any]:
    payload = dataclasses.asdict(facts)
    for key, value in payload.items():
        if isinstance(value, dt.date):
            payload[key] = value.isoformat()
    return payload


def load_sample(path: Any) -> list[AwardFacts]:
    """Relit un échantillon gelé — l'analyse doit être rejouable sans réseau."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    restored: list[AwardFacts] = []
    for row in payload["award_lots"]:
        parsed = dict(row)
        for key in ("award_date", "publication_date", "contract_signature_date"):
            parsed[key] = dt.date.fromisoformat(parsed[key]) if parsed[key] else None
        restored.append(AwardFacts(**parsed))
    return restored
