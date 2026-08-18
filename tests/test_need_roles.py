"""SPEC-007R1 §8-§19, §27 — rôles de faits, échelle, profils CPV, règles v0.4.

Le Need Graph V0 comptait des faits sans distinguer leur rôle : « type
construction » et « CPV 45 » comptaient pour deux, alors qu'ils disent la même
chose. R1 sépare les rôles — un besoin `medium` exige **un mécanisme** (pourquoi
cette ressource peut être nécessaire) **et une pression** (pourquoi un appoint
est plausible), jamais deux faits du même rôle.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.domain import EventRef, Evidence
from signals.needs import NeedGraphEngine
from signals.needs.features import (
    MATERIALITY_FLOOR,
    construction_profile,
    extract_features,
    scale_band,
)
from signals.needs.rules import RULE_LIBRARY, RULE_LIBRARY_VERSION
from signals.understanding.model import (
    Claim,
    ContractGeography,
    ContractParties,
    ContractTiming,
    ContractUnderstanding,
)

_EV = Evidence(
    source_system="simap",
    source_kind="publication_field",
    source_notice_id="28066-04",
    path="award.value",
    excerpt="valeur publiée",
)


def _claim(value: str) -> Claim:
    return Claim(
        value=value, confidence="high", kind="source_fact", rule="valeur publiée", evidence=(_EV,)
    )


def _cu(
    *,
    contract_type: str = "construction",
    cpv: str = "45210000",
    amount: str | None = "4500000.00 CHF",
    characteristics: tuple[str, ...] = (),
    duration: tuple[int, str] | None = None,
    start: dt.date | None = None,
) -> ContractUnderstanding:
    facts = {"winner": _claim("Entreprise Alpha SA"), "cpv": _claim(cpv)}
    if amount is not None:
        facts["amount"] = _claim(amount)
    if "several_lots" in characteristics:
        facts["lot"] = _claim("Lot 2")
    return ContractUnderstanding(
        award_ref=EventRef(source_system="simap", source_notice_id="28066-04"),
        source_system="simap",
        contract_type=_claim(contract_type),
        sector=_claim("unknown"),
        object_summary=_claim("Marché « Travaux »"),
        characteristics=tuple(_claim(c) for c in characteristics),
        facts=facts,
        parties=ContractParties(),
        geography=ContractGeography(buyer_country="CH"),
        timing=ContractTiming(
            published_at=dt.date(2026, 8, 1),
            contract_start_date=start,
            duration_value=duration[0] if duration else None,
            duration_unit=duration[1] if duration else None,
        ),
        evidence_coverage=1.0,
        engine_version="contract-understanding-v0.1",
    )


def _categories(cu: ContractUnderstanding) -> set[str]:
    return {need.category for need in NeedGraphEngine().derive(cu).needs}


# ─── §9-§10 — politique d'échelle et garde d'anomalie ───────────────────────────


class TestScalePolicy:
    def test_the_bands_are_deterministic_on_comparable_currencies(self) -> None:
        assert scale_band("26.00 EUR") == "not_material"
        assert scale_band("49999.99 CHF") == "not_material"
        assert scale_band("50000.00 EUR") == "modest"
        assert scale_band("999999.00 CHF") == "modest"
        assert scale_band("1000000.00 EUR") == "large"
        assert scale_band("10000000.00 CHF") == "very_large"

    def test_an_uncomparable_currency_is_never_scaled(self) -> None:
        assert scale_band("3972874.14 PLN") == "unknown"
        assert scale_band("538 RON") == "unknown"
        assert scale_band(None) == "unknown"

    def test_the_materiality_floor_is_explicit(self) -> None:
        assert MATERIALITY_FLOOR == 50_000

    def test_a_derisory_amount_produces_no_need_at_all(self) -> None:
        """§10 — 26 EUR ne justifie aucun besoin, quel que soit le mécanisme."""
        cu = _cu(amount="26.00 EUR", characteristics=("several_lots",))
        result = NeedGraphEngine().derive(cu)
        assert result.needs == ()
        assert any(s.reason == "scale_not_material" for s in result.suppressed_candidates)


# ─── §8 — rôles de faits ────────────────────────────────────────────────────────


class TestFeatureRoles:
    def test_a_mechanism_alone_never_produces_a_need(self) -> None:
        """Type construction + CPV construction = deux fois le même rôle."""
        cu = _cu(amount=None)
        assert _categories(cu) == set()

    def test_a_mechanism_plus_a_pressure_produces_a_need(self) -> None:
        assert _categories(_cu()) != set()

    def test_features_expose_the_two_roles_separately(self) -> None:
        features = extract_features(_cu(characteristics=("several_lots",)))
        assert features.mechanism("construction_machinery")
        assert features.pressure("large_scale")
        assert not features.pressure("defined_period")


class TestFactsThatAreNeverPressure:
    def test_defined_contract_period_is_not_a_pressure_fact(self) -> None:
        """§11 — fait temporel, jamais un second indice."""
        cu = _cu(amount=None, characteristics=("defined_contract_period",))
        assert _categories(cu) == set()
        assert not extract_features(cu).pressure("defined_period")

    def test_several_lots_alone_is_not_a_pressure_fact(self) -> None:
        """§12 — fait structurel ; il ne devient pression qu'avec une échelle connue."""
        cu = _cu(amount=None, characteristics=("several_lots",))
        assert _categories(cu) == set()

    def test_several_lots_with_known_scale_becomes_a_pressure_fact(self) -> None:
        cu = _cu(amount="600000.00 CHF", characteristics=("several_lots",))
        assert extract_features(cu).pressure("parallel_lots_with_scale")


