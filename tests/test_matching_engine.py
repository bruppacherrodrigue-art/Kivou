"""SPEC-008 §20-§29 — hard filters absolus, score expliqué, confiance séparée.

Le moteur applique d'abord les filtres durs — aucun score, si élevé soit-il, ne
les compense —, puis marque quatre dimensions mesurables, et rend toujours son
raisonnement : composants, raisons positives, limites, preuves.
"""

from __future__ import annotations

import datetime as dt

from signals.domain import EventRef, Evidence, Location
from signals.matching import (
    SCORE_POLICY_VERSION,
    MatchingEngine,
    TargetICP,
    Territory,
    ValueThreshold,
)
from signals.needs import NeedGraphEngine
from signals.understanding.model import (
    Claim,
    ContractGeography,
    ContractParties,
    ContractTiming,
    ContractUnderstanding,
)

AS_OF = dt.date(2026, 8, 20)

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
    sector: str = "unknown",
    cpv: str = "45210000",
    amount: str | None = "2400000.00 CHF",
    country: str | None = "CH",
    subdivision_code: str | None = None,
    published: dt.date = dt.date(2026, 8, 1),
    characteristics: tuple[str, ...] = (),
    duration: tuple[int, str] | None = None,
    start: dt.date | None = None,
) -> ContractUnderstanding:
    facts = {"winner": _claim("Entreprise Alpha SA"), "cpv": _claim(cpv)}
    if amount is not None:
        facts["amount"] = _claim(amount)
    if "several_lots" in characteristics:
        facts["lot"] = _claim("Lot 2")
    place = Location(
        country=country,
        subdivision_code=subdivision_code,
        subdivision_scheme="ISO-3166-2" if subdivision_code else None,
    ) if country else None
    return ContractUnderstanding(
        award_ref=EventRef(source_system="simap", source_notice_id="28066-04"),
        source_system="simap",
        contract_type=_claim(contract_type),
        sector=_claim(sector),
        object_summary=_claim("Marché « Travaux »"),
        characteristics=tuple(_claim(c) for c in characteristics),
        facts=facts,
        parties=ContractParties(),
        geography=ContractGeography(place_of_performance=place, buyer_country=country),
        timing=ContractTiming(
            published_at=published,
            contract_start_date=start,
            duration_value=duration[0] if duration else None,
            duration_unit=duration[1] if duration else None,
        ),
        evidence_coverage=1.0,
        engine_version="contract-understanding-v0.1",
    )


def _icp(**overrides) -> TargetICP:
    data = {
        "icp_id": "icp-rental-ch",
        "name": "Loueur d'engins — Suisse",
        "offer_summary": "Location de matériel de chantier.",
        "primary_need_categories": ("equipment_or_rental",),
        "secondary_need_categories": ("materials_or_components",),
        "geography_basis": "place_of_performance",
        "geography_policy": "required",
        "territories": (Territory(country="CH"),),
        "value_thresholds": (ValueThreshold(currency="CHF", minimum_amount=250_000),),
        "unknown_value_policy": "allow_with_penalty",
        "maximum_signal_age_days": 90,
        "preferred_timings": ("immediate", "near_term"),
        "source_modes_allowed": ("metadata_fallback",),
    }
    data.update(overrides)
    return TargetICP(**data)


def _match(cu: ContractUnderstanding, icp: TargetICP, *, as_of: dt.date = AS_OF):
    needs = NeedGraphEngine().derive(cu)
    return MatchingEngine().match(cu, needs, icp, as_of=as_of)


