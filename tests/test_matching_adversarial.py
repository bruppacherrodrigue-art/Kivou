"""SPEC-008 §45 — vingt cas adverses, un par lettre A à T.

Chaque test attaque une manière précise dont le moteur pourrait fabriquer un
signal : une géographie devinée, une devise convertie en douce, un secteur
inconnu compté comme positif, un timing absent transformé en point, une sortie
documentaire expérimentale réintroduite par la bande.

Les fixtures de construction viennent de `test_matching_engine` : un seul jeu de
helpers pour tout le matching, aucune duplication. Aucun mock : le moteur, le
Need Graph et les modèles pydantic réels sont exercés de bout en bout.
"""

from __future__ import annotations

import ast
import datetime as dt
import pathlib
import typing

import pytest
from pydantic import ValidationError
from test_matching_engine import _EV, AS_OF, _cu, _icp, _match

from signals.domain import Location, OrganizationRef
from signals.matching import (
    MATCH_POLICY_VERSION,
    SCORE_POLICY_VERSION,
    HardFilterResult,
    MatchingEngine,
    ScoredSignalMatch,
    SignalConfidence,
    SignalScoreComponent,
    TargetICP,
    Territory,
)
from signals.needs import NeedGraphEngine
from signals.understanding.model import ContractGeography, ContractParties

_MATCHING_PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "src" / "signals" / "matching"

ACQUISITION_TOKENS = (
    "apollo",
    "instantly",
    "campaign",
    "contact",
    "mailbox",
    "email",
    "prospect",
    "reply_rate",
)
"""Le vocabulaire de l'Acquisition Engine — interdit de séjour dans le produit client."""

DOCUMENT_TOKENS = ("document", "requirement", "dce", "extraction")


def _filter(result: ScoredSignalMatch, name: str) -> HardFilterResult:
    """Le filtre dur portant CE nom — son absence est en soi une information."""
    matching = [entry for entry in result.hard_filter_results if entry.name == name]
    assert matching, f"filtre « {name} » absent de {[f.name for f in result.hard_filter_results]}"
    return matching[0]


def _component(result: ScoredSignalMatch, name: str) -> SignalScoreComponent:
    matching = [entry for entry in result.score_components if entry.name == name]
    assert matching, f"composant « {name} » absent de {[c.name for c in result.score_components]}"
    return matching[0]


def _scored(**overrides) -> ScoredSignalMatch:
    """Un `ScoredSignalMatch` complet et valide, que chaque test dégrade à sa façon."""
    data = {
        "award_ref": _cu().award_ref,
        "icp_id": "icp-rental-ch",
        "as_of": AS_OF,
        "decision": "show",
        "band": "strong",
        "confidence": "medium",
        "raw_points": 45,
        "maximum_applicable_points": 45,
        "normalized_score": 100,
        "score_components": (
            SignalScoreComponent(
                name="need_offer_fit",
                points=45,
                maximum_points=45,
                detail="besoin principal correspondant : equipment_or_rental",
            ),
        ),
        "hard_filter_results": (
            HardFilterResult(name="need_overlap", passed=True, detail="besoin commun"),
        ),
        "matched_needs": ("equipment_or_rental",),
        "positive_reasons": ("besoin principal de l'ICP couvert",),
        "limitations": (),
        "evidence_refs": (_EV,),
        "match_policy_version": MATCH_POLICY_VERSION,
        "score_policy_version": SCORE_POLICY_VERSION,
    }
    data.update(overrides)
    return ScoredSignalMatch(**data)


def test_adversarial_a_exact_need_wrong_required_geography() -> None:
    """§45 A — besoin exact, mauvaise géographie `required` → décision `exclude`."""
    result = _match(_cu(country="FR"), _icp())

    # Le besoin correspond exactement : seule la géographie doit décider.
    assert _filter(result, "need_overlap").passed
    assert result.decision == "exclude"
    geography = _filter(result, "geography")
    assert not geography.passed
    assert geography.evaluable, "la règle était évaluable : c'est un rejet de fond, pas un manque"
    assert result.normalized_score == 0
    assert result.positive_reasons == ()


def test_adversarial_b_right_geography_no_common_need() -> None:
    """§45 B — bonne géographie, aucun besoin commun → décision `exclude`."""
    result = _match(
        _cu(),
        _icp(primary_need_categories=("waste_and_environment",), secondary_need_categories=()),
    )

    assert _filter(result, "geography").passed
    assert not _filter(result, "need_overlap").passed
    assert result.decision == "exclude"
    assert result.matched_needs == ()
    assert result.score_components == ()


