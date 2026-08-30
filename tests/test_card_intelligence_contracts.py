import datetime as dt
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from signals.accounts.icp_input import MonetaryThreshold, TargetIcpInput
from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    ClaimKind,
    GenerationResponse,
    PresentationClaim,
    PresentationInput,
    PresentationUnknown,
    PresentationVariant,
    PublishedCardPresentation,
    SourceFacts,
    TargetIcpSnapshot,
    TargetIcpThresholdSnapshot,
    TargetRole,
    TargetRoleKind,
)
from signals.qa_signals.contracts import QaDecision, QaStatus


def _claims() -> tuple[PresentationClaim, ...]:
    return (
        PresentationClaim(
            claim_id="FACT_HEADLINE",
            kind=ClaimKind.FACT,
            text="Attribution publiee pour Egli SA",
            evidence_refs=("source:awardee",),
        ),
        PresentationClaim(
            claim_id="FACT_AWARD",
            kind=ClaimKind.FACT,
            text="Egli SA est l'entreprise attributaire publiee par Ville de Sion.",
            evidence_refs=("source:awardee", "source:buyer"),
        ),
        PresentationClaim(
            claim_id="INFERENCE_IMPORTANCE",
            kind=ClaimKind.INFERENCE,
            text="Le montant publie rend ce marche significatif pour ce profil.",
            evidence_refs=("source:amount", "icp:minimum-value"),
            confidence="high",
        ),
        PresentationClaim(
            claim_id="INFERENCE_FIT",
            kind=ClaimKind.INFERENCE,
            text="Le besoin en materiaux correspond a l'offre declaree.",
            evidence_refs=("need:materials", "icp:materials"),
            confidence="high",
        ),
        PresentationClaim(
            claim_id="INFERENCE_TIMING",
            kind=ClaimKind.INFERENCE,
            text="Le calendrier commercial reste a confirmer.",
            evidence_refs=("source:publication-date",),
            confidence="low",
        ),
        PresentationClaim(
            claim_id="RECOMMENDED_ACTION",
            kind=ClaimKind.RECOMMENDATION,
            text="Verifier le besoin materiel avec le responsable des achats.",
            evidence_refs=("need:materials", "icp:materials"),
        ),
    )


def valid_full_payload() -> CardPresentationPayload:
    return CardPresentationPayload(
        variant=PresentationVariant.FULL,
        headline="Attribution publiee pour Egli SA",
        award_summary="Egli SA est l'entreprise attributaire publiee par Ville de Sion.",
        commercial_importance="Le montant publie rend ce marche significatif pour ce profil.",
        fit_reason="Le besoin en materiaux correspond a l'offre declaree.",
        timing="Le calendrier commercial reste a confirmer.",
        recommended_action="Verifier le besoin materiel avec le responsable des achats.",
        target_roles=(
            TargetRole(
                role=TargetRoleKind.PROCUREMENT_MANAGER,
                rationale="Responsabilite fonctionnelle des achats, pas une personne identifiee.",
                evidence_refs=("need:materials",),
            ),
        ),
        fit_need_categories=("materials_or_components",),
        unknowns=(
            PresentationUnknown(
                text="La date de debut du contrat n'est pas publiee.",
                evidence_refs=("source:publication-date",),
            ),
        ),
        claims=_claims(),
    )


def valid_fallback_payload() -> CardPresentationPayload:
    claims = _claims()[:2]
    return CardPresentationPayload(
        variant=PresentationVariant.FACTUAL_FALLBACK,
        headline=claims[0].text,
        award_summary=claims[1].text,
        claims=claims,
    )


def valid_source_facts() -> SourceFacts:
    return SourceFacts(
        winner_name="Egli SA",
        buyer_name="Ville de Sion",
        award_title="FOURNITURE LOT 7 ACCORD-CADRE ADMINISTRATIF",
        amount=Decimal("250000"),
        currency="CHF",
        location="Sion",
        publication_date=dt.date(2026, 8, 15),
        source_system="decp",
        source_notice_id="notice-123",
        evidence_refs=(
            "source:awardee",
            "source:buyer",
            "source:amount",
            "source:publication-date",
            "need:materials",
            "icp:materials",
            "icp:minimum-value",
        ),
    )


def valid_customer_input() -> TargetIcpInput:
    return TargetIcpInput(
        offer_summary="Materiaux de construction",
        offers=("materials_and_components",),
        territories=("CH",),
        minimum_contract_value=MonetaryThreshold(
            currency="CHF",
            minimum_amount=100000,
        ),
    )


