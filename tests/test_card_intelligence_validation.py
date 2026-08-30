from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    SourceFacts,
)
from signals.card_intelligence.fallback import actor_binding, factual_fallback
from signals.card_intelligence.validation import validate_payload
from signals.qa_signals.contracts import QaDecision, QaResponse

EVIDENCE = "source:decp:notice-1"


def source(**updates) -> PresentationInput:
    base = PresentationInput(
        account_id="account-1",
        signal_key="signal-1",
        signal_revision=1,
        target_icp_id="icp-1",
        target_icp_revision=2,
        language="fr",
        target_icp_label="Matériaux",
        target_icp_customer_input={"offers": ["materials_and_components"]},
        icp_matched_needs=("materials_or_components",),
        facts=SourceFacts(
            winner_name="Gagneraud Construction",
            buyer_name="Syndicat des crues de Carimai",
            award_title="CONSTRUCTION D'UN OUVRAGE DE RALENTISSEMENT DYNAMIQUE DES CRUES " * 3,
            amount="7725822",
            currency="EUR",
            location="Carimai · FR",
            award_date=None,
            publication_date=dt.date(2026, 8, 11),
            source_system="decp",
            source_notice_id="notice-1",
            evidence_refs=(EVIDENCE,),
        ),
    )
    return base.model_copy(update=updates)


def full_payload(**updates) -> CardPresentationPayload:
    base = CardPresentationPayload(
        variant=PresentationVariant.FULL,
        headline="Un lot de génie civil attribué à Gagneraud Construction",
        award_summary=(
            "Syndicat des crues de Carimai est indiqué comme acheteur et "
            "Gagneraud Construction comme entreprise attributaire d'un lot de génie civil."
        ),
        commercial_importance="Le marché porte sur un chantier de génie civil documenté.",
        fit_reason="Le besoin en matériaux et composants appartient au profil ciblé.",
        timing="Le calendrier d'exécution et les catégories d'achat restent à qualifier.",
        recommended_action="Vérifier le calendrier puis identifier la fonction achats chantier.",
        target_roles=("SITE_PROCUREMENT_MANAGER",),
        fit_need_categories=("materials_or_components",),
        unknowns=("Calendrier d'exécution", "Catégories d'achat"),
        claims=(
            PresentationClaim(
                claim_id="FACT_AWARDEE",
                kind=ClaimKind.FACT,
                text="Gagneraud Construction est l'entreprise attributaire publiée.",
                evidence_refs=(EVIDENCE,),
            ),
            PresentationClaim(
                claim_id="INFERENCE_FIT",
                kind=ClaimKind.INFERENCE,
                text="Une fourniture de matériaux peut être pertinente.",
                evidence_refs=(EVIDENCE,),
                confidence="low",
            ),
            PresentationClaim(
                claim_id="RECOMMEND_QUALIFY",
                kind=ClaimKind.RECOMMENDATION,
                text="Qualifier le calendrier avant une approche.",
                evidence_refs=(EVIDENCE,),
            ),
        ),
    )
    return base.model_copy(update=updates)


def test_a_valid_full_card_passes_deterministic_gates():
    assert validate_payload(full_payload(), source()).valid is True


