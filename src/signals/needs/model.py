"""Le modèle Need Graph — des hypothèses commerciales, jamais des certitudes.

    ContractAward (fait)
        → ContractUnderstanding (compréhension, SPEC-005)
            → NeedGraphResult (inférence commerciale, SPEC-007)

La séparation FAIT ≠ INFÉRENCE ≠ ACHAT CERTAIN est portée par le type :

- la confiance `high` n'existe pas — en mode `metadata_fallback`, aucune
  inférence fondée sur CPV, titre, montant, dates ou caractéristiques visibles
  ne peut prétendre à la certitude ;
- un besoin sans règle nommée, sans preuve ou sans mode de production ne se
  construit pas ;
- le vocabulaire de certitude (« will buy », « va recruter », « besoin
  confirmé ») est refusé à la validation — pas par un filtre aval, par le
  modèle lui-même ;
- au plus TROIS besoins par contrat, tous `medium`, tous de catégorie
  distincte. `needs = ()` est un résultat parfaitement valide : ne rien
  affirmer vaut mieux qu'un faux signal.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import model_validator

from signals.domain import EventRef, Evidence
from signals.domain.values import CanonicalModel, NonEmptyStr

ENGINE_VERSION = "need-graph-v0.2"

MAX_NEEDS = 3
"""En mode metadata_fallback : 0 à 3 besoins, jamais une liste exhaustive.
Le futur mode documentaire pourra monter à 5 — pas dans cette SPEC."""

NeedCategory = Literal[
    "workforce_capacity",
    "equipment_or_rental",
    "materials_or_components",
    "logistics_and_transport",
    "specialist_subcontracting",
    "safety_and_ppe",
    "waste_and_environment",
]
"""Taxonomie V0 — sept familles, chacune vendable par un fournisseur B2B réel.

Issue de l'étude de corpus Contract-100 (§9) : les familles invisibles dans le
modèle canonique (cybersécurité, formation, implémentation) ou adjacentes au
deliverable (logiciel pour un contrat IT, maintenance du livrable) sont
volontairement absentes — les inférer depuis des métadonnées fabriquerait de
faux signaux.
"""

NeedTiming = Literal["immediate", "near_term", "medium_term", "recurring", "unknown"]
"""`unknown` est toujours correct quand les faits manquent. Une date d'award
n'est jamais une date de début : sans date de début publiée, le seul timing
déductible est `recurring` (service récurrent à durée publiée)."""

Externalisability = Literal["likely_internal", "mixed", "external_plausible", "unknown"]
"""Jamais `certainly_external` ni `will_outsource` : Kivou ne sait pas si le
gagnant recrutera, réaffectera, louera ou sous-traitera."""

SourceMode = Literal["metadata_fallback", "document_supported"]
"""`document_supported` est réservé : SPEC-006 a désactivé l'auto-acceptation
documentaire (`AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False`). Tant qu'aucun
moteur documentaire éligible n'existe, tout besoin est produit — et étiqueté —
`metadata_fallback`."""

NeedConfidence = Literal["medium", "low"]
"""`high` n'existe pas dans le type : c'est la politique §7, rendue
inviolable. `medium` exige au moins deux faits indépendants cohérents ;
`low` reste dans les diagnostics et n'atteint jamais la sortie principale."""


_CERTAINTY_WORDING = re.compile(
    r"will\s+(?:definitely|buy|hire|purchase|need)|must\s+(?:buy|purchase)"
    r"|confirmed\s+(?:purchase|demand)|certain\s+(?:demand|opportunity)"
    r"|va\s+(?:acheter|recruter|embaucher)|besoin\s+confirm[eé]|achat\s+certain"
    r"|demande\s+certaine",
    re.IGNORECASE,
)

_HYPOTHETICAL_MARKERS = re.compile(
    r"\bmay\b|\bcould\b|\bmight\b|plausible|likely\s+operational"
    r"|pourrait|pourraient|susceptible|hypoth[eé]s|envisageable",
    re.IGNORECASE,
)


