"""L'exigence d'exécution — ce que le titulaire doit faire, d'après le document.

La frontière tenue ici est celle qui sépare SPEC-006 de SPEC-007 :

    « Le titulaire doit mettre à disposition au minimum 4 techniciens. »
        → exigence documentée              ← SPEC-006 s'arrête ici

    « Le titulaire devra probablement recruter. »
        → besoin commercial plausible      ← SPEC-007, plus tard

Une exigence sans extrait source n'existe pas : c'est la règle qui empêche un
modèle de langue de transformer une phrase plausible en obligation contractuelle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from signals.domain import Evidence
from signals.domain.values import CanonicalModel, NonEmptyStr

RequirementType = Literal[
    "deliverable",
    "quantity_volume",
    "staffing_constraint",
    "site_location",
    "schedule_deadline",
    "service_level",
    "operating_hours",
    "technology",
    "certification",
    "security_constraint",
    "environmental_constraint",
    "maintenance_obligation",
    "training_obligation",
    "documentation_obligation",
    "subcontracting_rule",
    "technical_characteristic",
    "payment_terms",
    "warranty_liability",
    "other",
]

"""`technical_characteristic` couvre les caractéristiques imposées à la chose
livrée — dimensions, matériau, tension, norme de fabrication. Le type est né de
la revue du corpus : sur le dossier portugais (un camion), la majorité des
obligations décrivent le produit et non une prestation, et les ranger en
« other » revenait à jeter l'essentiel du cahier des charges.
"""

Modality = Literal["mandatory", "prohibited", "optional", "informational"]
"""Ce que le document fait de l'énoncé.

`informational` couvre l'historique et le contexte — « le précédent contrat
exigeait une astreinte 24/7 » décrit le passé, pas une obligation actuelle. Ces
énoncés ne deviennent jamais des exigences.
"""

Confidence = Literal["high", "medium", "low"]
"""`high` exige les trois : obligation explicite, extrait exact, localisation stable."""

ExtractionMethod = Literal["deterministic", "model"]


class RequirementQuantity(CanonicalModel):
    """Une quantité, telle qu'écrite ET normalisée quand c'est sûr."""

    raw: NonEmptyStr
    value: float | None = None
    unit: NonEmptyStr | None = None


class ExecutionRequirement(CanonicalModel):
    """Une obligation, une interdiction ou une option documentée, avec sa preuve."""

    requirement_type: RequirementType
    modality: Modality
    # Énoncé structuré : il peut être normalisé. L'extrait, lui, ne l'est jamais.
    statement: NonEmptyStr
    quantity: RequirementQuantity | None = None
    confidence: Confidence
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    extraction_method: ExtractionMethod
    engine_version: NonEmptyStr

    @model_validator(mode="after")
    def _preuve_documentaire_obligatoire(self) -> ExecutionRequirement:
        for evidence in self.evidence:
            if evidence.source_kind != "tender_document":
                raise ValueError(
                    "une exigence d'exécution se prouve par un document de marché, "
                    f"pas par « {evidence.source_kind} »"
                )
            if not evidence.excerpt:
                raise ValueError(
                    "preuve sans extrait : sans passage source, l'exigence n'existe pas"
                )
        if self.modality == "informational":
            raise ValueError("un énoncé informatif (historique, contexte) n'est pas une exigence")
        return self

    @property
    def is_obligation(self) -> bool:
        return self.modality == "mandatory"