# ─── §13-§14 — profils de ressources CPV ────────────────────────────────────────


class TestConstructionProfiles:
    @pytest.mark.parametrize(
        ("cpv", "profile"),
        [
            ("45112710", "earthworks"),
            ("45210000", "building_civil"),
            ("45232140", "building_civil"),
            ("45310000", "technical_installation"),
            ("45410000", "finishing"),
            ("45500000", "equipment_hire_as_deliverable"),
            ("45000000", "general_or_unknown"),
            (None, "general_or_unknown"),
        ],
    )
    def test_the_profile_is_read_from_the_cpv_prefix(self, cpv: str | None, profile: str) -> None:
        assert construction_profile(cpv) == profile

    def test_a_general_construction_never_yields_machinery(self) -> None:
        """§14 — 1,68 MCHF sans sous-type exploitable ne suffit plus."""
        cu = _cu(cpv="45000000", amount="1686397.50 CHF")
        categories = _categories(cu)
        assert "equipment_or_rental" not in categories
        assert "materials_or_components" not in categories

    def test_a_general_construction_still_yields_workforce(self) -> None:
        cu = _cu(cpv="45000000", amount="1686397.50 CHF")
        assert "workforce_capacity" in _categories(cu)

    def test_earthworks_and_civil_engineering_support_machinery(self) -> None:
        assert "equipment_or_rental" in _categories(_cu(cpv="45112710"))
        assert "equipment_or_rental" in _categories(_cu(cpv="45210000"))

    def test_technical_installation_does_not_take_the_machinery_profile(self) -> None:
        categories = _categories(_cu(cpv="45310000"))
        assert "equipment_or_rental" not in categories
        assert "materials_or_components" in categories

    def test_finishing_does_not_take_the_civil_engineering_profile(self) -> None:
        categories = _categories(_cu(cpv="45410000"))
        assert "equipment_or_rental" not in categories
        assert "materials_or_components" in categories

    def test_equipment_hire_as_deliverable_never_needs_equipment(self) -> None:
        """§17 — louer des engins avec opérateur EST le livrable."""
        assert "equipment_or_rental" not in _categories(_cu(cpv="45500000"))


# ─── §15 — social_health_services ───────────────────────────────────────────────


class TestSocialHealthPressure:
    def test_a_modest_social_health_lot_produces_no_medium_need(self) -> None:
        cu = _cu(
            contract_type="social_health_services",
            cpv="85300000",
            amount="185083.74 EUR",
            characteristics=("several_lots", "defined_contract_period"),
        )
        assert _categories(cu) == set()

    def test_a_large_social_health_contract_supports_workforce(self) -> None:
        cu = _cu(contract_type="social_health_services", cpv="85300000", amount="2500000.00 EUR")
        assert "workforce_capacity" in _categories(cu)

    def test_a_recurring_social_health_service_with_scale_supports_workforce(self) -> None:
        cu = _cu(
            contract_type="social_health_services",
            cpv="85300000",
            amount="400000.00 EUR",
            characteristics=("long_duration",),
            duration=(36, "month"),
        )
        assert "workforce_capacity" in _categories(cu)


# ─── §16-§17 — recouvrement avec le livrable ────────────────────────────────────


class TestDeliverableOverlap:
    def test_a_transport_contract_never_needs_logistics(self) -> None:
        cu = _cu(contract_type="transport_logistics", cpv="60100000")
        assert "logistics_and_transport" not in _categories(cu)

    def test_an_equipment_supplier_never_needs_equipment(self) -> None:
        cu = _cu(contract_type="equipment_supply", cpv="34100000")
        assert "equipment_or_rental" not in _categories(cu)

    def test_a_medical_supplier_never_needs_components(self) -> None:
        cu = _cu(contract_type="medical_supply", cpv="33100000")
        assert "materials_or_components" not in _categories(cu)

    def test_medical_supply_does_not_produce_logistics_by_default(self) -> None:
        """§16 — la livraison est inhérente à la fourniture, pas un besoin de plus."""
        cu = _cu(
            contract_type="medical_supply",
            cpv="33100000",
            amount="845482.00 EUR",
            characteristics=("several_lots",),
        )
        assert "logistics_and_transport" not in _categories(cu)


# ─── §18-§19 — unité de raisonnement et bibliothèque ────────────────────────────


class TestUnitAndLibrary:
    def test_the_result_unit_is_the_award_lot(self) -> None:
        """Une notice à plusieurs lots produit un résultat par award-lot, jamais
        une consolidation de procédure."""
        cu = _cu()
        result = NeedGraphEngine().derive(cu)
        assert result.award_ref == cu.award_ref

    def test_the_library_declares_its_version(self) -> None:
        assert RULE_LIBRARY_VERSION == "need-rules-v0.5"

    def test_every_rule_declares_both_roles(self) -> None:
        for rule in RULE_LIBRARY:
            assert rule.mechanism_predicates, rule.rule_id
            assert rule.pressure_predicates, rule.rule_id
            assert rule.category
            assert rule.externalisability


# ─── §27 — non-régression SPEC-006 ──────────────────────────────────────────────


class TestSpec006NonRegression:
    def test_auto_document_requirements_stay_disabled(self) -> None:
        from signals.documents import AUTO_DOCUMENT_REQUIREMENTS_ENABLED

        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False
