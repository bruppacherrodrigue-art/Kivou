"""La vue soumise au vérificateur (SPEC-009A §13–§16, §20).

Elle est construite depuis la vue aveugle gelée de SPEC-009 et ne contient
**que** ce que §14 autorise. Ce qui en est absent l'est délibérément :
`normalized_score`, `raw_points`, `ScoreBand`, `MatchDecision`, composants de
score, `rule_ids`, `mechanism_facts`, `pressure_facts`, gold, verdict attendu,
verdict d'un relecteur précédent. Le modèle doit juger la cohérence commerciale,
pas deviner ce que le moteur a conclu.

Chaque fait public affichable reçoit un identifiant stable : le vérificateur ne
peut citer que des faits de ce catalogue (§20). Il ne peut donc pas fabriquer un
montant, une date, une technologie, une localisation ou une obligation.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any

SUPPORTED_LANGUAGES = ("fr", "en")

#: Mots-outils très fréquents et peu ambigus. On ne cherche pas à identifier une
#: langue quelconque — seulement à savoir si la vue tient en français ou en
#: anglais (§16). Aucune règle par pays n'est créée.
_FRENCH_MARKERS = re.compile(
    r"\b(le|la|les|des|du|de|un|une|et|pour|dans|avec|sur|par|aux|est|sont|"
    r"travaux|marché|prestations|fourniture|entretien|réalisation|maintenance)\b",
    re.IGNORECASE,
)
_ENGLISH_MARKERS = re.compile(
    r"\b(the|of|and|for|with|to|in|on|is|are|services|works|supply|"
    r"maintenance|contract|framework|provision|delivery)\b",
    re.IGNORECASE,
)


#: Un seul mot-outil peut apparaître par accident dans une autre langue — « des »
#: existe en allemand, « in » en italien. En dessous de ce plancher, on ne tranche
#: pas : `None` signifie « indéterminé », pas « langue exotique ».
MIN_LANGUAGE_MARKERS = 3


def detect_language(text: str) -> str | None:
    """`fr`, `en`, ou `None` quand le texte ne relève clairement d'aucune des deux (§16).

    Volontairement grossier : la question n'est pas « quelle langue ? » mais
    « cette vue est-elle représentable en français ou en anglais ? ». Le plancher
    de marqueurs évite qu'un mot isolé fasse passer un texte allemand pour du
    français.
    """
    stripped = (text or "").strip()
    if len(stripped) < 12:
        return None
    french = len(_FRENCH_MARKERS.findall(stripped))
    english = len(_ENGLISH_MARKERS.findall(stripped))
    if max(french, english) < MIN_LANGUAGE_MARKERS:
        return None
    return "fr" if french >= english else "en"


@dataclasses.dataclass(frozen=True)
class Fact:
    """Un fait public affichable, identifié et rattaché à sa source."""

    fact_id: str
    statement: str
    evidence_reference: str

    def as_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class VerifierInput:
    """Tout ce que le vérificateur voit, et rien d'autre."""

    signal_candidate_id: str
    winner: dict[str, Any]
    award: dict[str, Any]
    derived_needs: tuple[dict[str, Any], ...]
    target_icp: dict[str, Any]
    limitations: dict[str, Any]
    fact_catalog: tuple[Fact, ...]
    language: str | None
    language_supported: bool

    @property
    def fact_ids(self) -> frozenset[str]:
        return frozenset(fact.fact_id for fact in self.fact_catalog)

    @property
    def structured_need_categories(self) -> frozenset[str]:
        """Les catégories que l'ICP déclare — l'autorité, face au texte libre (§15)."""
        icp = self.target_icp
        return frozenset(
            tuple(icp.get("primary_need_categories") or ())
            + tuple(icp.get("secondary_need_categories") or ())
        )

    @property
    def derived_need_categories(self) -> frozenset[str]:
        return frozenset(need["category"] for need in self.derived_needs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal_candidate_id": self.signal_candidate_id,
            "winner": self.winner,
            "award": self.award,
            "derived_needs": [dict(need) for need in self.derived_needs],
            "target_icp": self.target_icp,
            "limitations": self.limitations,
            "fact_catalog": [fact.as_dict() for fact in self.fact_catalog],
        }

    def snapshot_hash(self) -> str:
        """Empreinte stable de la vue — la base de la clé de cache (§11)."""
        payload = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _winner_names(blind: dict[str, Any]) -> list[str]:
    names = []
    for party in blind["winner"]["parties"]:
        for member in party["members"]:
            names.append(member["legal_name"])
    return names


