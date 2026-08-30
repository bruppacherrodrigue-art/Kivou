from __future__ import annotations

import datetime as dt
from decimal import Decimal

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    SourceFacts,
)
from signals.card_intelligence.fallback import factual_fallback
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


def test_qa_contract_can_decide_but_cannot_rewrite_content():
    schema = str(QaResponse.model_json_schema()).casefold()
    for forbidden in ("headline", "summary", "content", "rewrite", "recommended_action"):
        assert forbidden not in schema
    response = QaResponse(decision=QaDecision(status="PASS", reasons=("grounded",)))
    assert response.decision is not None and response.decision.status == "PASS"