def valid_input(customer_input: TargetIcpInput | TargetIcpSnapshot | None = None) -> PresentationInput:
    return PresentationInput(
        account_id="account-1",
        signal_key="signal-1",
        signal_revision=4,
        target_icp_id="icp-1",
        target_icp_revision=7,
        language="fr",
        target_icp_label="Materiaux romands",
        target_icp_customer_input=customer_input or valid_customer_input(),
        icp_matched_needs=("materials_or_components",),
        facts=valid_source_facts(),
    )


def test_artifact_kind_has_no_separate_feed_or_detail_variant():
    assert tuple(ArtifactKind) == (ArtifactKind.CARD_PRESENTATION,)


def test_roles_and_need_categories_are_closed_and_evidence_bound():
    with pytest.raises(ValidationError):
        TargetRole(
            role="SOME_NAMED_PERSON",
            rationale="Une personne inventee",
            evidence_refs=("source:awardee",),
        )
    with pytest.raises(ValidationError, match="evidence_refs"):
        TargetRole(
            role=TargetRoleKind.PROCUREMENT_MANAGER,
            rationale="Categorie fonctionnelle",
            evidence_refs=(),
        )
    with pytest.raises(ValidationError, match="evidence_refs"):
        PresentationUnknown(text="Information absente", evidence_refs=())

    dumped = valid_full_payload().model_dump()
    dumped["fit_need_categories"] = ("invented_need",)
    with pytest.raises(ValidationError):
        CardPresentationPayload.model_validate(dumped)


def test_every_claim_requires_evidence_including_recommendations():
    for kind in ClaimKind:
        kwargs = {"confidence": "medium"} if kind is ClaimKind.INFERENCE else {}
        with pytest.raises(ValidationError, match="evidence_refs"):
            PresentationClaim(
                claim_id="CLAIM",
                kind=kind,
                text="Texte",
                evidence_refs=(),
                **kwargs,
            )


def test_only_inferences_carry_an_explicit_confidence():
    with pytest.raises(ValidationError, match="INFERENCE.*confidence"):
        PresentationClaim(
            claim_id="INFERENCE",
            kind=ClaimKind.INFERENCE,
            text="Inference",
            evidence_refs=("source:awardee",),
        )
    for kind in (ClaimKind.FACT, ClaimKind.RECOMMENDATION):
        with pytest.raises(ValidationError, match="only INFERENCE"):
            PresentationClaim(
                claim_id="CLAIM",
                kind=kind,
                text="Texte",
                evidence_refs=("source:awardee",),
                confidence="high",
            )


@pytest.mark.parametrize(
    "field",
    ("commercial_importance", "fit_reason", "timing", "recommended_action"),
)
def test_full_requires_every_commercial_field(field):
    dumped = valid_full_payload().model_dump()
    dumped[field] = None
    with pytest.raises(ValidationError, match="FULL requires every commercial field"):
        CardPresentationPayload.model_validate(dumped)


@pytest.mark.parametrize("field", ("target_roles", "fit_need_categories"))
def test_full_requires_roles_and_matched_needs(field):
    dumped = valid_full_payload().model_dump()
    dumped[field] = ()
    with pytest.raises(ValidationError, match="FULL requires roles and matched needs"):
        CardPresentationPayload.model_validate(dumped)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("commercial_importance", "Urgent"),
        ("fit_reason", "Correspondance"),
        ("timing", "Appeler demain"),
        ("recommended_action", "Contacter une personne"),
        (
            "target_roles",
            (
                TargetRole(
                    role=TargetRoleKind.PROCUREMENT_MANAGER,
                    rationale="Categorie fonctionnelle",
                    evidence_refs=("source:awardee",),
                ),
            ),
        ),
        ("fit_need_categories", ("materials_or_components",)),
    ),
)
def test_fallback_rejects_every_commercial_conclusion(field, value):
    dumped = valid_fallback_payload().model_dump()
    dumped[field] = value
    with pytest.raises(ValidationError, match="FACTUAL_FALLBACK"):
        CardPresentationPayload.model_validate(dumped)


def test_fallback_rejects_non_fact_claims():
    dumped = valid_fallback_payload().model_dump()
    dumped["claims"] = (_claims()[2], *_claims()[:2])
    with pytest.raises(ValidationError, match="FACT claims only"):
        CardPresentationPayload.model_validate(dumped)


