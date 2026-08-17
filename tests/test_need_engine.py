"""SPEC-007 §12-§20 — le moteur : features déterministes, règles, bornes.

Pipeline attendu (§16) :

    ContractUnderstanding
      → extraction déterministe de features
      → règles applicables → candidats
      → règles négatives (deliverable ≠ besoin, anti-inférences)
      → liaison des preuves (Evidence des claims d'entrée)
      → politique de confiance (medium = 2 faits indépendants)
      → déduplication par catégorie canonique
      → ranking déterministe → top 0-3

Aucun LLM, aucun réseau : tout est déductible des champs canoniques.
"""

from __future__ import annotations

import datetime as dt

from signals.domain import EventRef, Evidence
from signals.needs import ENGINE_VERSION, NeedGraphEngine
from signals.needs.features import extract_features, scale_band
from signals.understanding.model import (
    Claim,
    ContractGeography,
    ContractParties,
    ContractTiming,
    ContractUnderstanding,
)

_EV = Evidence(
    source_system="ted",
    source_kind="publication_field",
    source_notice_id="565997-2026",
    path="BT-27",
    excerpt="valeur publiée",
)


def _claim(value: str, rule: str = "valeur publiée dans l'avis") -> Claim:
    return Claim(value=value, confidence="high", kind="source_fact", rule=rule, evidence=(_EV,))


def _cu(
    *,
    contract_type: str = "construction",
    amount: str | None = "4500000.00 EUR",
    characteristics: tuple[str, ...] = (),
    duration: tuple[int, str] | None = None,
    start: dt.date | None = None,
    published: dt.date | None = dt.date(2026, 8, 1),
) -> ContractUnderstanding:
    facts = {"winner": _claim("Entreprise Alpha SA"), "cpv": _claim("45210000")}
    if amount is not None:
        facts["amount"] = _claim(amount)
    if "several_lots" in characteristics:
        facts["lot"] = _claim("Lot 2")
    timing = ContractTiming(
        published_at=published,
        contract_start_date=start,
        duration_value=duration[0] if duration else None,
        duration_unit=duration[1] if duration else None,
    )
    return ContractUnderstanding(
        award_ref=EventRef(source_system="ted", source_notice_id="565997-2026"),
        source_system="ted",
        contract_type=_claim(contract_type),
        sector=_claim("unknown", rule=None),
        object_summary=_claim("Marché « Travaux de gros œuvre »"),
        characteristics=tuple(_claim(c) for c in characteristics),
        facts=facts,
        parties=ContractParties(),
        geography=ContractGeography(buyer_country="FR"),
        timing=timing,
        evidence_coverage=1.0,
        engine_version="contract-understanding-v0.1",
    )


class TestEconomicScale:
    """Bandes d'échelle — SPEC-007R1 §9 affine la binarité de V0 en cinq bandes."""

    def test_a_large_eur_amount_is_large(self) -> None:
        assert scale_band("4500000.00 EUR") == "large"
        assert scale_band("1500000 CHF") == "large"

    def test_a_modest_amount_stays_modest(self) -> None:
        assert scale_band("192396.26 EUR") == "modest"

    def test_an_uncovered_currency_is_never_scaled(self) -> None:
        """Aucune conversion inventée : 3 972 874 PLN n'est ni large ni modest."""
        assert scale_band("3972874.14 PLN") == "unknown"

    def test_a_missing_amount_is_unknown(self) -> None:
        assert scale_band(None) == "unknown"


class TestFeatureExtraction:
    def test_features_read_only_canonical_fields(self) -> None:
        cu = _cu(characteristics=("several_lots", "long_duration"), duration=(48, "month"))
        features = extract_features(cu)
        assert features.contract_type == "construction"
        assert features.scale_band == "large"
        assert features.several_lots and features.long_duration
        assert features.duration_months == 48

    def test_a_service_with_published_duration_is_recurring(self) -> None:
        cu = _cu(contract_type="facility_services", duration=(24, "month"))
        assert extract_features(cu).recurring_service is True

    def test_construction_is_not_a_recurring_service(self) -> None:
        cu = _cu(duration=(24, "month"))
        assert extract_features(cu).recurring_service is False


