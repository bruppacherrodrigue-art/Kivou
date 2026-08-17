"""Le tri par nom face aux langues à cas.

`document_kind` reconnaissait `vzorec pogodbe` mais pas `osnutek pogodbe` ni
`vzorec krovne pogodbe` : le motif portait le nominatif `pogodba`, alors que le
slovène décline. Sur un dossier réel de HELD-OUT-3, cela a rangé trois projets
de contrat — les pièces les plus denses en obligations d'exécution — parmi les
`unknown`, donc en fin de file de lecture.

Les noms testés ici sont ceux de documents réellement rencontrés.
"""

from __future__ import annotations

import pytest

from signals.documents.model import TenderDocument
from signals.documents.triage import document_kind, relevance_rank


class TestSlovenianContractInflections:
    @pytest.mark.parametrize(
        "name",
        [
            "9_vzorec_pogodbe_sklop 2.docx",
            "4_-_ODMSPU-11_2026_Osnutek_Pogodbe.docx",
            "8_vzorec_krovne_pogodbe_sklop 1.docx",
            "8a_vzorec_posamicne_pogodbe_sklop 1.docx",
            "P-3 Vzorec pogodbe_pop.docx",
            "OBR-Vzorec pogodbe.docx",
        ],
    )
    def test_a_draft_contract_is_recognised_whatever_its_case(self, name: str) -> None:
        assert document_kind(name) == "contract_conditions"

    def test_the_nominative_still_works(self) -> None:
        assert document_kind("pogodba.docx") == "contract_conditions"


class TestSlovenianSpecificationInflections:
    @pytest.mark.parametrize(
        "name",
        [
            "2_-_ODMSPU-11_2026_Tehnicne_specifikacije.docx",
            "Tehnične specifikacije.pdf",
        ],
    )
    def test_a_technical_specification_is_recognised(self, name: str) -> None:
        assert document_kind(name) == "technical_specification"


class TestPricedSchedulesAreBillsOfQuantities:
    @pytest.mark.parametrize(
        "name",
        [
            "Specifikacije_predračuna_sklop 1.xlsx",
            "Ponudbeni_predračun.docx",
            "Popis del.xlsx",
        ],
    )
    def test_a_priced_schedule_is_a_bill_of_quantities(self, name: str) -> None:
        assert document_kind(name) == "bill_of_quantities"


class TestNothingIsGuessed:
    @pytest.mark.parametrize(
        "name",
        [
            "1_CE_CPI_100_2026.pdf",
            "2_PP_CPI_100_2026.pdf",
            "11_Ovojnica.docx",
        ],
    )
    def test_an_opaque_abbreviation_stays_unknown(self, name: str) -> None:
        """« CE » abrège Caderno de Encargos — et cent autres choses.

        Le module refuse de deviner : mieux vaut `unknown` et une lecture tardive
        qu'une nature inventée qui ferait passer un formulaire pour un cahier
        des charges.
        """
        assert document_kind(name) == "unknown"

    def test_a_form_is_still_a_form(self) -> None:
        assert document_kind("3_-_ODMSPU-11_2026_ESPD.xml") == "form"

    def test_a_declaration_is_not_promoted_to_a_contract(self) -> None:
        assert document_kind("7_Izjava_podizvajalca.docx") != "contract_conditions"


class TestTheFixChangesReadingOrder:
    def test_a_draft_contract_is_now_read_before_an_unknown_document(self) -> None:
        """C'est l'effet concret : ces pièces remontent dans la file de lecture."""

        def rank(name: str) -> int:
            return relevance_rank(
                TenderDocument(
                    source_system="ted",
                    name=name,
                    access_status="available",
                    content_hash="a" * 64,
                )
            )

        assert rank("4_-_ODMSPU-11_2026_Osnutek_Pogodbe.docx") < rank("11_Ovojnica.docx")