def test_claim_identifiers_are_unique_per_payload():
    dumped = valid_full_payload().model_dump()
    dumped["claims"] = (*dumped["claims"], dumped["claims"][0])
    with pytest.raises(ValidationError, match="claim_id values must be unique"):
        CardPresentationPayload.model_validate(dumped)


def test_every_public_prose_field_is_bound_to_an_evidenced_claim():
    dumped = valid_full_payload().model_dump()
    dumped["timing"] = "Appeler demain"
    with pytest.raises(ValidationError, match="timing.*exact evidenced claim"):
        CardPresentationPayload.model_validate(dumped)


@pytest.mark.parametrize(
    ("field", "wrong_kind", "confidence"),
    (
        ("headline", ClaimKind.RECOMMENDATION, None),
        ("award_summary", ClaimKind.RECOMMENDATION, None),
        ("commercial_importance", ClaimKind.FACT, None),
        ("fit_reason", ClaimKind.FACT, None),
        ("timing", ClaimKind.FACT, None),
        ("recommended_action", ClaimKind.FACT, None),
    ),
)
def test_public_prose_fields_require_their_exact_semantic_claim_kind(
    field, wrong_kind, confidence
):
    payload = valid_full_payload()
    claims = tuple(
        claim.model_copy(update={"kind": wrong_kind, "confidence": confidence})
        if claim.text == getattr(payload, field)
        else claim
        for claim in payload.claims
    )
    dumped = payload.model_dump()
    dumped["claims"] = claims
    with pytest.raises(ValidationError, match=rf"{field}.*{field_expected_kind(field).value}"):
        CardPresentationPayload.model_validate(dumped)


def field_expected_kind(field: str) -> ClaimKind:
    if field in {"headline", "award_summary"}:
        return ClaimKind.FACT
    if field == "recommended_action":
        return ClaimKind.RECOMMENDATION
    return ClaimKind.INFERENCE


@pytest.mark.parametrize("surface", ("claim", "role", "unknown"))
def test_every_evidence_reference_resolves_in_the_source_catalog(surface):
    payload = valid_full_payload()
    if surface == "claim":
        claims = (
            payload.claims[0].model_copy(update={"evidence_refs": ("unknown:ref",)}),
            *payload.claims[1:],
        )
        payload = payload.model_copy(update={"claims": claims})
    elif surface == "role":
        roles = (
            payload.target_roles[0].model_copy(update={"evidence_refs": ("unknown:ref",)}),
        )
        payload = payload.model_copy(update={"target_roles": roles})
    else:
        unknowns = (
            payload.unknowns[0].model_copy(update={"evidence_refs": ("unknown:ref",)}),
        )
        payload = payload.model_copy(update={"unknowns": unknowns})

    assert valid_source_facts().unresolved_evidence_refs(payload) == ("unknown:ref",)
    with pytest.raises(ValueError, match="unknown evidence_refs.*unknown:ref"):
        valid_source_facts().ensure_evidence_refs(payload)


def test_source_evidence_catalog_is_unique_and_amount_currency_are_atomic():
    dumped = valid_source_facts().model_dump()
    dumped["evidence_refs"] = ("source:awardee", "source:awardee")
    with pytest.raises(ValidationError, match="evidence_refs.*unique"):
        SourceFacts.model_validate(dumped)

    for missing in ("amount", "currency"):
        dumped = valid_source_facts().model_dump()
        dumped[missing] = None
        with pytest.raises(ValidationError, match="amount and currency"):
            SourceFacts.model_validate(dumped)


def test_presentation_input_uses_the_structured_customer_contract():
    source = valid_input()
    assert isinstance(source.target_icp_customer_input, TargetIcpSnapshot)
    assert source.target_icp_customer_input.offers == ("materials_and_components",)
    dumped = source.model_dump()
    dumped["target_icp_customer_input"] = {"offers": ("not-a-real-offer",)}
    with pytest.raises(ValidationError):
        PresentationInput.model_validate(dumped)


def test_presentation_icp_snapshot_is_deeply_frozen():
    snapshot = valid_input().target_icp_customer_input
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.offers = ("staffing_and_labour",)
    assert snapshot.minimum_contract_value is not None
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.minimum_contract_value.minimum_amount = 1.0