def _evidence_index(blind: dict[str, Any]) -> dict[str, str]:
    """Chemin de preuve → référence lisible, pour rattacher chaque fait."""
    index: dict[str, str] = {}
    for evidence in blind.get("evidence_refs") or []:
        path = evidence.get("path")
        if not path:
            continue
        url = evidence.get("source_url") or evidence.get("source_notice_id") or ""
        index[path] = f"{evidence['source_system']}:{path} {url}".strip()
    return index


def _build_facts(blind: dict[str, Any]) -> tuple[Fact, ...]:
    """Le catalogue de faits publics, dans un ordre stable et déterministe."""
    contract = blind["contract"]
    understanding = blind["contract_understanding"]
    timing = understanding.get("timing") or {}
    evidence = _evidence_index(blind)
    fallback = blind.get("source_url") or blind["source"]

    def reference(*paths: str) -> str:
        for path in paths:
            if path in evidence:
                return evidence[path]
        return str(fallback)

    entries: list[tuple[str, str]] = []

    names = _winner_names(blind)
    if names:
        entries.append((f"Attributaire publié : {' ; '.join(names)}", reference()))
    countries = sorted(
        {
            member["country"]
            for party in blind["winner"]["parties"]
            for member in party["members"]
            if member.get("country")
        }
    )
    if countries:
        entries.append((f"Pays de l'attributaire : {', '.join(countries)}", reference()))

    if blind.get("publication_date"):
        entries.append(
            (f"Date de publication de l'avis : {blind['publication_date']}", reference())
        )
    for label, key in (
        ("Date d'attribution", "award_date"),
        ("Début d'exécution publié", "contract_start_date"),
        ("Fin d'exécution publiée", "contract_end_date"),
    ):
        if timing.get(key):
            entries.append((f"{label} : {timing[key]}", reference()))

    title = contract.get("title") or contract.get("contract_reference")
    if title:
        entries.append((f"Intitulé du marché : {title}", reference("procurement.title")))
    if understanding.get("object_summary"):
        entries.append(
            (
                f"Objet retenu : {understanding['object_summary']}",
                reference("procurement.description", "procurement.title"),
            )
        )
    if understanding.get("contract_type"):
        entries.append((f"Type de contrat : {understanding['contract_type']}", reference()))
    if understanding.get("sector"):
        entries.append((f"Secteur : {understanding['sector']}", reference()))
    if contract.get("cpv_main"):
        entries.append(
            (
                f"CPV principal : {contract['cpv_main']}",
                reference(
                    "procurement.cpvCode.code",
                    "cac:ProcurementProject/cbc:MainCommodityClassification",
                ),
            )
        )
    value = contract.get("value")
    if value:
        entries.append(
            (
                f"Montant publié : {value['amount']} {value['currency']}",
                reference("procurement.value", "cac:LegalMonetaryTotal"),
            )
        )
    else:
        entries.append(("Montant non publié par l'avis", str(fallback)))
    place = contract.get("place_of_performance") or {}
    if place.get("country"):
        entries.append(
            (
                "Lieu d'exécution publié : "
                + ", ".join(str(v) for v in (place.get("locality"), place.get("country")) if v),
                reference(),
            )
        )
    buyers = contract.get("buyers") or []
    if buyers:
        entries.append(
            (
                "Acheteur public : "
                + " ; ".join(f"{b['legal_name']} ({b.get('country') or '?'})" for b in buyers),
                reference(),
            )
        )

    return tuple(
        Fact(fact_id=f"F{index:02d}", statement=statement, evidence_reference=ref)
        for index, (statement, ref) in enumerate(entries, start=1)
    )


def _free_text(blind: dict[str, Any]) -> str:
    contract = blind["contract"]
    understanding = blind["contract_understanding"]
    parts = [
        contract.get("title") or "",
        contract.get("lot_title") or "",
        understanding.get("object_summary") or "",
        (contract.get("description") or "")[:600],
    ]
    return " ".join(part for part in parts if part)