def test_materials_profile_rejects_personnel_copy_even_if_qa_would_pass():
    payload = full_payload(
        commercial_importance="Une capacité de personnel supplémentaire pourrait être nécessaire."
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert "icp_category_mismatch:materials_vs_staffing" in outcome.errors


def test_generated_fit_category_must_be_in_icp_matched_needs():
    payload = full_payload(fit_need_categories=("workforce_capacity",))
    outcome = validate_payload(payload, source())
    assert "fit_need_not_matched:workforce_capacity" in outcome.errors


def test_unknown_date_and_actor_collision_are_rejected():
    payload = full_payload(
        award_summary=(
            "Gagneraud Construction est indiqué comme acheteur et entreprise attributaire "
            "et le marché a été attribué le 2026-08-10."
        )
    )
    collision = source(
        facts=source().facts.model_copy(
            update={"buyer_name": "Gagneraud Construction"}
        )
    )
    outcome = validate_payload(payload, collision)
    assert "actor_role_collision" in outcome.errors
    assert "unknown_date:2026-08-10" in outcome.errors
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_actor_role_inversion_is_rejected_even_when_both_names_are_present():
    payload = full_payload(
        award_summary=(
            "Gagneraud Construction est indiqué comme acheteur et Syndicat des crues "
            "de Carimai comme entreprise attributaire."
        )
    )
    outcome = validate_payload(payload, source())
    assert "actor_role_mismatch" in outcome.errors


def test_distinct_long_actor_names_cannot_publish_as_the_same_rendered_label():
    prefix = (
        "Groupement Entreprise Construction Architecture Energie Infrastructure "
        "Regionale "
    )
    item = source(
        facts=source().facts.model_copy(
            update={
                "winner_name": f"{prefix}Titulaire Alpha",
                "buyer_name": f"{prefix}Acheteur Beta",
            }
        )
    )
    payload = factual_fallback(item)
    outcome = validate_payload(payload, item)
    assert outcome.valid is False
    assert "actor_role_collision" in outcome.errors


def test_localized_publication_date_cannot_be_claimed_as_award_date():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué le 11 août 2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_iso_publication_date_cannot_be_labeled_as_award_date():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Date d'attribution : 2026-08-11."
        )
    )
    outcome = validate_payload(payload, source())
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_abbreviated_french_date_cannot_evade_award_date_binding():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué le 10 sept. 2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert "unknown_date:2026-09-10" in outcome.errors
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_dmy_hyphen_date_cannot_evade_award_date_binding():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué le 10-08-2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert "unknown_date:2026-08-10" in outcome.errors
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_two_digit_year_date_cannot_evade_award_date_binding():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué le 10/08/26."
        )
    )
    outcome = validate_payload(payload, source())
    assert "unknown_date:2026-08-10" in outcome.errors
    assert "publication_or_notification_presented_as_award_date" in outcome.errors


def test_month_only_award_assertion_is_rejected_without_an_award_date():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué en août 2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert "unparsed_date_literal:2026" in outcome.errors


def test_month_only_award_assertion_with_unusual_connector_is_rejected():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. Le marché a été attribué au mois d’août 2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert "unparsed_date_literal:2026" in outcome.errors


