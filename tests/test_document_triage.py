"""Tri documentaire : nature du fichier, priorité de lecture, langue.

Un dossier réel mélange le cahier des charges, le bordereau de quantités, un
formulaire ESPD et l'annonce publiée. Les lire dans le désordre coûte du temps
sur les gros dossiers et dilue les exigences dans du formulaire vide : ce module
décide quoi lire d'abord, à partir du nom et du format observés — jamais du
contenu supposé.
"""

from __future__ import annotations

import pytest

from signals.documents import TenderDocument
from signals.documents.triage import detect_language, document_kind, relevance_rank


def _document(name: str, media_type: str | None = None) -> TenderDocument:
    return TenderDocument(
        source_system="ted",
        name=name,
        media_type=media_type,
        access_status="available",
        content_hash="a" * 64,
    )


class TestDocumentKind:
    """Les libellés viennent des deux dossiers réels, pas d'une théorie."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("1_Caderno_encargos_AE.pdf", "technical_specification"),
            ("Cahier des charges techniques.pdf", "technical_specification"),
            ("Dokumentacija v zvezi z oddajo.docx", "technical_specification"),
            ("2_Programa_Procedimento_AE.pdf", "procedure_rules"),
            ("Reglement de la consultation.pdf", "procedure_rules"),
            ("Popis del - SKLOP 1.xlsx", "bill_of_quantities"),
            ("Bordereau des prix unitaires.xlsx", "bill_of_quantities"),
            ("espd-request.xml", "form"),
            ("Minuta do anuncio.pdf", "notice_copy"),
            ("384-II-Anuncio-2026-08-14 JORAA.pdf", "notice_copy"),
            ("Conditions generales du contrat.pdf", "contract_conditions"),
            ("3_espd-request.zip", "archive"),
            ("Anexo 4.pdf", "annex"),
            ("419970113.pdf", "unknown"),
        ],
    )
    def test_kind_from_real_document_names(self, name: str, expected: str) -> None:
        assert document_kind(name) == expected

    def test_archive_recognised_by_media_type_even_without_suffix(self) -> None:
        assert document_kind("dossier", media_type="application/zip") == "archive"

    def test_unknown_name_is_unknown_not_guessed(self) -> None:
        assert document_kind("MTEyOTYzNw") == "unknown"

    def test_kind_is_case_and_accent_insensitive(self) -> None:
        assert document_kind("CADERNO DE ENCARGOS.PDF") == "technical_specification"
        assert document_kind("Minuta do anúncio.pdf") == "notice_copy"


class TestRelevanceRank:
    """Le cahier des charges passe avant le formulaire ESPD, toujours."""

    def test_specification_ranks_before_procedure_rules(self) -> None:
        assert relevance_rank(_document("Caderno_encargos.pdf")) < relevance_rank(
            _document("Programa_Procedimento.pdf")
        )

    def test_procedure_rules_rank_before_forms(self) -> None:
        assert relevance_rank(_document("Programa_Procedimento.pdf")) < relevance_rank(
            _document("espd-request.xml")
        )

    def test_notice_copy_ranks_last_it_repeats_what_we_already_have(self) -> None:
        ranks = [relevance_rank(_document(n)) for n in ("Caderno.pdf", "Popis del.xlsx")]
        assert max(ranks) < relevance_rank(_document("Minuta do anuncio.pdf"))

    def test_unreadable_document_ranks_after_every_readable_one(self) -> None:
        unreadable = TenderDocument(
            source_system="simap", name="dossier de marché", access_status="auth_required"
        )
        assert relevance_rank(unreadable) > relevance_rank(_document("Minuta do anuncio.pdf"))

    def test_sorting_a_real_dossier_puts_the_specification_first(self) -> None:
        dossier = [
            _document("Minuta do anuncio.pdf"),
            _document("3_espd-request.zip"),
            _document("2_Programa_Procedimento_AE.pdf"),
            _document("1_Caderno_encargos_AE.pdf"),
        ]
        ordered = sorted(dossier, key=relevance_rank)
        assert ordered[0].name == "1_Caderno_encargos_AE.pdf"
        assert ordered[-1].name == "Minuta do anuncio.pdf"


class TestLanguageDetection:
    """Détection par mots fonctionnels : assez pour étiqueter, jamais pour traduire."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("O adjudicatário deve apresentar os documentos que são exigidos no caderno", "pt"),
            ("Ponudnik mora predložiti dokumentacijo, ki je zahtevana v razpisu", "sl"),
            ("Le titulaire doit mettre à disposition les moyens qui sont exigés", "fr"),
            ("The contractor shall provide the equipment that is required by the contract", "en"),
            ("Der Auftragnehmer muss die geforderten Leistungen mit dem Personal erbringen", "de"),
            ("L'aggiudicatario deve fornire il personale che è richiesto dal contratto", "it"),
        ],
    )
    def test_detects_the_six_languages_met_in_the_corpus(self, text: str, expected: str) -> None:
        assert detect_language(text) == expected

    def test_returns_none_rather_than_guessing_on_a_number_table(self) -> None:
        assert detect_language("120 240 360 480 12,5 %") is None

    def test_returns_none_on_text_too_short_to_decide(self) -> None:
        assert detect_language("Popis del") is None

    def test_a_narrow_lead_is_not_a_language(self) -> None:
        """SPEC-006R : mieux vaut « inconnue » qu'une langue fausse.

        Sur le corpus réel, deux pièces slovènes étaient étiquetées `pt` et `en`
        parce qu'un ou deux mots courts penchaient de ce côté. Cette étiquette
        n'influence aucune exigence, mais une métadonnée fausse reste fausse.
        """
        # « do » et « da » comptent en portugais, « in », « to » et « the » en
        # anglais : trois voix contre deux ne suffisent pas à trancher.
        assert detect_language("Popis do opreme da izvedbo in to the sklop") is None

    def test_a_clear_lead_is_still_detected(self) -> None:
        assert (
            detect_language(
                "Ponudnik mora predložiti dokumentacijo, ki je zahtevana v razpisu za oddajo"
            )
            == "sl"
        )