class TestTimingPolicy:
    def test_no_start_date_means_unknown_never_invented(self) -> None:
        result = NeedGraphEngine().derive(_cu(start=None))
        assert all(need.timing == "unknown" for need in result.needs)

    def test_award_date_is_never_treated_as_a_start(self) -> None:
        cu = _cu(start=None)
        cu = cu.model_copy(
            update={"timing": cu.timing.model_copy(update={"award_date": dt.date(2026, 7, 30)})}
        )
        result = NeedGraphEngine().derive(cu)
        assert all(need.timing == "unknown" for need in result.needs)

    def test_a_start_within_thirty_days_is_immediate(self) -> None:
        result = NeedGraphEngine().derive(_cu(start=dt.date(2026, 8, 20)))
        assert result.needs and all(need.timing == "immediate" for need in result.needs)

    def test_a_start_within_ninety_days_is_near_term(self) -> None:
        result = NeedGraphEngine().derive(_cu(start=dt.date(2026, 10, 15)))
        assert result.needs and all(need.timing == "near_term" for need in result.needs)

    def test_a_recurring_service_is_recurring_even_without_a_start(self) -> None:
        cu = _cu(
            contract_type="facility_services",
            characteristics=("long_duration",),
            duration=(36, "month"),
        )
        result = NeedGraphEngine().derive(cu)
        assert result.needs and all(need.timing == "recurring" for need in result.needs)


class TestCandidateGeneration:
    def test_a_large_construction_yields_at_most_three_supported_needs(self) -> None:
        result = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        assert 1 <= len(result.needs) <= 3
        for need in result.needs:
            assert need.confidence == "medium"
            assert need.rule_ids
            assert need.evidence_refs
            assert need.mechanism_facts and need.pressure_facts
            assert need.source_mode == "metadata_fallback"
            assert need.engine_version == ENGINE_VERSION

    def test_needs_are_ranked_deterministically(self) -> None:
        first = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        second = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        assert [n.category for n in first.needs] == [n.category for n in second.needs]

    def test_a_mechanism_without_any_pressure_is_suppressed(self) -> None:
        """SPEC-007R1 §8 — un mécanisme seul reste `plausible_but_weak` : le
        moteur le garde en diagnostic, jamais en sortie."""
        result = NeedGraphEngine().derive(_cu(amount=None))
        assert result.needs == ()
        assert result.suppressed_candidates
        assert all(s.reason == "no_pressure_fact" for s in result.suppressed_candidates)

    def test_an_information_poor_contract_yields_nothing(self) -> None:
        result = NeedGraphEngine().derive(_cu(contract_type="business_services", amount=None))
        assert result.needs == ()

    def test_subcontracting_requires_three_converging_signals(self) -> None:
        without_lots = NeedGraphEngine().derive(_cu())
        assert "specialist_subcontracting" not in {n.category for n in without_lots.needs}
        with_lots = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        subs = [n for n in with_lots.needs if n.category == "specialist_subcontracting"]
        if subs:
            assert subs[0].mechanism_facts and len(subs[0].pressure_facts) >= 2


class TestDeliverableIsNeverTheNeed:
    def test_a_transport_contract_never_needs_transport(self) -> None:
        cu = _cu(contract_type="transport_logistics", characteristics=("several_lots",))
        result = NeedGraphEngine().derive(cu)
        assert "logistics_and_transport" not in {n.category for n in result.needs}

    def test_an_equipment_supplier_never_needs_equipment_rental(self) -> None:
        cu = _cu(contract_type="equipment_supply", characteristics=("several_lots",))
        result = NeedGraphEngine().derive(cu)
        categories = {n.category for n in result.needs}
        assert "equipment_or_rental" not in categories
        assert "materials_or_components" not in categories

    def test_a_medical_supplier_never_needs_distribution(self) -> None:
        """SPEC-007R1 §16 — la livraison est inhérente à la fourniture ; aucun
        fait canonique ne démontre une distribution structurée en plus."""
        cu = _cu(contract_type="medical_supply", characteristics=("several_lots",))
        result = NeedGraphEngine().derive(cu)
        assert "logistics_and_transport" not in {n.category for n in result.needs}


class TestDeduplication:
    def test_two_rules_on_the_same_category_merge_into_one_need(self) -> None:
        """Construction large + longue durée : deux règles safety/workforce
        peuvent converger — jamais deux besoins de même catégorie."""
        cu = _cu(characteristics=("several_lots", "long_duration"), duration=(36, "month"))
        result = NeedGraphEngine().derive(cu)
        categories = [n.category for n in result.needs]
        assert len(categories) == len(set(categories))


class TestExternalisability:
    def test_nothing_is_ever_certainly_external(self) -> None:
        result = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        for need in result.needs:
            assert need.externalisability in (
                "likely_internal",
                "mixed",
                "external_plausible",
                "unknown",
            )

    def test_external_plausible_requires_several_signals(self) -> None:
        result = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        for need in result.needs:
            if need.externalisability == "external_plausible":
                assert len(set(need.pressure_facts)) >= 2