class SuppressedCandidate(CanonicalModel):
    """Un candidat écarté — visible en diagnostic, jamais présenté comme besoin."""

    category: NeedCategory
    rule_id: NonEmptyStr
    reason: NonEmptyStr


class ResourceNeed(CanonicalModel):
    """Une hypothèse commerciale : plausible, limitée, explicable — pas un fait.

    La preuve (`evidence_refs`) démontre les FAITS D'ENTRÉE du contrat, jamais
    que le besoin futur aura lieu : c'est `reasoning` qui porte le passage du
    fait à l'hypothèse, et il doit rester explicitement hypothétique.
    """

    category: NeedCategory
    # WEDGE-HARDENING R1 §19 — DE QUOI ce besoin parle. Une hypothèse qui ne
    # nomme pas son sujet ne peut pas être contredite par lui : c'est ainsi
    # qu'un besoin d'engins de terrassement s'est retrouvé sur un lot de portes
    # intérieures en métal sans que rien ne sonne. Facultatif parce qu'un avis
    # peut ne publier aucun objet exploitable — et alors le besoin le dit.
    subject: NonEmptyStr | None = None
    statement: NonEmptyStr
    reasoning: NonEmptyStr
    timing: NeedTiming
    externalisability: Externalisability
    confidence: NeedConfidence
    evidence_refs: tuple[Evidence, ...]
    supporting_facts: tuple[NonEmptyStr, ...]
    # SPEC-007R1 §8 — les deux rôles, nommés séparément. Compter des faits ne
    # suffisait pas : « type construction » et « CPV 45 » en faisaient deux tout
    # en disant la même chose.
    mechanism_facts: tuple[NonEmptyStr, ...] = ()
    pressure_facts: tuple[NonEmptyStr, ...] = ()
    rule_ids: tuple[NonEmptyStr, ...]
    source_mode: SourceMode
    engine_version: NonEmptyStr

    @model_validator(mode="after")
    def _une_hypothese_se_justifie(self) -> ResourceNeed:
        if not self.rule_ids:
            raise ValueError("un besoin sans règle nommée n'est pas explicable")
        if not self.evidence_refs:
            raise ValueError("un besoin sans preuve des faits d'entrée n'est pas vérifiable")
        if self.confidence == "medium" and not (self.mechanism_facts and self.pressure_facts):
            raise ValueError(
                "confiance medium sans mécanisme ET pression : deux faits du même "
                "rôle ne suffisent jamais (SPEC-007R1 §8)"
            )
        for text in (self.statement, self.reasoning):
            if _CERTAINTY_WORDING.search(text):
                raise ValueError(
                    f"vocabulaire de certitude refusé : {text[:60]!r} — le Need Graph "
                    "ne connaît ni achat certain ni recrutement confirmé"
                )
        if not _HYPOTHETICAL_MARKERS.search(self.reasoning):
            raise ValueError(
                "le raisonnement doit rester explicitement hypothétique "
                "(« may », « pourrait », « plausible »…)"
            )
        return self


class NeedGraphResult(CanonicalModel):
    """Le verdict du Need Graph pour un contrat — bornes comprises."""

    award_ref: EventRef
    source_mode: SourceMode
    needs: tuple[ResourceNeed, ...] = ()
    suppressed_candidates: tuple[SuppressedCandidate, ...] = ()
    warnings: tuple[NonEmptyStr, ...] = ()
    engine_version: NonEmptyStr

    @model_validator(mode="after")
    def _une_sortie_bornee_et_sure(self) -> NeedGraphResult:
        if len(self.needs) > MAX_NEEDS:
            raise ValueError(
                f"{len(self.needs)} besoins : le Need Graph n'en présente jamais "
                f"plus de {MAX_NEEDS} — il ne produit pas de liste exhaustive"
            )
        if any(need.confidence != "medium" for need in self.needs):
            raise ValueError(
                "seuls les besoins medium atteignent la sortie principale ; "
                "les low restent dans les diagnostics"
            )
        categories = [need.category for need in self.needs]
        if len(categories) != len(set(categories)):
            raise ValueError(
                "deux besoins de même catégorie canonique doivent être fusionnés, "
                "pas présentés deux fois"
            )
        return self
