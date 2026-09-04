"""Le modèle de compréhension — une couche DÉRIVÉE, à côté du fait brut.

    ContractAward  (fait canonique, jamais modifié)
            │
            ▼
    ContractUnderstanding  (ce qu'on en comprend, et pourquoi)

Chaque élément de compréhension est un `Claim` : une valeur, un niveau de
confiance, la règle qui l'a produite et les preuves qui la soutiennent. Le
modèle refuse une affirmation sûre sans preuve — la traçabilité n'est pas une
convention, c'est une contrainte structurelle.

Ce qui n'existe pas ici, délibérément : aucun besoin commercial, aucun score
d'opportunité, aucune échelle économique. Le premier relève du Need Graph ; la
seconde est indéfendable tant que le corpus mêle huit devises sans conversion
autorisée.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from signals.domain import EventRef, Evidence, Location, OrganizationRef, SourceSystem
from signals.domain.values import CanonicalModel, NonEmptyStr

Confidence = Literal["high", "medium", "low"]
"""Trois niveaux, lisibles par un utilisateur non technique.

- `high`   : un fait structuré et une confirmation indépendante concordent ;
- `medium` : un seul signal fiable, sans contradiction ;
- `low`    : signal faible, contradictoire, ou absent.

Aucun score numérique ne promeut un niveau. La règle qui a produit la valeur est
toujours nommée dans `Claim.rule`.
"""

OperationalCharacteristic = Literal[
    "several_lots",
    "framework_agreement",
    "consortium_award",
    "multiple_contractors",
    "long_duration",
    "defined_contract_period",
    "multi_country_parties",
]
"""Uniquement des caractéristiques **explicitement visibles** dans l'avis.

Pas de `high_staffing_need` ni de `likely_subcontracting` : ce sont des
inférences commerciales, elles appartiennent au Need Graph.
"""


ClaimKind = Literal["source_fact", "derived"]
"""Ce que l'affirmation prétend être.

`source_fact` : la source l'a publié, on le restitue.
`derived`     : nous l'avons conclu à partir d'autres éléments.

Les confondre reviendrait à présenter une conclusion comme une donnée
officielle — c'est précisément ce que Kivou doit rendre impossible.
"""


class Claim(CanonicalModel):
    """Une affirmation, avec sa nature, sa confiance, sa règle et ses preuves."""

    value: NonEmptyStr
    confidence: Confidence
    kind: ClaimKind = "derived"
    rule: NonEmptyStr | None = None
    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="after")
    def _une_affirmation_sure_se_prouve(self) -> Claim:
        if self.confidence in ("high", "medium") and not self.evidence:
            raise ValueError(
                f"affirmation « {self.value} » en confiance {self.confidence} sans preuve : "
                "une classification qu'on ne peut pas justifier ne peut pas être présentée "
                "comme sûre"
            )
        return self

    @property
    def is_material(self) -> bool:
        """Une affirmation matérielle est une affirmation qui prétend savoir."""
        return self.value != "unknown"


class ContractTiming(CanonicalModel):
    """Les faits temporels publiés, plus les délais qui s'en déduisent exactement.

    Aucune date n'est recalculée ni transposée : une date d'adjudication ne
    devient jamais une date de début. Un délai n'apparaît que si **les deux**
    dates existent, et il nomme celles dont il vient.
    """

    published_at: dt.date | dt.datetime | None = None
    award_date: dt.date | None = None
    contract_signature_date: dt.date | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None
    duration_value: int | None = None
    duration_unit: str | None = None

    days_between_award_and_start: int | None = None
    contract_span_days: int | None = None
    derived_from: tuple[str, ...] = ()


class ContractParties(CanonicalModel):
    """Les organisations publiées, chacune dans SON rôle.

    Deux ensembles, jamais fusionnés et jamais hiérarchisés : l'acheteur qui
    mène la procédure et le signataire du contrat ne sont pas le même fait. Une
    centrale d'achat peut conduire un marché sans le signer — c'est le cas réel
    observé sur `565986-2026` (CPO LT mène, l'hôpital signe).

    La position dans une liste n'est pas un rôle : il n'existe ici aucun
    « acheteur principal ».
    """

    procedure_buyers: tuple[OrganizationRef, ...] = ()
    contract_signatories: tuple[OrganizationRef, ...] = ()


class ContractGeography(CanonicalModel):
    """Le lieu tel que l'avis le publie — aucun géocodage, aucune déduction."""

    place_of_performance: Location | None = None
    buyer_country: str | None = None


class ContractUnderstanding(CanonicalModel):
    """Ce que l'avis permet de comprendre du contrat, et rien de plus."""

    award_ref: EventRef
    source_system: SourceSystem
    source_award_id: NonEmptyStr | None = None

    contract_type: Claim
    sector: Claim
    # WEDGE-HARDENING R1 §14 — le corps de métier. Facultatif parce que le champ
    # est né après les compréhensions déjà gelées ; le moteur le renseigne
    # toujours, et son absence se lit exactement comme `unknown_or_general`.
    trade_domain: Claim | None = None
    object_summary: Claim
    characteristics: tuple[Claim, ...] = ()
    # Résultats documentaires différés, traçables mais non matérialisés dans le
    # signal tant que la politique MVP garde l'auto-acceptation désactivée.
    document_requirements: tuple[Any, ...] = ()

    # Les faits critiques restitués depuis l'avis, chacun avec sa preuve : gagnant,
    # montant, CPV, acheteur, dates, lot. Ce ne sont pas des conclusions, mais ils
    # doivent pouvoir revenir à leur source aussi sûrement qu'elles.
    facts: dict[str, Claim] = Field(default_factory=dict)

    parties: ContractParties
    geography: ContractGeography
    timing: ContractTiming

    # Part des affirmations matérielles qui sont adossées à une preuve.
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    engine_version: NonEmptyStr

    def material_claims(self) -> dict[str, Claim]:
        """Toutes les affirmations qui prétendent savoir quelque chose, par nom.

        Faits restitués et conclusions confondus : l'exigence de traçabilité
        vaut pour les deux. Ce qui les distingue reste lisible dans `Claim.kind`.
        """
        named: dict[str, Claim] = {
            "contract_type": self.contract_type,
            "sector": self.sector,
            "object_summary": self.object_summary,
            **({"trade_domain": self.trade_domain} if self.trade_domain else {}),
            **self.facts,
        }
        for index, characteristic in enumerate(self.characteristics):
            named[f"characteristic_{index}"] = characteristic
        return {name: claim for name, claim in named.items() if claim.is_material}

    @staticmethod
    def coverage_of(claims: tuple[Claim, ...]) -> float:
        """couverture = affirmations matérielles prouvées / affirmations matérielles.

        Sans affirmation matérielle, la couverture vaut 1.0 : ne rien affirmer
        est un état parfaitement couvert, pas une lacune.
        """
        material = [claim for claim in claims if claim.is_material]
        if not material:
            return 1.0
        return sum(1 for claim in material if claim.evidence) / len(material)
