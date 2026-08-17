"""La politique d'acquisition d'un corpus — ce qu'elle garde, et pourquoi.

Deux mesures ont dicté ces règles :

- le stratum 1, sans filtre de nature, a rendu 7 exigences réelles sur 150 —
  un dénominateur de rappel inutilisable ;
- le stratum 2, avec un filtre strict qui rejetait `unknown`, a rendu **un**
  document exploitable sur 500 avis. Un nom de fichier opaque n'est pas une
  preuve d'inutilité : `1_CE_CPI_100_2026.pdf` est un cahier des charges.

D'où une politique qui exclut ce qui est administratif avec certitude, et garde
le reste — l'annotation humaine tranchera mieux qu'un nom de fichier.
"""

from __future__ import annotations

import pytest

from signals.documents.heldout3_build import (
    CORPUS_KINDS,
    keeps_document,
    keeps_language,
)


class TestOpaqueNamesAreKept:
    def test_unknown_is_part_of_the_corpus(self) -> None:
        """Le coût de l'exclure a été mesuré : 1 document sur 500 avis."""
        assert "unknown" in CORPUS_KINDS

    def test_an_opaque_portuguese_specification_is_kept(self) -> None:
        assert keeps_document("1_CE_CPI_100_2026.pdf") is True

    def test_procedure_rules_and_annexes_are_kept(self) -> None:
        """Un règlement de consultation porte parfois des clauses d'exécution,
        et une annexe technique est parfois le cahier des charges lui-même."""
        assert keeps_document("Reglement de consultation.pdf") is True
        assert keeps_document("Annexe 3 - specifications.pdf") is True

    def test_the_execution_bearing_kinds_are_kept(self) -> None:
        for name in (
            "Cahier des charges techniques.pdf",
            "4_-_ODMSPU-11_2026_Osnutek_Pogodbe.docx",
            "Popis del.xlsx",
        ):
            assert keeps_document(name) is True, name


class TestAdministrativePiecesAreExcluded:
    @pytest.mark.parametrize(
        "name",
        [
            "3_-_ODMSPU-11_2026_ESPD.xml",
            "Narocnik_ESPD.xml",
            "formulaire_de_candidature.pdf",
        ],
    )
    def test_a_candidature_form_is_excluded(self, name: str) -> None:
        assert keeps_document(name) is False

    def test_a_notice_copy_is_excluded(self) -> None:
        assert keeps_document("anuncio_joraa.pdf") is False

    def test_an_archive_is_not_a_document(self) -> None:
        assert keeps_document("dossier.zip") is False


class TestNoCountrySpecificRuleWasAddedForTheMvp:
    """Le MVP est fr + en. Les autres pays sont des fixtures de régression.

    Un préfixe `OBR-` (slovène, *obrazec*) avait été ajouté pour écarter des
    formulaires de candidature ; il est retiré. Conséquence assumée : ces
    formulaires restent `unknown`, donc conservés, et c'est l'annotation qui les
    écartera. Mieux vaut un corpus un peu plus large qu'une exception nationale
    dans un moteur qui doit rester agnostique.
    """

    def test_a_slovenian_form_prefix_stays_unclassified(self) -> None:
        """`OBR-Kadri` est un formulaire de candidature — et reste `unknown`.

        C'est le prix explicite du retrait : l'annotation l'écartera. Aucune
        exception nationale n'entre dans le moteur pour l'éviter.
        """
        from signals.documents.triage import document_kind

        assert document_kind("OBR-Kadri.docx") == "unknown"

    def test_the_mvp_languages_still_have_their_form_detection(self) -> None:
        """Ce qui compte pour le MVP continue d'être écarté."""
        from signals.documents.triage import document_kind

        assert document_kind("formulaire_de_candidature.pdf") == "form"
        assert document_kind("ESPD_request.xml") == "form"


class TestLanguageNeverRejectsWhatItCannotRead:
    def test_an_undetermined_language_is_kept(self) -> None:
        """`None` veut dire « pas déterminée », jamais « pas supportée »."""
        assert keeps_language(None, ("fr", "en")) is True

    def test_an_accepted_language_is_kept(self) -> None:
        assert keeps_language("fr", ("fr", "en")) is True
        assert keeps_language("en", ("fr", "en")) is True

    def test_another_language_is_rejected_only_when_identified(self) -> None:
        assert keeps_language("sl", ("fr", "en")) is False
        assert keeps_language("pt", ("fr", "en")) is False

    def test_no_filter_keeps_everything(self) -> None:
        assert keeps_language("sl", ()) is True
        assert keeps_language(None, ()) is True

    def test_a_bill_of_quantities_full_of_numbers_survives(self) -> None:
        """Un bordereau n'a presque pas de mots : il ne doit pas être perdu."""
        from signals.documents.triage import detect_language

        assert detect_language("12,50 3,00 450 m2 18,75") is None
        assert keeps_language(detect_language("12,50 3,00 450 m2 18,75"), ("fr", "en")) is True


class TestNoLanguageVocabularyLeaksIntoTheSnapshot:
    def test_the_snapshot_module_names_no_language_word(self) -> None:
        import pathlib

        import signals.documents.snapshot as module

        source = pathlib.Path(module.__file__).read_text().casefold()
        for word in ("titulaire", "acheteur", "shall", "contractor", "izvajalec"):
            assert word not in source, word


class TestTheModalityFilterActuallyFilters:
    """`detect_modality` rend `None`, jamais la chaîne `"none"`.

    Comparer à `"none"` ne filtrait rien : titres, en-têtes et lignes de
    pointillés entraient dans les corpus, et la densité en exigences réelles
    s'en trouvait écrasée. Le stratum 1 en a souffert (7 exigences sur 150).
    """

    def test_a_sentence_without_modality_is_rejected(self) -> None:
        from signals.documents.extract import TextBlock
        from signals.documents.heldout3_build import candidate_indices

        blocks = [
            TextBlock(
                locator="p1",
                text="OIN N°3 | LINDOR-BEAUREGARD, secteur nord du projet.",
                method="docx_paragraph",
            ),
            TextBlock(
                locator="p2",
                text="Le titulaire doit remettre un rapport mensuel au format électronique.",
                method="docx_paragraph",
            ),
        ]
        assert candidate_indices(blocks) == [1]

    def test_the_sentinel_is_none_not_a_string(self) -> None:
        from signals.documents.language import detect_modality

        assert detect_modality("OIN N°3 | LINDOR-BEAUREGARD, secteur nord.") is None
        assert detect_modality("Le titulaire doit remettre un rapport.") == "mandatory"