def test_adversarial_c_known_amount_below_the_minimum() -> None:
    """§45 C — montant connu sous le minimum → décision `exclude`."""
    result = _match(_cu(amount="80000.00 CHF"), _icp())

    assert result.decision == "exclude"
    value = _filter(result, "value_threshold")
    assert not value.passed
    assert value.evaluable, "un montant publié et comparable est évaluable"
    assert "sous le minimum" in value.detail
    assert result.normalized_score == 0


def test_adversarial_d_missing_amount_under_exclude_policy() -> None:
    """§45 D — montant absent avec `unknown_value_policy="exclude"` → jamais montré."""
    result = _match(_cu(amount=None), _icp(unknown_value_policy="exclude"))

    missing = _filter(result, "value_missing")
    assert not missing.passed
    assert result.decision in ("insufficient_data", "exclude")
    # La politique implémentée choisit entre les deux par l'évaluabilité de la règle.
    expected = "exclude" if missing.evaluable else "insufficient_data"
    assert result.decision == expected
    assert result.normalized_score == 0


def test_adversarial_e_currency_without_a_matching_threshold() -> None:
    """§45 E — devise sans seuil correspondant → aucune comparaison inventée."""
    neutral = _match(_cu(amount="2400000.00 EUR"), _icp())

    # Aucun seuil CHF n'est appliqué à un montant EUR : la comparaison n'existe pas.
    assert all(entry.name != "value_threshold" for entry in neutral.hard_filter_results)
    currency = _filter(neutral, "value_currency")
    assert currency.passed, "un échec fabriqué faute de conversion serait un faux rejet"
    assert _component(neutral, "economic_impact").points == 0

    # Sous une politique stricte, l'échec reste marqué INÉVALUABLE — pas un rejet de fond.
    strict = _match(_cu(amount="2400000.00 EUR"), _icp(unknown_value_policy="exclude"))
    strict_currency = _filter(strict, "value_currency")
    assert not strict_currency.passed
    assert not strict_currency.evaluable
    assert strict.decision == "insufficient_data"


def test_adversarial_f_excluded_contract_type() -> None:
    """§45 F — contract type exclu → décision `exclude`."""
    result = _match(_cu(), _icp(excluded_contract_types=("construction",)))

    assert result.decision == "exclude"
    contract_type = _filter(result, "contract_type")
    assert not contract_type.passed
    assert contract_type.evaluable
    assert result.positive_reasons == ()
    assert result.evidence_refs == ()


def test_adversarial_g_unknown_sector_is_never_positive() -> None:
    """§45 G — secteur inconnu → jamais positif par défaut."""
    unknown = _match(_cu(sector="unknown"), _icp(included_sectors=("housing",)))

    # Un secteur inconnu ne bloque pas, mais il n'ouvre aucun crédit non plus.
    assert _filter(unknown, "sector").passed
    assert all(entry.name != "sector" for entry in unknown.score_components)
    assert all("secteur" not in reason for reason in unknown.positive_reasons)

    # Et il ne vaut pas davantage qu'un secteur explicitement visé par l'ICP.
    targeted = _match(_cu(sector="housing"), _icp(included_sectors=("housing",)))
    assert unknown.normalized_score <= targeted.normalized_score


def test_adversarial_h_publication_older_than_the_window() -> None:
    """§45 H — publication trop ancienne → décision `exclude`."""
    result = _match(_cu(published=dt.date(2025, 1, 1)), _icp())

    assert result.decision == "exclude"
    age = _filter(result, "signal_age")
    assert not age.passed
    assert age.evaluable, "une date publiée rend la fraîcheur évaluable"
    assert result.normalized_score == 0


def test_adversarial_i_unknown_timing_earns_no_positive_point() -> None:
    """§45 I — timing inconnu → aucun point de timing positif."""
    cu = _cu(start=None)
    needs = NeedGraphEngine().derive(cu)
    assert needs.needs and all(need.timing == "unknown" for need in needs.needs)

    preferences = ("immediate", "near_term")
    unknown = MatchingEngine().match(cu, needs, _icp(preferred_timings=preferences), as_of=AS_OF)
    dated = _match(_cu(start=dt.date(2026, 8, 10)), _icp(preferred_timings=preferences))

    unknown_timing = _component(unknown, "freshness_timing")
    dated_timing = _component(dated, "freshness_timing")
    # Même date de publication : seule la part « timing » sépare les deux composants.
    assert unknown_timing.points < dated_timing.points
    assert unknown_timing.points < unknown_timing.maximum_points
    assert "aucun timing préféré établi" in unknown_timing.detail
    assert any("timing reste indéterminé" in limit for limit in unknown.limitations)


