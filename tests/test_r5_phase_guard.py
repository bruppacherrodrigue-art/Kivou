"""SPEC-006R5.1 §3-§4 — la garde de phase déterministe, structurelle, générique.

Le dernier faux auto-accept du run DEV R5 (candidat 351) était une clause
d'acte d'engagement confirmée par le contradicteur malgré son propre prompt.
La garde répond structurellement : elle ne lit JAMAIS le texte de la phrase —
uniquement le nom du document, le type documentaire et le titre de section.
Un mot du candidat (« doit », « engagement », « exécuter ») ne bloque rien ;
un contexte documentaire de formation du contrat, de candidature ou de
jugement des offres bloque tout. En cas de doute : BLOCK.
"""

from __future__ import annotations

from signals.documents.adversarial import final_decision, phase_guard
from signals.documents.snapshot import CandidateSnapshot


def _snapshot(document_name: str, heading: str | None) -> CandidateSnapshot:
    sentence = "Le titulaire doit assurer la maintenance des équipements pendant le marché."
    return CandidateSnapshot(
        candidate_id=1,
        award_reference="26-000000",
        document_hash="cafe",
        document_name=document_name,
        media_type="application/pdf",
        source_locator="page 4",
        heading=heading,
        previous_block=None,
        current_block=sentence,
        next_block=None,
        logical_span=sentence,
        source_block_locators=("page 4",),
        excerpt=sentence,
    )


class TestEngagementDocuments:
    def test_an_acte_d_engagement_is_a_formation_context(self) -> None:
        guard = phase_guard(_snapshot("AEMarcheCadreAMO.docx", "Numéro de TVA intracommunautaire"))
        assert guard.verdict == "BLOCK"
        assert guard.reason

    def test_the_block_covers_the_whole_engagement_document(self) -> None:
        """§3 : le contexte « acte d'engagement » se bloque en entier — même une
        section substantielle y reste une stipulation de l'offre engagée. En cas
        de doute : BLOCK."""
        assert (
            phase_guard(_snapshot("2.1_ Acte d_engagement.docx", "E- Durée - Délai")).verdict
            == "BLOCK"
        )
        assert phase_guard(_snapshot("AE_03.docx", "8 - Engagement insertion")).verdict == "BLOCK"
        assert (
            phase_guard(_snapshot("AE CONSEIL ASSISTANCE NETTOYAGE.docx", None)).verdict == "BLOCK"
        )


class TestCandidacyAndConsultationDocuments:
    def test_candidacy_forms_are_blocked_by_name(self) -> None:
        assert phase_guard(_snapshot("DC2_declaration_candidat.docx", None)).verdict == "BLOCK"
        assert phase_guard(_snapshot("Lettre de candidature DC1.pdf", None)).verdict == "BLOCK"

    def test_the_consultation_rules_carry_the_award_criteria(self) -> None:
        assert phase_guard(_snapshot("Reglement_de_consultation.pdf", None)).verdict == "BLOCK"
        assert phase_guard(_snapshot("RC.pdf", None)).verdict == "BLOCK"


class TestHeadingContexts:
    def test_award_criteria_headings_block_in_any_document(self) -> None:
        assert (
            phase_guard(_snapshot("document_divers.pdf", "Critères de jugement des offres")).verdict
            == "BLOCK"
        )
        assert (
            phase_guard(_snapshot("document_divers.pdf", "Jugement et attribution")).verdict
            == "BLOCK"
        )
        assert (
            phase_guard(_snapshot("document_divers.pdf", "Présentation des offres")).verdict
            == "BLOCK"
        )

    def test_signature_and_identification_headings_block(self) -> None:
        assert phase_guard(_snapshot("annexe.pdf", "Signature du candidat")).verdict == "BLOCK"
        assert phase_guard(_snapshot("annexe.pdf", "Acceptation de l'offre")).verdict == "BLOCK"
        assert phase_guard(_snapshot("annexe.pdf", "Numéro SIRET")).verdict == "BLOCK"

    def test_candidacy_headings_block(self) -> None:
        guard = phase_guard(
            _snapshot("AE CONSEIL.docx", "• Qualifications le cas échéant, références")
        )
        assert guard.verdict == "BLOCK"


class TestNoLexicalOverblocking:
    """§4 — jamais de blocage porté par les mots de la phrase ou par un simple
    mot dans un titre de clause réelle."""

    def test_a_ccap_execution_clause_always_passes(self) -> None:
        guard = phase_guard(_snapshot("CCAP.pdf", "Obligations du titulaire"))
        assert guard.verdict == "PASS"
        assert guard.reason is None

    def test_a_cctp_with_trap_words_in_the_sentence_passes(self) -> None:
        # La phrase contient « doit », « engagement », « exécuter » — la garde
        # ne la lit pas ; le contexte CCTP décide.
        snapshot = _snapshot("CCTP.docx", "Conditions d'exécution")
        assert phase_guard(snapshot).verdict == "PASS"

    def test_an_insertion_clause_heading_in_a_ccap_is_not_blocked_by_the_word(self) -> None:
        guard = phase_guard(_snapshot("CCAP.pdf", "Engagement relatif à l'action d'insertion"))
        assert guard.verdict == "PASS"

    def test_an_unknown_document_with_a_plain_heading_passes(self) -> None:
        guard = phase_guard(_snapshot("Consignes Sécurité Entreprises Extérieures.pdf", None))
        assert guard.verdict == "PASS"


class TestFinalPolicyIntegration:
    def test_a_perfect_confirm_in_a_blocked_context_is_ignored(self) -> None:
        from signals.documents.adversarial import AdversarialResponse
        from signals.documents.classification import SemanticClassification

        sentence = "Le titulaire doit assurer la maintenance des équipements pendant le marché."
        snapshot = _snapshot("AEMarcheCadreAMO.docx", "Numéro de TVA intracommunautaire")
        primary = SemanticClassification(
            phase="execution",
            obligated_actor="contractor",
            modality="mandatory",
            requirement_type="other",
            context_status="sufficient",
            source_excerpt=sentence,
            confidence="high",
        )
        verifier = AdversarialResponse(
            verdict="confirm", blocker="none", supporting_excerpt=sentence, confidence="high"
        )
        decision = final_decision(primary, verifier, snapshot=snapshot)
        assert decision.outcome == "ignored"
        assert decision.reason.startswith("phase_guard_")

    def test_a_perfect_confirm_in_a_clean_context_still_passes(self) -> None:
        from signals.documents.adversarial import AdversarialResponse
        from signals.documents.classification import SemanticClassification

        sentence = "Le titulaire doit assurer la maintenance des équipements pendant le marché."
        snapshot = _snapshot("CCAP.pdf", "Obligations du titulaire")
        primary = SemanticClassification(
            phase="execution",
            obligated_actor="contractor",
            modality="mandatory",
            requirement_type="other",
            context_status="sufficient",
            source_excerpt=sentence,
            confidence="high",
        )
        verifier = AdversarialResponse(
            verdict="confirm", blocker="none", supporting_excerpt=sentence, confidence="high"
        )
        assert final_decision(primary, verifier, snapshot=snapshot).outcome == "auto_accepted"
