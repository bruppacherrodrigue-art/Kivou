"""Rapprocher un avis BOAMP et un contrat DECP — ou reconnaître qu'on ne peut pas.

Les deux sources françaises décrivent le même marché sans partager d'identifiant.
La tentation est de les joindre sur ce qu'elles ont en commun : le SIRET de
l'acheteur et celui du titulaire. Les données interdisent ce raccourci.

    Mesuré sur la Ville de Nice et ses titulaires
    ─────────────────────────────────────────────
    Le couple (acheteur, titulaire) seul rapproche des marchés distants de
    **cinq ans** : un contrat de voirie de décembre 2023 et une installation de
    réseaux d'arrosage de juin 2020 partagent exactement le même couple.

Un couple de parties n'identifie donc pas un contrat — il identifie une
relation commerciale. C'est la date qui tranche : quand la notification DECP
tombe le jour de la conclusion publiée par BOAMP, il s'agit du même acte.

    strong       parties identiques + date compatible + AU MOINS UN corroborant
                 indépendant du contrat (CPV, montant, ou référence exacte)
    probable     parties identiques + la date OU un corroborant, pas les deux
    unresolved   tout le reste — y compris le couple de parties seul

Le corroborant est l'exigence ajoutée par le closeout R2. Parties et date
suffisaient tant qu'on supposait qu'un fournisseur ne gagne qu'un marché par
jour chez le même acheteur — ce que les données démentent. Le jeu de test
contient le contre-exemple réel : `202524V1642-01` et `-02`, deux lots du même
accord-cadre notifiés le 2025-05-21 à la même entreprise par le même acheteur.

    Ambiguïté
    ─────────
    Quand plusieurs candidats satisfont également les critères forts, aucun
    n'est retenu : tous sont conservés, tous sont déclassés en `probable`, et
    `unique_strong` rend `None`. Choisir « le premier » ferait porter à un
    contrat les faits d'un autre, ce qui est exactement le genre d'erreur
    qu'aucune preuve ne rattrape ensuite.

Un `probable` ne fusionne rien silencieusement (§23) : il est rendu comme
candidat, et c'est l'appelant qui décide.

La ressemblance de raison sociale n'entre nulle part. Elle n'est ni
déterministe ni vérifiable, et deux établissements d'un même groupe portent
souvent le même nom.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from signals.connectors.decp import buyer_siret, winner_sirets
from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent

FRANCE_LINK_POLICY_VERSION = "france-link-v0.3"

MatchStrength = Literal["strong", "probable", "unresolved"]

#: Les seuls corroborants acceptés — tous déterministes, tous propres au
#: CONTRAT et non à la relation entre les parties.
INDEPENDENT_CORROBORATORS: frozenset[str] = frozenset({"cpv", "amount", "contract_reference"})

NOTIFICATION_TOLERANCE_DAYS = 7
"""Écart admis entre la conclusion BOAMP (BT-145) et la notification DECP.