def test_adversarial_j_winner_location_versus_place_of_performance() -> None:
    """§45 J — gagnant compatible, lieu d'exécution incompatible : le résultat suit
    `geography_basis`."""
    # Le gagnant est suisse, le chantier est français : seule la base choisie tranche.
    cu = _cu(country="FR").model_copy(
        update={
            "parties": ContractParties(
                contract_signatories=(
                    OrganizationRef(legal_name="Entreprise Alpha SA", country="CH"),
                )
            )
        }
    )

    place = _match(cu, _icp(geography_basis="place_of_performance"))
    assert place.decision == "exclude"
    assert not _filter(place, "geography").passed

    # `winner_location` est modélisable mais sans données : jamais un faux positif.
    winner = _match(cu, _icp(geography_basis="winner_location"))
    assert winner.decision == "insufficient_data"
    winner_missing = _filter(winner, "geography_missing")
    assert not winner_missing.passed
    assert not winner_missing.evaluable

    either = _match(cu, _icp(geography_basis="either"))
    assert either.decision == "exclude"
    assert not _filter(either, "geography").passed

    # SPEC-008R §2 : `ignore` ne se déclare qu'avec la politique `ignored` —
    # le cas de figure est le même, sa configuration est simplement cohérente.
    ignored = _match(cu, _icp(geography_basis="ignore", geography_policy="ignored", territories=()))
    assert _filter(ignored, "geography").passed
    assert ignored.decision != "exclude"


def test_adversarial_k_subdivision_with_a_different_scheme() -> None:
    """§45 K — subdivision avec schéma différent → aucun faux match."""
    place = Location(country="CH", subdivision_code="FR10", subdivision_scheme="ISO-3166-2")
    cu = _cu().model_copy(
        update={"geography": ContractGeography(place_of_performance=place, buyer_country="CH")}
    )
    icp = _icp(
        territories=(Territory(country="FR", subdivision_code="FR10", subdivision_scheme="NUTS"),)
    )

    result = _match(cu, icp)
    # Codes identiques, schémas différents, pays différents : rien ne se compare.
    assert result.decision == "exclude"
    geography = _filter(result, "geography")
    assert not geography.passed
    assert "FR10" not in geography.detail
    assert all("FR10" not in limitation for limitation in result.limitations)

    # Une subdivision qui ne nomme pas son schéma ne se compare à rien du tout.
    with pytest.raises(ValidationError):
        Territory(country="FR", subdivision_code="FR10")


def test_adversarial_l_primary_need_outranks_secondary_need() -> None:
    """§45 L — primary need vs secondary need : le primaire classe strictement plus haut."""
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

    # Toutes choses égales : même award-lot, même besoin retenu, même géographie.
    assert primary.matched_needs == secondary.matched_needs == ("equipment_or_rental",)
    assert primary.normalized_score > secondary.normalized_score
    assert _component(primary, "need_offer_fit").points > (
        _component(secondary, "need_offer_fit").points
    )


def test_adversarial_m_several_matched_needs_stay_capped() -> None:
    """§45 M — plusieurs matched needs : le score reste plafonné."""
    cu = _cu(characteristics=("several_lots",), start=dt.date(2026, 8, 10))
    many = _match(
        cu,
        _icp(
            primary_need_categories=(
                "equipment_or_rental",
                "workforce_capacity",
                "materials_or_components",
            ),
            secondary_need_categories=(),
        ),
    )
    single = _match(
        cu, _icp(primary_need_categories=("equipment_or_rental",), secondary_need_categories=())
    )

    assert len(many.matched_needs) == 3
    fit = _component(many, "need_offer_fit")
    assert fit.points <= fit.maximum_points
    # Trois besoins ne valent pas plus qu'un seul : le composant est borné.
    assert fit.points == _component(single, "need_offer_fit").points
    assert many.raw_points <= many.maximum_applicable_points
    assert many.normalized_score <= 100


