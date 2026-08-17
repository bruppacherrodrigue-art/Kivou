"""SPEC-006R4 — le verdict à deux modèles et ses trois états.

Un modèle qui accepte tout seul n'établit rien. Ces tests fixent ce que la
politique fait d'un accord, d'un désaccord, d'un doute et d'une panne.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.documents.classification import SemanticClassification
from signals.documents.consensus import (
    CONSENSUS_POLICY_VERSION,
    ConsensusDecision,
    VerifierResponse,
    resolve,
    verifier_response_schema,
)

SOURCE = (
    "Izvajalec mora naročniku mesečno predložiti poročilo o opravljenih delih v elektronski obliki."
)
EXCERPT = "Izvajalec mora naročniku mesečno predložiti poročilo o opravljenih delih"


def primary(**overrides: object) -> SemanticClassification:
    """Une classification primaire qui passe la politique, sauf surcharge."""
    fields: dict[str, object] = {
        "phase": "execution",
        "obligated_actor": "contractor",
        "modality": "mandatory",
        "requirement_type": "documentation_obligation",
        "context_status": "sufficient",
        "source_excerpt": EXCERPT,
        "confidence": "high",
    }
    fields.update(overrides)
    return SemanticClassification(**fields)  # type: ignore[arg-type]


def verifier(**overrides: object) -> VerifierResponse:
    fields: dict[str, object] = {
        "verdict": "confirm",
        "reason": "execution_contractor",
        "source_excerpt": EXCERPT,
        "confidence": "high",
    }
    fields.update(overrides)
    return VerifierResponse(**fields)  # type: ignore[arg-type]


class TestVerifierContract:
    """Le vérificateur répond à une seule question, dans une seule forme."""

    def test_it_answers_with_one_of_three_verdicts(self) -> None:
        for verdict in ("confirm", "reject", "uncertain"):
            assert (
                VerifierResponse(
                    verdict=verdict,  # type: ignore[arg-type]
                    reason="execution_contractor",
                    source_excerpt=EXCERPT,
                    confidence="medium",
                ).verdict
                == verdict
            )

    def test_a_verdict_outside_the_three_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            verifier(verdict="probably")

    def test_a_reason_outside_the_taxonomy_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            verifier(reason="looks_fine")

    def test_it_may_not_invent_a_field(self) -> None:
        """Le schéma est fermé : le vérificateur ne réécrit pas l'exigence."""
        with pytest.raises(ValidationError):
            VerifierResponse(
                verdict="confirm",
                reason="execution_contractor",
                source_excerpt=EXCERPT,
                confidence="high",
                rewritten_statement="Le titulaire remet un rapport mensuel.",  # type: ignore[call-arg]
            )

    def test_an_empty_excerpt_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            verifier(source_excerpt="")

    def test_the_schema_sent_to_the_provider_is_strict_and_closed(self) -> None:
        schema = verifier_response_schema()
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {
            "verdict",
            "reason",
            "source_excerpt",
            "confidence",
        }

    def test_the_schema_carries_the_enumerations_inline(self) -> None:
        """`strict: true` interdit les `$ref` : les énumérations sont aplaties."""
        schema = verifier_response_schema()
        assert "$defs" not in schema
        assert schema["properties"]["verdict"]["enum"] == ["confirm", "reject", "uncertain"]


class TestPrimaryRejectionEndsIt:
    def test_a_primary_rejection_is_rejected_without_calling_the_verifier(self) -> None:
        decision = resolve(primary(phase="procurement"), None, source_text=SOURCE)
        assert decision.outcome == "rejected"
        assert decision.reason == "phase_procurement"
        assert decision.verifier_called is False

    def test_the_rejection_motive_is_kept(self) -> None:
        decision = resolve(primary(obligated_actor="buyer"), None, source_text=SOURCE)
        assert decision.reason == "actor_buyer"

    def test_an_excerpt_absent_from_the_source_is_rejected(self) -> None:
        decision = resolve(
            primary(source_excerpt="Le titulaire doit repeindre la façade."),
            None,
            source_text=SOURCE,
        )
        assert decision.outcome == "rejected"
        assert decision.reason == "excerpt_not_found"


class TestAgreementAccepts:
    def test_both_models_agreeing_produces_auto_accepted(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=True)
        assert decision.outcome == "auto_accepted"
        assert decision.reason is None

    def test_auto_accepted_records_that_the_verifier_ran(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=True)
        assert decision.verifier_called is True

    def test_a_confirm_for_another_reason_is_not_an_agreement(self) -> None:
        """Confirmer « c'est une obligation du soumissionnaire » n'est pas confirmer."""
        decision = resolve(
            primary(),
            verifier(reason="bidder_obligation"),
            source_text=SOURCE,
            evidence_complete=True,
        )
        assert decision.outcome == "review_required"
        assert decision.reason == "bidder_obligation"