def test_presentation_input_copies_the_mutable_customer_input_before_fingerprinting():
    customer_input = valid_customer_input()
    source = valid_input(customer_input)
    fingerprint = source.fingerprint()
    assert source.target_icp_customer_input is not customer_input
    assert source.target_icp_customer_input.minimum_contract_value is not (
        customer_input.minimum_contract_value
    )

    customer_input.offers = ("staffing_and_labour",)
    assert customer_input.minimum_contract_value is not None
    customer_input.minimum_contract_value.minimum_amount = 1.0

    assert source.target_icp_customer_input.offers == ("materials_and_components",)
    assert source.target_icp_customer_input.minimum_contract_value is not None
    assert source.target_icp_customer_input.minimum_contract_value.minimum_amount == 100000
    assert source.fingerprint() == fingerprint


def test_presentation_icp_snapshot_refuses_coercive_monetary_values_at_the_boundary():
    with pytest.raises(ValidationError):
        TargetIcpThresholdSnapshot(currency="CHF", minimum_amount="100000")

    unsafe_threshold = MonetaryThreshold.model_construct(
        currency="CHF",
        minimum_amount="100000",
        maximum_amount=None,
    )
    unsafe_customer_input = TargetIcpInput.model_construct(
        offers=("materials_and_components",),
        territories=("CH",),
        minimum_contract_value=unsafe_threshold,
    )
    with pytest.raises(ValidationError):
        valid_input(unsafe_customer_input)


def test_input_fingerprint_is_canonical_and_revision_sensitive():
    source = valid_input()
    raw = source.model_dump(mode="json")
    reordered = dict(reversed(tuple(raw.items())))
    decoded = PresentationInput.model_validate_json(json.dumps(reordered))
    assert decoded.fingerprint() == source.fingerprint()
    assert len(source.fingerprint()) == 64

    for update in (
        {"signal_revision": source.signal_revision + 1},
        {"target_icp_revision": source.target_icp_revision + 1},
        {"language": "en"},
    ):
        assert source.model_copy(update=update).fingerprint() != source.fingerprint()


@pytest.mark.parametrize(
    ("payload", "failure_kind"),
    ((None, None), (valid_fallback_payload(), "provider_failure")),
)
def test_generation_response_accepts_exactly_payload_xor_failure(payload, failure_kind):
    with pytest.raises(ValidationError, match="exactly one"):
        GenerationResponse(payload=payload, failure_kind=failure_kind)
    assert GenerationResponse(payload=valid_fallback_payload()).payload is not None
    assert GenerationResponse(failure_kind="provider_failure").failure_kind == "provider_failure"


def valid_publication(
    *,
    status: str = "PASS",
    content: CardPresentationPayload | None = None,
    published_at: dt.datetime | None = None,
) -> PublishedCardPresentation:
    return PublishedCardPresentation(
        artifact_id="a" * 64,
        version=1,
        status=status,
        schema_version="card-presentation-v1",
        published_at=published_at or dt.datetime(2026, 8, 30, 8, 0, tzinfo=dt.UTC),
        content=content or valid_full_payload(),
    )


@pytest.mark.parametrize(
    ("status", "content"),
    (
        ("PASS", valid_fallback_payload()),
        ("FALLBACK", valid_full_payload()),
    ),
)
def test_publication_status_and_variant_are_exact_pairs(status, content):
    with pytest.raises(ValidationError, match="status/variant pair"):
        valid_publication(status=status, content=content)


def test_publication_envelope_rejects_bad_identity_version_schema_and_time():
    base = valid_publication().model_dump()
    invalid = (
        ("artifact_id", "not-a-sha256"),
        ("version", 0),
        ("schema_version", "card-presentation-v2"),
        ("published_at", base["published_at"].replace(tzinfo=None)),
    )
    for field, value in invalid:
        dumped = dict(base)
        dumped[field] = value
        with pytest.raises(ValidationError):
            PublishedCardPresentation.model_validate(dumped)


def test_contracts_are_closed_frozen_and_json_round_trip_strictly():
    payload = valid_full_payload()
    assert CardPresentationPayload.model_validate_json(payload.model_dump_json()) == payload
    dumped = payload.model_dump()
    dumped["rewrite"] = "forbidden"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CardPresentationPayload.model_validate(dumped)
    with pytest.raises(ValidationError, match="frozen"):
        payload.headline = "Rewritten"


def test_qa_decision_has_no_content_rewrite_field():
    decision = QaDecision(status=QaStatus.PASS, reasons=("grounded",))
    assert set(decision.model_dump()) == {"status", "reasons"}
    assert set(QaStatus) == {
        QaStatus.PASS,
        QaStatus.REGENERATE,
        QaStatus.FALLBACK,
        QaStatus.REVIEW,
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QaDecision(
            status=QaStatus.PASS,
            reasons=("grounded",),
            payload={"headline": "rewrite"},
        )