def test_adversarial_n_metadata_mode_caps_confidence_at_medium() -> None:
    """§45 N — mode source `metadata` → confiance maximum `medium`, jamais `high`."""
    cu = _cu(characteristics=("several_lots",), start=dt.date(2026, 8, 10))
    needs = NeedGraphEngine().derive(cu)
    assert needs.source_mode == "metadata_fallback"

    result = _match(cu, _icp(preferred_timings=("immediate",)))
    # Même le meilleur signal possible reste `medium` : le score n'achète pas la confiance.
    assert result.band == "strong"
    assert result.confidence == "medium"
    assert "high" not in typing.get_args(SignalConfidence)
    with pytest.raises(ValidationError):
        _scored(confidence="high")


def test_adversarial_o_experimental_document_output_is_never_used() -> None:
    """§45 O — sortie expérimentale SPEC-006 : jamais utilisée par le moteur de matching."""
    from signals.documents import mvp

    assert mvp.AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False

    # Aucun module de `signals.matching` n'importe le pipeline documentaire.
    imported: set[str] = set()
    for path in sorted(_MATCHING_PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not [module for module in imported if module.startswith("signals.documents")]

    # Aucun champ documentaire n'entre dans l'ICP ni dans le résultat.
    for model in (TargetICP, ScoredSignalMatch):
        for field in model.model_fields:
            assert not any(token in field.lower() for token in DOCUMENT_TOKENS), (model, field)
    with pytest.raises(ValidationError):
        _icp(document_requirements=("attestation de capacité",))


def test_adversarial_p_score_breakdown_is_exact() -> None:
    """§45 P — somme des points == raw_points, somme des maximums == maximum applicable,
    normalisé == round(100 * raw / max)."""
    scored = (
        _match(_cu(), _icp()),
        _match(_cu(start=dt.date(2026, 8, 10)), _icp(preferred_timings=("immediate",))),
        _match(_cu(amount="2400000.00 EUR"), _icp()),
    )

    for result in scored:
        assert result.score_components, "un résultat noté sans composant n'est pas traçable"
        assert sum(c.points for c in result.score_components) == result.raw_points
        assert sum(c.maximum_points for c in result.score_components) == (
            result.maximum_applicable_points
        )
        assert result.maximum_applicable_points > 0
        assert result.normalized_score == round(
            100 * result.raw_points / result.maximum_applicable_points
        )


def test_adversarial_q_a_score_without_explanation_is_invalid() -> None:
    """§45 Q — score sans explication → modèle invalide (pydantic ValidationError)."""
    assert _scored().decision == "show", "le gabarit complet doit rester valide"

    with pytest.raises(ValidationError):
        _scored(positive_reasons=())
    with pytest.raises(ValidationError):
        _scored(evidence_refs=())
    with pytest.raises(ValidationError):
        _scored(matched_needs=())
    with pytest.raises(ValidationError):
        _scored(score_components=(), raw_points=0, maximum_applicable_points=0, normalized_score=0)


def test_adversarial_r_no_acquisition_or_campaign_field() -> None:
    """§45 R — champs acquisition/campagne absents du TargetICP et de ScoredSignalMatch."""
    for model in (TargetICP, ScoredSignalMatch):
        for field in model.model_fields:
            assert not any(token in field.lower() for token in ACQUISITION_TOKENS), (model, field)

    # `extra="forbid"` : la frontière est structurelle, pas conventionnelle.
    with pytest.raises(ValidationError):
        _icp(campaign_id="cmp-001")
    with pytest.raises(ValidationError):
        _scored(reply_rate=0.12)


def test_adversarial_s_two_lots_of_the_same_notice_stay_distinct() -> None:
    """§45 S — deux lots de la même notice → résultats distincts."""
    lot_one = _cu(amount="2400000.00 CHF").model_copy(update={"source_award_id": "lot-1"})
    lot_two = _cu(amount="120000.00 CHF").model_copy(update={"source_award_id": "lot-2"})
    assert lot_one.award_ref == lot_two.award_ref, "les deux lots viennent bien du même avis"

    first = _match(lot_one, _icp())
    second = _match(lot_two, _icp())

    assert first.decision == "show"
    assert second.decision == "exclude"
    assert first.model_dump() != second.model_dump()


def test_adversarial_t_repetition_is_deterministic() -> None:
    """§45 T — répétition déterministe : deux runs identiques donnent le même `model_dump()`."""
    first = _match(_cu(), _icp())
    second = _match(_cu(), _icp())

    assert first.model_dump() == second.model_dump()
    # Jusque dans l'ORDRE des filtres, des composants et des preuves.
    assert [f.name for f in first.hard_filter_results] == [
        f.name for f in second.hard_filter_results
    ]
    assert [c.name for c in first.score_components] == [c.name for c in second.score_components]
    assert first.evidence_refs == second.evidence_refs