@pytest.mark.parametrize(
    "statement",
    (
        "L'attribution est intervenue durant 2026.",
        "Le marché a été remporté au mois d'août 2026.",
        "Le marché a été gagné pendant l'exercice 2026.",
        "The contract award occurred during 2026.",
        "The contract was won during 2026.",
        "Le marché a été attribué le 10 août.",
        "Le marché a été attribué le 10/08.",
        "The contract was awarded yesterday.",
    ),
)
def test_award_event_lexemes_cannot_hide_an_unbound_time(statement):
    payload = full_payload(
        award_summary=f"{actor_binding(source())}. {statement}"
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert any(error.startswith("unparsed_date_literal:") for error in outcome.errors)


@pytest.mark.parametrize(
    "statement",
    (
        "Le marché a été attribué ; août 2026.",
        "Le marché a été attribué :\naoût 2026.",
        "Les marchés ont été attribués en août 2026.",
        "Les lots ont été remportés en 2026.",
        "Les consultations ont été gagnées en 2026.",
        "The buyer awards the contract in August 2026.",
        "The supplier wins in 2026.",
        "The contract was awarded; August 2026.",
        "The contract was awarded:\nAugust 2026.",
    ),
)
def test_inflections_and_clause_continuations_cannot_bypass_date_binding(statement):
    payload = full_payload(
        award_summary=f"{actor_binding(source())}. {statement}"
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert any(error.startswith("unparsed_date_literal:") for error in outcome.errors)


def test_english_award_date_is_rejected_without_an_award_date():
    payload = full_payload(
        award_summary=(
            f"{actor_binding(source())}. The contract was awarded on Aug 10, 2026."
        )
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert "unknown_date:2026-08-10" in outcome.errors


def test_isolated_year_near_award_verb_is_rejected():
    payload = full_payload(
        award_summary=(f"{actor_binding(source())}. Le marché est indiqué attribué en 2026.")
    )
    outcome = validate_payload(payload, source())
    assert outcome.valid is False
    assert "unparsed_date_literal:2026" in outcome.errors


def test_supported_localized_dates_pass_only_with_their_exact_role():
    item = source(
        facts=source().facts.model_copy(
            update={"award_date": dt.date(2026, 8, 12)}
        )
    )
    payload = full_payload(
        award_summary=f"{actor_binding(item)}. Marché attribué le 12 août 2026."
    )
    assert validate_payload(payload, item).valid is True


def test_fallback_never_reuses_the_administrative_title_or_invents_a_summary():
    item = source()
    payload = factual_fallback(item)
    assert payload.variant is PresentationVariant.FACTUAL_FALLBACK
    assert item.facts.award_title not in payload.award_summary
    assert "résumé validé indisponible" in payload.award_summary
    assert validate_payload(payload, item).valid is True


def test_fallback_keeps_long_actor_names_bounded_and_preserves_structured_facts():
    item = source(
        facts=source().facts.model_copy(
            update={
                "winner_name": "Groupement " + "Entreprise attributaire très longue " * 10,
                "buyer_name": "Acheteur public " + "territorial " * 20,
                "amount": Decimal("30000000"),
                "award_date": dt.date(2026, 8, 12),
            }
        )
    )
    payload = factual_fallback(item)
    assert len(payload.headline) <= 160
    assert len(payload.award_summary) <= 420
    assert "30000000 EUR" in payload.award_summary
    assert "2026-08-12" in payload.award_summary
    assert validate_payload(payload, item).valid is True


def test_english_fallback_discloses_a_missing_buyer_without_commercial_claims():
    item = source(
        language="en",
        facts=source().facts.model_copy(update={"buyer_name": None}),
    )
    payload = factual_fallback(item)
    assert "Buyer not published" in payload.award_summary
    assert payload.commercial_importance is None
    assert validate_payload(payload, item).valid is True


def test_fallback_bounds_large_evidence_sets_and_keeps_the_source_reference():
    refs = (EVIDENCE, *(f"evidence:{index}" for index in range(1, 32)))
    item = source(facts=source().facts.model_copy(update={"evidence_refs": refs}))
    payload = factual_fallback(item)
    assert len(payload.claims[0].evidence_refs) == 16
    assert payload.claims[0].evidence_refs[0] == EVIDENCE
    assert validate_payload(payload, item).valid is True


def test_factual_amount_and_postcode_that_look_like_a_year_are_not_dates():
    item = source(
        facts=source().facts.model_copy(
            update={"amount": Decimal("2026"), "location": "2026 · CH"}
        )
    )
    payload = factual_fallback(item)
    assert "2026 EUR" in payload.award_summary
    assert "2026 · CH" in payload.award_summary
    assert validate_payload(payload, item).valid is True


@pytest.mark.parametrize(
    "headline",
    ("Projet 2026", "Lot 2026", "Production de 2026 unités", "Code 20260"),
)
def test_non_temporal_numbers_remain_allowed_outside_an_award_statement(headline):
    assert validate_payload(full_payload(headline=headline), source()).valid is True


def test_materials_guard_ignores_a_factual_company_name_containing_personnel():
    item = source(
        facts=source().facts.model_copy(update={"winner_name": "Personnel Services SA"})
    )
    payload = factual_fallback(item)
    assert validate_payload(payload, item).valid is True


def test_certainty_guard_ignores_a_legal_company_name_containing_will_hire():
    item = source(
        language="en",
        facts=source().facts.model_copy(update={"winner_name": "Will Hire Ltd"}),
    )
    payload = factual_fallback(item)
    assert validate_payload(payload, item).valid is True


def test_uppercase_guard_ignores_a_long_legal_company_name():
    item = source(
        facts=source().facts.model_copy(
            update={"winner_name": "LONG COMPANY NAME WITH MANY UPPERCASE LETTERS " * 10}
        )
    )
    payload = factual_fallback(item)
    assert validate_payload(payload, item).valid is True


def test_long_verbatim_excerpt_from_administrative_title_is_rejected():
    item = source()
    excerpt = " ".join((item.facts.award_title or "").split()[:16])
    payload = full_payload(
        award_summary=f"{actor_binding(item)}. {excerpt}."
    )
    outcome = validate_payload(payload, item)
    assert "raw_administrative_title_partially_reused" in outcome.errors


def test_qa_contract_can_decide_but_cannot_rewrite_content():
    schema = str(QaResponse.model_json_schema()).casefold()
    for forbidden in ("headline", "summary", "content", "rewrite", "recommended_action"):
        assert forbidden not in schema
    response = QaResponse(decision=QaDecision(status="PASS", reasons=("grounded",)))
    assert response.decision is not None and response.decision.status == "PASS"
