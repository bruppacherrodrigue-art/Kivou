"""SPEC-007 §37-§39 — les cas adversariaux A-L, le wording, la non-régression.

Chaque cas est une tentation mesurée sur le corpus : produire un besoin qui
répète le contrat, gonfler un indice unique en signal, inventer un timing,
transformer un montant en plan de recrutement. Le moteur doit résister à
chacune — structurellement, pas par bonne volonté.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.domain import EventRef, Evidence
from signals.needs import NeedGraphEngine
from signals.needs.model import _CERTAINTY_WORDING, _HYPOTHETICAL_MARKERS
from signals.needs.rules import RULE_LIBRARY, NeedRule
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
    amount: str | None = "4500000.00 CHF",
    characteristics: tuple[str, ...] = (),
    duration: tuple[int, str] | None = None,
    start: dt.date | None = None,
    summary: str = "Marché « Travaux »",
) -> ContractUnderstanding:
    facts = {"winner": _claim("Entreprise Alpha SA"), "cpv": _claim("45210000")}
    if amount is not None:
        facts["amount"] = _claim(amount)
    if "several_lots" in characteristics:
        facts["lot"] = _claim("Lot 2")
    return ContractUnderstanding(
        award_ref=EventRef(source_system="simap", source_notice_id="28066-04"),
        source_system="simap",
        contract_type=_claim(contract_type),
        sector=_claim("unknown"),
        object_summary=_claim(summary),
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


class TestCaseA_InformationPoorContract:
    def test_a_large_but_opaque_contract_yields_nothing(self) -> None:
        """Gros montant, type sans règle : aucun besoin forcé pour remplir la fiche."""
        result = NeedGraphEngine().derive(
            _cu(contract_type="business_services", amount="9000000.00 EUR")
        )
        assert result.needs == ()

    def test_an_unknown_type_yields_nothing(self) -> None:
        result = NeedGraphEngine().derive(_cu(contract_type="unknown"))
        assert result.needs == ()


class TestCaseB_CleaningContract:
    def test_cleaning_is_never_returned_as_a_need(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(
                contract_type="facility_services",
                characteristics=("long_duration",),
                duration=(36, "month"),
            )
        )
        for need in result.needs:
            assert "facility" not in need.category
            assert "nettoyage" not in need.statement.casefold()
        # La capacité de personnel, elle, est un intrant légitime (§11).
        assert {n.category for n in result.needs} <= {"workforce_capacity"}


class TestCaseC_SoftwareWithoutSecurityInfo:
    def test_cybersecurity_is_structurally_impossible(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(contract_type="it_digital", characteristics=("several_lots",))
        )
        assert all("cyber" not in need.category for need in result.needs)
        assert all("cyber" not in rule.category for rule in RULE_LIBRARY)


class TestCaseD_SupplyContract:
    def test_no_staffing_from_amount_alone(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(contract_type="equipment_supply", amount="9000000.00 EUR")
        )
        assert "workforce_capacity" not in {n.category for n in result.needs}


class TestCaseE_LargeMultiLotConstruction:
    def test_equipment_is_plausible_when_several_facts_support_it(self) -> None:
        """Sur un chantier de grande échelle, le matériel est un besoin soutenu
        par deux faits (type + échelle) — il atteint la sortie."""
        result = NeedGraphEngine().derive(_cu())
        equipment = [n for n in result.needs if n.category == "equipment_or_rental"]
        assert equipment
        assert equipment[0].mechanism_facts and equipment[0].pressure_facts

    def test_a_multi_lot_chantier_is_capped_at_three_best_supported_needs(self) -> None:
        """Le chantier ouvre plus de trois mécanismes : le ranking en garde
        trois, et nomme ceux qu'il a écartés."""
        result = NeedGraphEngine().derive(_cu(characteristics=("several_lots",)))
        assert len(result.needs) == 3
        for need in result.needs:
            assert need.mechanism_facts and need.pressure_facts
        assert any(s.reason == "ranked_below_top_three" for s in result.suppressed_candidates)


class TestCaseF_ConsultingContract:
    def test_no_equipment_rental_for_intellectual_services(self) -> None:
        for contract_type in ("business_services", "engineering_architecture"):
            result = NeedGraphEngine().derive(
                _cu(contract_type=contract_type, characteristics=("several_lots",))
            )
            assert "equipment_or_rental" not in {n.category for n in result.needs}


class TestCaseG_MissingStartDate:
    def test_timing_is_unknown_never_invented(self) -> None:
        result = NeedGraphEngine().derive(_cu(start=None))
        assert result.needs and all(n.timing == "unknown" for n in result.needs)