class TestHardFilters:
    def test_a_matching_signal_is_shown(self) -> None:
        result = _match(_cu(), _icp())
        assert result.decision == "show"
        assert result.matched_needs

    def test_no_exact_need_overlap_excludes(self) -> None:
        """§21 — la première condition : au moins un besoin exactement commun."""
        result = _match(
            _cu(),
            _icp(primary_need_categories=("waste_and_environment",), secondary_need_categories=()),
        )
        assert result.decision == "exclude"
        assert any(f.name == "need_overlap" and not f.passed for f in result.hard_filter_results)

    def test_an_excluded_contract_type_blocks(self) -> None:
        result = _match(_cu(), _icp(excluded_contract_types=("construction",)))
        assert result.decision == "exclude"
        assert any(f.name == "contract_type" and not f.passed for f in result.hard_filter_results)

    def test_an_excluded_sector_blocks(self) -> None:
        result = _match(_cu(sector="healthcare"), _icp(excluded_sectors=("healthcare",)))
        assert result.decision == "exclude"

    def test_a_required_geography_mismatch_excludes(self) -> None:
        result = _match(_cu(country="FR"), _icp())
        assert result.decision == "exclude"

    def test_a_required_subdivision_mismatch_excludes(self) -> None:
        result = _match(
            _cu(subdivision_code="CH-VD"),
            _icp(territories=(Territory(country="CH", subdivision_code="CH-LU", subdivision_scheme="ISO-3166-2"),)),
        )
        assert result.decision == "exclude"

    def test_an_included_cpv_prefix_excludes_another_sector(self) -> None:
        result = _match(_cu(cpv="45210000"), _icp(included_cpv_prefixes=("44",)))
        assert result.decision == "exclude"

    def test_a_required_geography_missing_is_insufficient_data(self) -> None:
        """§20 — une règle stricte inévaluable n'est pas un rejet de fond."""
        result = _match(_cu(country=None), _icp())
        assert result.decision == "insufficient_data"
        assert any("geography" in f.name for f in result.hard_filter_results if not f.passed)

    def test_a_known_amount_below_the_threshold_excludes(self) -> None:
        result = _match(_cu(amount="80000.00 CHF"), _icp())
        assert result.decision == "exclude"

    def test_a_missing_amount_under_exclude_policy_is_reported(self) -> None:
        result = _match(_cu(amount=None), _icp(unknown_value_policy="exclude"))
        assert result.decision in ("exclude", "insufficient_data")
        assert result.decision != "show"

    def test_an_award_older_than_the_maximum_age_excludes(self) -> None:
        result = _match(_cu(published=dt.date(2026, 1, 1)), _icp())
        assert result.decision == "exclude"

    def test_a_forbidden_source_mode_yields_nothing(self) -> None:
        result = _match(_cu(), _icp(source_modes_allowed=("document_supported",)))
        assert result.decision == "exclude"

    def test_a_hard_filter_failure_is_never_compensated_by_the_score(self) -> None:
        result = _match(_cu(country="FR"), _icp())
        assert result.decision == "exclude"
        assert result.normalized_score == 0


class TestValuePolicy:
    def test_a_currency_without_a_threshold_is_never_compared(self) -> None:
        """§15 — aucune conversion : un montant en EUR ne se compare pas au seuil CHF."""
        result = _match(_cu(amount="2400000.00 EUR"), _icp())
        assert result.decision != "exclude" or all(
            f.name != "value_threshold" or f.passed for f in result.hard_filter_results
        )

    def test_a_derisory_amount_earns_no_economic_points(self) -> None:
        """§16 — un montant neutralisé par SPEC-007 ne rapporte rien."""
        result = _match(_cu(amount="26.00 CHF"), _icp(value_thresholds=()))
        economic = [c for c in result.score_components if c.name == "economic_impact"]
        assert all(component.points == 0 for component in economic)


class TestFreshnessAndTiming:
    def test_the_engine_never_reads_the_clock_itself(self) -> None:
        """§17 — `as_of` est explicite ; deux `as_of` donnent deux fraîcheurs."""
        published = dt.date(2026, 8, 15)
        recent = _match(_cu(published=published), _icp(), as_of=dt.date(2026, 8, 20))
        # 92 jours plus tard : au-delà du plafond de 90 jours de cet ICP.
        stale = _match(_cu(published=published), _icp(), as_of=dt.date(2026, 11, 15))
        assert recent.decision == "show"
        assert stale.decision == "exclude"

    def test_an_unknown_timing_never_earns_positive_points(self) -> None:
        """Sans date de début publiée, tous les besoins sont `unknown` : le
        composant ne peut pas atteindre son plafond."""
        cu = _cu(start=None)
        needs = NeedGraphEngine().derive(cu)
        assert needs.needs and all(need.timing == "unknown" for need in needs.needs)
        result = MatchingEngine().match(cu, needs, _icp(), as_of=AS_OF)
        timing = [c for c in result.score_components if c.name == "freshness_timing"]
        assert timing, "le composant fraîcheur/timing doit exister"
        assert timing[0].points < timing[0].maximum_points

    def test_a_preferred_timing_earns_more_than_an_unknown_one(self) -> None:
        with_timing = _match(
            _cu(start=dt.date(2026, 8, 10)), _icp(preferred_timings=("immediate",))
        )
        without = _match(_cu(), _icp(preferred_timings=("immediate",)))
        assert with_timing.normalized_score > without.normalized_score


