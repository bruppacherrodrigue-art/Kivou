"""SPEC-007 §5 — le modèle Need Graph : des hypothèses, jamais des certitudes.

    ContractUnderstanding (fait d'entrée)
            ↓
    NeedGraphEngine
            ↓
    NeedGraphResult ── ResourceNeed[]

La séparation FAIT ≠ INFÉRENCE ≠ ACHAT CERTAIN est structurelle : le modèle
refuse un besoin sans règle, sans preuve, sans mode de production, et refuse
tout vocabulaire de certitude (« will buy », « va recruter »). En mode
metadata_fallback, la confiance maximale est `medium` — `high` n'existe pas
dans le type.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.domain import EventRef, Evidence
from signals.needs import (
    ENGINE_VERSION,
    NeedGraphResult,
    ResourceNeed,
    SuppressedCandidate,
)

EVIDENCE = Evidence(
    source_system="ted",
    source_kind="publication_field",
    source_notice_id="565997-2026",
    path="BT-27",
    excerpt="Valeur estimée : 4 500 000 EUR",
)

REF = EventRef(source_system="ted", source_notice_id="565997-2026")


def _need(**overrides) -> ResourceNeed:
    data = {
        "category": "equipment_or_rental",
        "statement": "Une capacité temporaire de matériel de chantier pourrait être commercialement pertinente.",
        "reasoning": (
            "Le contrat est un marché de travaux de grande ampleur : une pression "
            "opérationnelle sur le matériel est plausible pendant l'exécution."
        ),
        "timing": "unknown",
        "externalisability": "mixed",
        "confidence": "medium",
        "evidence_refs": (EVIDENCE,),
        "supporting_facts": ("cpv", "amount"),
        "mechanism_facts": ("construction_machinery",),
        "pressure_facts": ("large_scale",),
        "rule_ids": ("construction-large-equipment-v1",),
        "source_mode": "metadata_fallback",
        "engine_version": ENGINE_VERSION,
    }
    data.update(overrides)
    return ResourceNeed(**data)


class TestResourceNeedInvariants:
    def test_a_valid_hypothesis_is_accepted(self) -> None:
        need = _need()
        assert need.category == "equipment_or_rental"
        assert need.source_mode == "metadata_fallback"

    def test_high_confidence_does_not_exist_in_the_type(self) -> None:
        with pytest.raises(ValidationError):
            _need(confidence="high")

    def test_a_need_without_any_rule_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _need(rule_ids=())

    def test_a_need_without_evidence_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _need(evidence_refs=())

    def test_medium_confidence_requires_a_mechanism_and_a_pressure(self) -> None:
        """SPEC-007R1 §8 — deux faits du même rôle ne suffisent jamais."""
        with pytest.raises(ValidationError):
            _need(pressure_facts=())
        with pytest.raises(ValidationError):
            _need(mechanism_facts=())

    def test_low_confidence_may_rest_on_a_mechanism_alone(self) -> None:
        need = _need(confidence="low", pressure_facts=())
        assert need.confidence == "low"

    @pytest.mark.parametrize(
        "forbidden",
        [
            "Le gagnant va recruter 30 agents de sécurité.",
            "The winner will buy new equipment.",
            "Confirmed purchase of materials expected.",
            "Besoin confirmé de personnel supplémentaire.",
            "The winner must buy trucks.",
            "Achat certain de fournitures.",
            "will definitely need cranes",
            "certain demand for steel",
        ],
    )
    def test_certainty_wording_is_structurally_refused(self, forbidden: str) -> None:
        with pytest.raises(ValidationError):
            _need(statement=forbidden)
        with pytest.raises(ValidationError):
            _need(reasoning=forbidden)

    def test_the_reasoning_must_stay_explicitly_hypothetical(self) -> None:
        with pytest.raises(ValidationError):
            _need(reasoning="Le contrat exige du matériel supplémentaire dès demain.")


class TestNeedGraphResult:
    def test_an_empty_result_is_a_valid_result(self) -> None:
        result = NeedGraphResult(
            award_ref=REF,
            source_mode="metadata_fallback",
            needs=(),
            suppressed_candidates=(),
            warnings=(),
            engine_version=ENGINE_VERSION,
        )
        assert result.needs == ()

    def test_more_than_three_needs_are_refused(self) -> None:
        needs = tuple(
            _need(category=c)
            for c in (
                "equipment_or_rental",
                "materials_or_components",
                "workforce_capacity",
                "safety_and_ppe",
            )
        )
        with pytest.raises(ValidationError):
            NeedGraphResult(
                award_ref=REF,
                source_mode="metadata_fallback",
                needs=needs,
                suppressed_candidates=(),
                warnings=(),
                engine_version=ENGINE_VERSION,
            )

    def test_low_confidence_needs_never_reach_the_main_output(self) -> None:
        low = _need(confidence="low", pressure_facts=())
        with pytest.raises(ValidationError):
            NeedGraphResult(
                award_ref=REF,
                source_mode="metadata_fallback",
                needs=(low,),
                suppressed_candidates=(),
                warnings=(),
                engine_version=ENGINE_VERSION,
            )

    def test_duplicate_categories_are_refused_in_the_output(self) -> None:
        with pytest.raises(ValidationError):
            NeedGraphResult(
                award_ref=REF,
                source_mode="metadata_fallback",
                needs=(_need(), _need()),
                suppressed_candidates=(),
                warnings=(),
                engine_version=ENGINE_VERSION,
            )

    def test_suppressed_candidates_keep_their_reason(self) -> None:
        suppressed = SuppressedCandidate(
            category="specialist_subcontracting",
            rule_id="construction-large-multilot-subcontracting-v1",
            reason="single_indicator",
        )
        result = NeedGraphResult(
            award_ref=REF,
            source_mode="metadata_fallback",
            needs=(),
            suppressed_candidates=(suppressed,),
            warnings=(),
            engine_version=ENGINE_VERSION,
        )
        assert result.suppressed_candidates[0].reason == "single_indicator"