class TestCaseH_AlreadyStartedContracts:
    def test_a_started_recurring_service_is_recurring(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(
                contract_type="security_services",
                characteristics=("long_duration",),
                duration=(48, "month"),
                start=dt.date(2026, 7, 1),
            )
        )
        assert result.needs and all(n.timing == "recurring" for n in result.needs)

    def test_a_started_one_off_contract_is_immediate(self) -> None:
        result = NeedGraphEngine().derive(_cu(start=dt.date(2026, 7, 15)))
        assert result.needs and all(n.timing == "immediate" for n in result.needs)


class TestCaseI_DeliverableRepetition:
    def test_the_deliverable_category_is_suppressed_with_its_reason(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(contract_type="transport_logistics", characteristics=("several_lots",))
        )
        assert "logistics_and_transport" not in {n.category for n in result.needs}
        # Un fournisseur d'équipements ne « découvre » ni équipement ni
        # composants : la garde de recouvrement les écarte avec leur motif.
        supply = NeedGraphEngine().derive(
            _cu(contract_type="equipment_supply", characteristics=("several_lots",))
        )
        categories = {n.category for n in supply.needs}
        assert "equipment_or_rental" not in categories
        assert "materials_or_components" not in categories
        assert "logistics_and_transport" not in categories


class TestCaseJ_ExperimentalSpec006Outputs:
    def test_the_engine_only_consumes_contract_understanding(self) -> None:
        import inspect

        from signals.needs.engine import NeedGraphEngine as Engine

        parameters = inspect.signature(Engine.derive).parameters
        assert list(parameters) == ["self", "cu"]

    def test_the_needs_package_never_imports_the_documents_pipeline(self) -> None:
        import pathlib

        for path in pathlib.Path("src/signals/needs").glob("*.py"):
            assert "signals.documents" not in path.read_text(), path

    def test_spec006_auto_accept_stays_disabled(self) -> None:
        """§39 — la non-régression SPEC-006, épinglée ici aussi."""
        from signals.documents import AUTO_DOCUMENT_REQUIREMENTS_ENABLED

        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False


class TestCaseK_UnsupportedLanguage:
    def test_canonical_facts_work_regardless_of_language(self) -> None:
        """§26 — les faits canoniques restent utilisables ; le texte libre, jamais."""
        result = NeedGraphEngine().derive(
            _cu(summary="Marché « ИЗБОР НА ДОСТАВЧИК НА НЕТНА АКТИВНА ЕЛЕКТРИЧЕСКА ЕНЕРГИЯ »")
        )
        # Le résumé bulgare n'a aucun effet : seules les features canoniques comptent.
        assert result.needs

    def test_without_canonical_facts_nothing_is_returned(self) -> None:
        result = NeedGraphEngine().derive(
            _cu(contract_type="unknown", amount=None, summary="Доставка на електрическа енергия")
        )
        assert result.needs == ()


class TestCaseL_TwoRulesSameCategory:
    def test_converging_rules_merge_into_one_need_with_both_rule_ids(self) -> None:
        first = next(r for r in RULE_LIBRARY if r.category == "workforce_capacity")
        twin = NeedRule(
            rule_id="workforce-construction-twin-v1",
            category="workforce_capacity",
            mechanism_predicates=("construction_site",),
            pressure_predicates=("parallel_lots_with_scale",),
            statement_template=first.statement_template,
            reasoning_template=first.reasoning_template,
            externalisability="mixed",
        )
        engine = NeedGraphEngine(rules=(first, twin))
        result = engine.derive(_cu(characteristics=("several_lots",)))
        workforce = [n for n in result.needs if n.category == "workforce_capacity"]
        assert len(workforce) == 1
        assert set(workforce[0].rule_ids) == {first.rule_id, "workforce-construction-twin-v1"}
        assert workforce[0].mechanism_facts and workforce[0].pressure_facts


class TestWordingPolicy:
    @pytest.mark.parametrize("rule", RULE_LIBRARY, ids=lambda r: r.rule_id)
    def test_every_rule_template_is_hypothetical_and_certainty_free(self, rule) -> None:
        assert not _CERTAINTY_WORDING.search(rule.statement_template)
        assert not _CERTAINTY_WORDING.search(rule.reasoning_template)
        assert _HYPOTHETICAL_MARKERS.search(rule.reasoning_template)

    def test_no_rule_uses_recruitment_vocabulary(self) -> None:
        """§15 — le concept canonique est workforce_capacity : Kivou ne sait pas
        si le gagnant recrutera, intérimera, réaffectera ou sous-traitera."""
        for rule in RULE_LIBRARY:
            assert "recrut" not in rule.statement_template.casefold()
            assert "embauch" not in rule.statement_template.casefold()