class TestDisagreementNeverRejects:
    def test_a_verifier_rejection_keeps_the_candidate_for_review(self) -> None:
        decision = resolve(
            primary(), verifier(verdict="reject", reason="procurement"), source_text=SOURCE
        )
        assert decision.outcome == "review_required"

    def test_the_verifier_motive_is_kept(self) -> None:
        decision = resolve(
            primary(), verifier(verdict="reject", reason="procurement"), source_text=SOURCE
        )
        assert decision.reason == "procurement"

    def test_an_uncertain_verifier_keeps_the_candidate_for_review(self) -> None:
        decision = resolve(
            primary(),
            verifier(verdict="uncertain", reason="insufficient_context"),
            source_text=SOURCE,
        )
        assert decision.outcome == "review_required"
        assert decision.reason == "insufficient_context"

    def test_a_verifier_rejection_never_produces_rejected(self) -> None:
        """Un désaccord est une incertitude, pas une réfutation."""
        for reason in ("procurement", "qualification", "third_party", "fragment"):
            decision = resolve(
                primary(),
                verifier(verdict="reject", reason=reason),  # type: ignore[arg-type]
                source_text=SOURCE,
            )
            assert decision.outcome != "rejected", reason


class TestTechnicalFailureIsNeverAVerdict:
    def test_a_missing_primary_classification_goes_to_review(self) -> None:
        decision = resolve(None, None, source_text=SOURCE)
        assert decision.outcome == "review_required"
        assert decision.technical_failure is True
        assert decision.reason == "technical_failure"

    def test_a_missing_verifier_answer_goes_to_review(self) -> None:
        """Le primaire acceptait : l'absence de vérification n'est pas un rejet."""
        decision = resolve(primary(), None, source_text=SOURCE, verifier_called=True)
        assert decision.outcome == "review_required"
        assert decision.technical_failure is True

    def test_a_technical_failure_is_never_rejected(self) -> None:
        assert resolve(None, None, source_text=SOURCE).outcome != "rejected"


class TestConfidenceHasNoSingleAuthority:
    def test_two_high_confidences_and_complete_evidence_give_high(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=True)
        assert decision.confidence == "high"

    def test_a_high_declared_by_the_primary_alone_does_not_carry(self) -> None:
        decision = resolve(
            primary(confidence="high"),
            verifier(confidence="medium"),
            source_text=SOURCE,
            evidence_complete=True,
        )
        assert decision.confidence != "high"

    def test_a_high_declared_by_the_verifier_alone_does_not_carry(self) -> None:
        decision = resolve(
            primary(confidence="low"),
            verifier(confidence="high"),
            source_text=SOURCE,
            evidence_complete=True,
        )
        assert decision.confidence != "high"

    def test_incomplete_evidence_forbids_high(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=False)
        assert decision.confidence != "high"

    def test_incomplete_evidence_forbids_auto_acceptance(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=False)
        assert decision.outcome == "review_required"
        assert decision.reason == "evidence_incomplete"

    def test_a_candidate_kept_for_review_is_never_high(self) -> None:
        decision = resolve(
            primary(), verifier(verdict="uncertain", reason="fragment"), source_text=SOURCE
        )
        assert decision.confidence != "high"


class TestLocatorConflictBlocksAcceptance:
    def test_a_locator_conflict_sends_the_candidate_to_review(self) -> None:
        decision = resolve(
            primary(),
            verifier(),
            source_text=SOURCE,
            evidence_complete=True,
            locator_conflict=True,
        )
        assert decision.outcome == "review_required"
        assert decision.reason == "locator_conflict"


class TestPolicyIsVersioned:
    def test_the_decision_carries_the_policy_version(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=True)
        assert decision.policy_version == CONSENSUS_POLICY_VERSION

    def test_the_version_names_the_two_model_policy(self) -> None:
        assert "v0.4" in CONSENSUS_POLICY_VERSION

    def test_a_decision_is_immutable(self) -> None:
        decision = resolve(primary(), verifier(), source_text=SOURCE, evidence_complete=True)
        with pytest.raises(Exception):  # noqa: B017 — frozen dataclass
            decision.outcome = "rejected"  # type: ignore[misc]

    def test_the_three_states_are_the_only_outcomes(self) -> None:
        assert set(ConsensusDecision.STATES) == {
            "auto_accepted",
            "review_required",
            "rejected",
        }