def _structured_spine(blind: dict[str, Any]) -> bool:
    """Le squelette de faits neutres en langue suffit-il à juger ?

    Un CPV et un type de contrat sont lisibles quelle que soit la langue de
    l'avis. C'est ce qui permet de ne PAS écarter mécaniquement toute
    adjudication allemande ou italienne — §16 interdit les règles par pays.
    """
    contract = blind["contract"]
    understanding = blind["contract_understanding"]
    return bool(contract.get("cpv_main")) and bool(understanding.get("contract_type"))


def build_verifier_input(blind: dict[str, Any]) -> VerifierInput:
    """Compose la vue du vérificateur depuis une vue aveugle SPEC-009.

    Interprétation déclarée de §16 : la vue est *composée* en français ; le texte
    source y est cité tel quel comme donnée non fiable. Elle est donc jugée
    non représentable seulement quand le texte libre n'est ni français ni anglais
    **et** que le squelette structuré (CPV + type de contrat) ne porte rien.
    Écarter toute adjudication germanophone reviendrait à créer une règle par
    pays, ce que §16 interdit explicitement.
    """
    contract = blind["contract"]
    understanding = blind["contract_understanding"]
    timing = understanding.get("timing") or {}
    icp = blind["icp"]

    language = detect_language(_free_text(blind))
    language_supported = language in SUPPORTED_LANGUAGES or _structured_spine(blind)

    winner = {
        "parties": [
            {
                "name": party["name"],
                "is_group": party["is_group"],
                "members": [
                    {
                        "legal_name": member["legal_name"],
                        "country": member["country"],
                        "location": member.get("address"),
                    }
                    for member in party["members"]
                ],
            }
            for party in blind["winner"]["parties"]
        ]
    }

    award = {
        "source": blind["source"],
        "publication_date": blind.get("publication_date"),
        "award_date": timing.get("award_date"),
        "contract_start_date": timing.get("contract_start_date"),
        "contract_end_date": timing.get("contract_end_date"),
        "title": contract.get("title") or contract.get("contract_reference"),
        "factual_summary": understanding.get("object_summary"),
        "contract_type": understanding.get("contract_type"),
        "sector": understanding.get("sector"),
        "cpv_main": contract.get("cpv_main"),
        "amount": (contract.get("value") or {}).get("amount"),
        "currency": (contract.get("value") or {}).get("currency"),
        "place_of_performance": contract.get("place_of_performance"),
        "detected_language": language,
    }

    derived_needs = tuple(
        {
            "category": need["category"],
            "statement": need["statement"],
            "reasoning": need["reasoning"],
            "timing": need["timing"],
            "externalisability": need["externalisability"],
            "confidence": need["confidence"],
        }
        for need in blind["derived_needs"]
    )

    target_icp = {
        "name": icp["name"],
        "primary_need_categories": list(icp["primary_need_categories"]),
        "secondary_need_categories": list(icp["secondary_need_categories"]),
        "included_contract_types": list(icp["included_contract_types"]),
        "excluded_contract_types": list(icp["excluded_contract_types"]),
        "included_sectors": list(icp.get("included_sectors") or ()),
        "excluded_sectors": list(icp.get("excluded_sectors") or ()),
        "geography_basis": icp["geography_basis"],
        "geography_policy": icp["geography_policy"],
        "territories": icp["territories"],
        "value_thresholds": icp["value_thresholds"],
        "maximum_signal_age_days": icp["maximum_signal_age_days"],
        "preferred_timings": list(icp["preferred_timings"]),
        "offer_summary_clarification_only": icp["offer_summary"],
    }

    limitations = {
        "source_mode": blind["source_mode"],
        "document_mode_disclosure": blind["disclosure"],
        "missing_facts": [
            label
            for label, present in (
                ("amount", bool(contract.get("value"))),
                ("place_of_performance", bool(contract.get("place_of_performance"))),
                ("contract_start_date", bool(timing.get("contract_start_date"))),
                ("contract_end_date", bool(timing.get("contract_end_date"))),
                ("award_date", bool(timing.get("award_date"))),
            )
            if not present
        ],
    }

    return VerifierInput(
        signal_candidate_id=blind["signal_id"],
        winner=winner,
        award=award,
        derived_needs=derived_needs,
        target_icp=target_icp,
        limitations=limitations,
        fact_catalog=_build_facts(blind),
        language=language,
        language_supported=language_supported,
    )