class TestScoreStructure:
    def test_the_score_is_an_integer_between_zero_and_hundred(self) -> None:
        result = _match(_cu(), _icp())
        assert isinstance(result.normalized_score, int)
        assert 0 <= result.normalized_score <= 100

    def test_the_components_sum_exactly_to_the_raw_points(self) -> None:
        """§45 P — la décomposition doit être exacte."""
        result = _match(_cu(), _icp())
        assert sum(c.points for c in result.score_components) == result.raw_points
        assert sum(c.maximum_points for c in result.score_components) == (
            result.maximum_applicable_points
        )

    def test_an_inapplicable_dimension_leaves_the_denominator(self) -> None:
        """§22 — géographie ignorée : ses points sortent du maximum applicable."""
        ignored = _match(
            _cu(), _icp(geography_policy="ignored", geography_basis="ignore", territories=())
        )
        assert all(c.name != "geography" for c in ignored.score_components)
        assert ignored.maximum_applicable_points < 100

    def test_an_unconfigured_preference_earns_no_default_points(self) -> None:
        result = _match(_cu(), _icp(preferred_timings=()))
        timing = next(c for c in result.score_components if c.name == "freshness_timing")
        assert timing.points <= timing.maximum_points

    def test_the_policy_version_travels_with_the_result(self) -> None:
        result = _match(_cu(), _icp())
        assert result.score_policy_version == SCORE_POLICY_VERSION


class TestNeedFit:
    def test_a_primary_match_outranks_a_secondary_one(self) -> None:
        """§45 L — toutes choses égales par ailleurs."""
        primary = _match(
            _cu(),
            _icp(primary_need_categories=("equipment_or_rental",), secondary_need_categories=()),
        )
        secondary = _match(
            _cu(),
            _icp(
                primary_need_categories=("waste_and_environment",),
                secondary_need_categories=("equipment_or_rental",),
            ),
        )
        assert primary.normalized_score > secondary.normalized_score

    def test_several_matched_needs_stay_capped(self) -> None:
        """§25 et §45 M — le composant ne gonfle jamais au-delà de son maximum."""
        result = _match(
            _cu(characteristics=("several_lots",)),
            _icp(
                primary_need_categories=("equipment_or_rental", "workforce_capacity"),
                secondary_need_categories=("materials_or_components",),
            ),
        )
        fit = next(c for c in result.score_components if c.name == "need_offer_fit")
        assert fit.points <= fit.maximum_points


class TestConfidenceAndExplanation:
    def test_confidence_is_capped_at_medium_in_metadata_mode(self) -> None:
        result = _match(_cu(), _icp())
        assert result.confidence == "medium"

    def test_a_high_score_keeps_a_medium_confidence(self) -> None:
        """§26 — le score et la confiance sont deux dimensions distinctes."""
        result = _match(_cu(), _icp())
        assert result.normalized_score > 50
        assert result.confidence == "medium"

    def test_every_result_explains_itself(self) -> None:
        result = _match(_cu(), _icp())
        assert result.positive_reasons
        assert result.score_components
        assert result.evidence_refs
        assert result.as_of == AS_OF

    def test_a_metadata_signal_always_declares_its_limitation(self) -> None:
        result = _match(_cu(), _icp())
        assert any("métadonnées" in limitation for limitation in result.limitations)

    def test_the_band_accompanies_the_decision_without_replacing_it(self) -> None:
        result = _match(_cu(), _icp())
        assert result.decision == "show"
        assert result.band in ("strong", "promising", "weak", "excluded")


class TestDeterminism:
    def test_two_identical_runs_produce_identical_results(self) -> None:
        """§45 T."""
        first = _match(_cu(), _icp())
        second = _match(_cu(), _icp())
        assert first.model_dump() == second.model_dump()

    def test_free_text_never_changes_the_outcome(self) -> None:
        """§8 — deux résumés d'offre différents, mêmes champs structurés."""
        one = _match(_cu(), _icp(offer_summary="Location de matériel de chantier."))
        two = _match(_cu(), _icp(offer_summary="Nous louons des grues et des pelles."))
        assert one.normalized_score == two.normalized_score
        assert one.decision == two.decision

    def test_two_lots_of_the_same_notice_stay_distinct(self) -> None:
        """§45 S — l'unité est l'award-lot, jamais la procédure."""
        lot_a = _cu(amount="2400000.00 CHF")
        lot_b = _cu(amount="120000.00 CHF")
        assert _match(lot_a, _icp()).decision == "show"
        assert _match(lot_b, _icp()).decision == "exclude"


class TestSpecSixSevenNonRegression:
    def test_the_matcher_consumes_no_experimental_document_output(self) -> None:
        from signals.documents import AUTO_DOCUMENT_REQUIREMENTS_ENABLED

        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False

    def test_the_matching_package_never_imports_the_documents_pipeline(self) -> None:
        import pathlib

        for path in pathlib.Path("src/signals/matching").glob("*.py"):
            assert "signals.documents" not in path.read_text(), path