Les deux actes sont proches mais pas simultanés : la notification suit la
signature de quelques jours ouvrés. Au-delà d'une semaine, rien ne garantit
qu'il s'agit du même contrat plutôt que du suivant.
"""

#: §24 — quelle source fait foi, champ par champ, et pourquoi. La justification
#: n'est pas décorative : elle est le seul garde-fou contre une préférence
#: choisie par commodité d'implémentation.
FIELD_PRIORITY: dict[str, dict[str, str]] = {
    "winner_siret": {
        "preferred": "decp",
        "fallback": "boamp",
        "conflict_policy": "diagnostic",
        "reason": (
            "DECP identifie le titulaire sur 100 % de ses lignes ; BOAMP n'en "
            "publie un que sur 38,3 % de ses award-lots eForms"
        ),
    },
    "winner_legal_name": {
        "preferred": "boamp",
        "fallback": "decp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": (
            "le schéma DECP 2022 ne comporte AUCUN champ de raison sociale : "
            "BOAMP est la seule source du nom d'entreprise"
        ),
    },
    "buyer_siret": {
        "preferred": "decp",
        "fallback": "boamp",
        "conflict_policy": "diagnostic",
        "reason": "BOAMP ne porte un SIRET acheteur que dans 53,8 % des award-lots mesurés",
    },
    "publication_date": {
        "preferred": "boamp",
        "fallback": "decp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": (
            "`datePublicationDonnees` date la mise en ligne de la donnée ouverte, "
            "des mois après la parution de l'avis"
        ),
    },
    "award_date": {
        "preferred": "boamp",
        "fallback": "boamp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": "DECP n'expose aucune date de décision d'attribution (§20)",
    },
    "contract_signature_date": {
        "preferred": "boamp",
        "fallback": "boamp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": (
            "BT-145 est explicitement une conclusion de contrat ; le schéma DECP "
            "2022 n'en publie aucune, donc aucun conflit n'est possible"
        ),
    },
    "contract_notification_date": {
        "preferred": "decp",
        "fallback": "decp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": (
            "R1 §2 — DECP est la seule des deux sources à publier la notification ; "
            "BOAMP n'expose pas cet acte"
        ),
    },
    "amount": {
        "preferred": "boamp",
        "fallback": "decp",
        "conflict_policy": "diagnostic",
        "reason": (
            "BOAMP publie la valeur de l'offre retenue ; le schéma DECP 2022 dit "
            "« montant HT forfaitaire ou estimé maximum » — deux grandeurs "
            "différentes, jamais arbitrées"
        ),
    },
    "cpv": {
        "preferred": "boamp",
        "fallback": "decp",
        "conflict_policy": "diagnostic",
        "reason": "les deux sources classent le même marché différemment ; l'écart est un fait",
    },
    "place_of_performance": {
        "preferred": "decp",
        "fallback": "boamp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": (
            "DECP donne un code de lieu typé (postal, département) ; BOAMP "
            "s'arrête souvent au NUTS de la procédure"
        ),
    },
    "duration_months": {
        "preferred": "decp",
        "fallback": "boamp",
        "conflict_policy": "prefer_without_diagnostic",
        "reason": "`dureeMois` est publié par DECP et absent des avis eForms du BOAMP",
    },
}


@dataclasses.dataclass(frozen=True)
class LinkCandidate:
    """Un rapprochement possible, avec ce sur quoi il repose et ce qui manque."""

    decp_id: str
    strength: MatchStrength
    matched_on: tuple[str, ...]
    diverged_on: tuple[str, ...]
    #: Vrai quand ce candidat a été déclassé parce qu'un autre le valait autant.
    ambiguous: bool = False
    policy_version: str = FRANCE_LINK_POLICY_VERSION


@dataclasses.dataclass(frozen=True)
class FieldConflict:
    """Deux sources, deux valeurs, aucune arbitrée (§25)."""

    field: str
    boamp_value: str | None
    decp_value: str | None
    note: str


@dataclasses.dataclass(frozen=True)
class MergedFrenchAward:
    """Le contrat canonique, enrichi de ce que DECP ajoute — sans rien écraser."""

    award: ContractAward
    decp_id: str
    winner_siret: str | None
    buyer_siret: str | None
    contract_notification_date: dt.date | None
    duration_months: int | None
    conflicts: tuple[FieldConflict, ...]
    provenance: dict[str, str]
    policy_version: str = FRANCE_LINK_POLICY_VERSION


def _award_winner_sirets(award: ContractAward) -> set[str]:
    return {
        identifier.value
        for party in award.awardee_parties
        for member in party.members
        for identifier in member.organization.identifiers
        if identifier.scheme == "SIRET"
    }


def _event_buyer_sirets(event: PublicEvent) -> set[str]:
    return {
        identifier.value
        for organization in event.procedure_buyers
        for identifier in organization.identifiers
        if identifier.scheme == "SIRET"
    }


def _decp_date(record: dict) -> dt.date | None:
    raw = record.get("datenotification")
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _decp_cpv(record: dict) -> str | None:
    raw = record.get("codecpv")
    if not raw:
        return None
    root = str(raw).partition("-")[0]
    return root if root.isdigit() and len(root) == 8 else None


def _decp_references(record: dict) -> set[str]:
    """Les identifiants de contrat que DECP publie, remplissage `CDL` exclu."""
    from signals.connectors.decp.parser import FILLER_VALUES

    found = set()
    for key in ("id", "idaccordcadre"):
        value = record.get(key)
        text = str(value).strip() if value is not None else ""
        if text and text not in FILLER_VALUES:
            found.add(text)
    return found


def _decp_amount(record: dict) -> str | None:
    raw = record.get("montant")
    return None if raw is None else str(raw)


def resolve_candidates(
    award: ContractAward,
    event: PublicEvent,
    decp_records: Iterable[dict],
    *,
    tolerance_days: int = NOTIFICATION_TOLERANCE_DAYS,
) -> tuple[LinkCandidate, ...]:
    """Les rapprochements possibles d'un award-lot BOAMP, classés par force.

    L'ordre de sortie est déterministe : force décroissante puis identifiant
    DECP. Deux exécutions rendent la même liste, ce que le futur polling exige.
    """
    buyers = _event_buyer_sirets(event)
    winners = _award_winner_sirets(award)
    candidates: list[LinkCandidate] = []

    for record in decp_records:
        decp_id = str(record.get("id") or "")
        if not decp_id:
            continue
        matched: list[str] = []
        diverged: list[str] = []

        if buyers and buyer_siret(record) in buyers:
            matched.append("buyer_siret")
        elif buyers:
            diverged.append("buyer_siret")

        if winners and set(winner_sirets(record)) & winners:
            matched.append("winner_siret")
        elif winners:
            diverged.append("winner_siret")

        notified = _decp_date(record)
        signed = award.contract_signature_date
        if notified and signed:
            if abs((notified - signed).days) <= tolerance_days:
                matched.append("notification_date")
            else:
                diverged.append("notification_date")

        award_cpv = award.cpv_main.code if award.cpv_main else None
        decp_cpv = _decp_cpv(record)
        if award_cpv and decp_cpv:
            (matched if award_cpv == decp_cpv else diverged).append("cpv")

        award_amount = str(award.value.amount) if award.value else None
        decp_amount = _decp_amount(record)
        if award_amount and decp_amount:
            same = float(award_amount) == float(decp_amount)
            (matched if same else diverged).append("amount")

        # Une référence de marché ne corrobore que lorsqu'elle CONCORDE. Deux
        # registres formatent le même numéro différemment ; une inégalité ne
        # démontre donc rien, et la compter comme divergence serait du bruit.
        if award.contract_reference and award.contract_reference in _decp_references(record):
            matched.append("contract_reference")

        parties_agree = {"buyer_siret", "winner_siret"} <= set(matched)
        corroborated = bool(INDEPENDENT_CORROBORATORS & set(matched))
        dated = "notification_date" in matched
        if parties_agree and dated and corroborated:
            strength: MatchStrength = "strong"
        elif parties_agree and (dated or corroborated):
            strength = "probable"
        else:
            strength = "unresolved"

        candidates.append(
            LinkCandidate(
                decp_id=decp_id,
                strength=strength,
                matched_on=tuple(matched),
                diverged_on=tuple(diverged),
            )
        )

    order = {"strong": 0, "probable": 1, "unresolved": 2}
    guarded = _apply_ambiguity_guard(candidates)
    return tuple(sorted(guarded, key=lambda c: (order[c.strength], c.decp_id)))


def _corroboration_rank(candidate: LinkCandidate) -> tuple[int, int]:
    """De quoi comparer deux candidats forts, sans jamais « choisir le meilleur ».

    Une référence de marché exacte l'emporte sur n'importe quel nombre
    d'accords de CPV ou de montant : c'est le seul corroborant qui identifie le
    **contrat** plutôt que ses caractéristiques. À défaut, le nombre de
    corroborants départage.

    Ce rang ne sert qu'à répondre à une question binaire — un candidat
    domine-t-il STRICTEMENT tous les autres ? — et jamais à classer un
    palmarès.
    """
    matched = set(candidate.matched_on)
    return (
        1 if "contract_reference" in matched else 0,
        len(INDEPENDENT_CORROBORATORS & matched),
    )


def _apply_ambiguity_guard(
    candidates: list[LinkCandidate],
) -> list[LinkCandidate]:
    """Aucun contrat ne se fusionne quand deux candidats le valent autant.

    Deux situations réelles, très différentes, se présentent dès qu'un couple
    (acheteur, titulaire) rend plusieurs enregistrements :

    * **Doublon de publication.** DECP publie parfois le même contrat sous deux
      identifiants — mesuré sur `26-011` et `20262601101`, mêmes parties, même
      date, même montant, même objet. L'un porte la référence exacte du marché,
      l'autre non : ils ne sont pas également corroborés, et le premier
      l'emporte de façon déterministe.
    * **Contrats réellement distincts.** Deux lots notifiés le même jour au même
      titulaire, sous le même CPV — 61 groupes de ce type sur 600 contrats lus.
      Là, rien ne départage, et rien ne doit être fusionné.

    Le départage n'a donc lieu que sur une domination **stricte**. En cas
    d'égalité, tous les candidats sont conservés et tous sont déclassés : les
    perdre effacerait la preuve qu'un doute existait.
    """
    strong = [candidate for candidate in candidates if candidate.strength == "strong"]
    if len(strong) < 2:
        return candidates

    ranks = {candidate.decp_id: _corroboration_rank(candidate) for candidate in strong}
    best = max(ranks.values())
    leaders = [decp_id for decp_id, rank in ranks.items() if rank == best]

    if len(leaders) == 1:
        # Un candidat domine strictement : les autres sont dominés, pas ambigus.
        dominated = {candidate.decp_id for candidate in strong} - set(leaders)
        return [
            dataclasses.replace(candidate, strength="probable")
            if candidate.decp_id in dominated
            else candidate
            for candidate in candidates
        ]

    tied = set(leaders) | {candidate.decp_id for candidate in strong}
    return [
        dataclasses.replace(candidate, strength="probable", ambiguous=True)
        if candidate.decp_id in tied
        else candidate
        for candidate in candidates
    ]


def unique_strong(candidates: Sequence[LinkCandidate]) -> LinkCandidate | None:
    """L'unique candidat fort, ou `None` — jamais « le premier de la liste ».

    C'est la seule porte vers une fusion de faits. Un appelant qui prendrait
    `candidates[0]` sans passer par ici pourrait fusionner un candidat déclassé.
    """
    strong = [candidate for candidate in candidates if candidate.strength == "strong"]
    return strong[0] if len(strong) == 1 else None


def merge_award(award: ContractAward, decp_record: dict) -> MergedFrenchAward:
    """Enrichit un award-lot BOAMP de ce que DECP apporte, sans écraser quoi que ce soit.

    Le contrat canonique ressort **inchangé** : la fusion ajoute des faits à
    côté et signale les divergences. C'est la seule forme de fusion compatible
    avec §25 — une valeur remplacée est une preuve perdue.
    """
    conflicts: list[FieldConflict] = []

    award_amount = str(award.value.amount) if award.value else None
    decp_amount = _decp_amount(decp_record)
    if award_amount and decp_amount and float(award_amount) != float(decp_amount):
        conflicts.append(
            FieldConflict(
                field="amount",
                boamp_value=award_amount,
                decp_value=decp_amount,
                note=(
                    "BOAMP publie la valeur de l'offre retenue ; DECP publie un "
                    "montant HT forfaitaire ou estimé maximum "
                    f"({decp_record.get('nature') or 'nature non publiée'})"
                ),
            )
        )

    award_cpv = award.cpv_main.code if award.cpv_main else None
    decp_cpv = _decp_cpv(decp_record)
    if award_cpv and decp_cpv and award_cpv != decp_cpv:
        conflicts.append(
            FieldConflict(
                field="cpv",
                boamp_value=award_cpv,
                decp_value=decp_cpv,
                note="les deux sources classent le même marché sous des CPV différents",
            )
        )

    signed = award.contract_signature_date
    notified = _decp_date(decp_record)
    if signed and notified and signed != notified:
        conflicts.append(
            FieldConflict(
                field="contract_signature_date",
                boamp_value=signed.isoformat(),
                decp_value=notified.isoformat(),
                note="conclusion BT-145 contre notification DECP — deux actes voisins, distincts",
            )
        )

    duration: Any = decp_record.get("dureemois")
    return MergedFrenchAward(
        award=award,
        decp_id=str(decp_record.get("id") or ""),
        winner_siret=next(iter(winner_sirets(decp_record)), None),
        buyer_siret=buyer_siret(decp_record),
        contract_notification_date=notified,
        duration_months=int(duration) if isinstance(duration, int | float) else None,
        conflicts=tuple(conflicts),
        provenance={
            "boamp": award.event_ref.source_notice_id,
            "decp": str(decp_record.get("id") or ""),
        },
    )
