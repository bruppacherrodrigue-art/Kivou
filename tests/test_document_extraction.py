"""Du binaire au texte localisé, sur des fichiers réellement publiés.

Aucun fichier de ces tests n'a été fabriqué pour l'occasion : ce sont des pièces
de deux dossiers de marché (Portugal, Slovénie) téléchargées depuis les portails
que TED référence. Leur inventaire exact est dans `MANIFEST.json`.

Ce que ces tests protègent : la **localisation**. « Page 12 » ou « Popis!B12 »
est ce qui rend une preuve vérifiable par un humain ; un texte concaténé sans
repère ne prouverait plus rien.
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import zipfile

import pytest

from signals.documents import (
    ArchiveLimits,
    expand,
    extract_text,
    read_archive,
    sniff_media_type,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"
MANIFEST = json.loads((FIXTURES / "MANIFEST.json").read_text())


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestFixturesAreTheRealFiles:
    @pytest.mark.parametrize("name", sorted(MANIFEST))
    def test_bytes_match_the_hash_recorded_at_download(self, name: str) -> None:
        assert hashlib.sha256(load(name)).hexdigest() == MANIFEST[name]["sha256"]


class TestMediaSniffing:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("caderno_encargos.pdf", "application/pdf"),
            ("dokumentacija.docx", "openxmlformats-officedocument.wordprocessingml.document"),
            ("popis_opreme.xlsx", "openxmlformats-officedocument.spreadsheetml.sheet"),
            ("espd-request.zip", "application/zip"),
        ],
    )
    def test_real_files_are_recognised(self, name: str, expected: str) -> None:
        assert sniff_media_type(name, load(name)).endswith(expected)

    def test_the_bytes_win_over_a_lying_extension(self) -> None:
        assert sniff_media_type("rapport.docx", load("caderno_encargos.pdf")) == "application/pdf"

    def test_an_unknown_binary_is_not_guessed(self) -> None:
        assert sniff_media_type("x", b"\x00\x01\x02\x03") == "application/octet-stream"


class TestPdf:
    def test_each_page_becomes_its_own_located_block(self) -> None:
        result = extract_text(load("caderno_encargos.pdf"), name="caderno_encargos.pdf")

        assert result.supported and not result.encrypted
        assert len(result.blocks) >= 25
        assert result.blocks[0].locator == "page 1"
        assert [block.page for block in result.blocks] == sorted(b.page for b in result.blocks)

    def test_the_extracted_text_is_the_document_text(self) -> None:
        result = extract_text(load("caderno_encargos.pdf"))
        assert "adjudicatário" in " ".join(block.text for block in result.blocks).casefold()

    def test_a_pdf_without_a_text_layer_says_ocr_would_be_needed(self) -> None:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        buffer = io.BytesIO()
        writer.write(buffer)

        result = extract_text(buffer.getvalue(), name="scan.pdf")
        assert result.blocks == ()
        assert any("OCR_REQUIRED_NOT_IMPLEMENTED" in warning for warning in result.warnings)


class TestDocx:
    def test_paragraphs_are_numbered_and_non_empty(self) -> None:
        result = extract_text(load("dokumentacija.docx"), name="dokumentacija.docx")

        assert len(result.blocks) > 500
        assert result.blocks[0].locator.startswith("paragraphe ")
        assert all(block.text.strip() for block in result.blocks)

    def test_slovenian_text_survives_the_extraction(self) -> None:
        result = extract_text(load("dokumentacija.docx"))
        assert "ponudnik" in " ".join(block.text for block in result.blocks).casefold()


class TestXlsx:
    def test_a_cell_is_located_by_sheet_and_reference(self) -> None:
        result = extract_text(load("popis_opreme.xlsx"), name="popis_opreme.xlsx")

        assert result.blocks
        locator = result.blocks[0].locator
        assert "!" in locator, "sans nom de feuille, une cellule ne prouve rien"
        sheet, reference = locator.split("!")
        assert sheet and reference[0].isalpha()

    def test_shared_strings_are_resolved_not_left_as_indexes(self) -> None:
        result = extract_text(load("popis_opreme.xlsx"))
        texts = [block.text for block in result.blocks]
        assert any(len(text) > 10 and not text.isdigit() for text in texts)


class TestHtmlXmlPlain:
    def test_html_is_reduced_to_readable_lines(self) -> None:
        page = b"<html><head><style>p{color:red}</style></head><body><p>Ligne une</p>"
        page += b"<script>alert(1)</script><p>Ligne deux</p></body></html>"
        result = extract_text(page, name="page.html")
        joined = " ".join(block.text for block in result.blocks)

        assert "Ligne une" in joined and "Ligne deux" in joined
        assert "alert" not in joined, "le script n'est pas du texte de document"

    def test_xml_nodes_keep_their_tag_as_locator(self) -> None:
        result = extract_text(load("espd-request.zip"))
        # Le ZIP lui-même n'est pas du XML : c'est l'entrée qui l'est.
        entry = next(
            e for e in read_archive(load("espd-request.zip")).accepted if e.path.endswith(".xml")
        )
        assert entry.content is not None
        result = extract_text(entry.content, name=entry.path)
        assert result.blocks
        assert "[" in result.blocks[0].locator

    def test_plain_text_keeps_line_numbers(self) -> None:
        result = extract_text(b"premiere ligne\n\ndeuxieme ligne\n", name="notes.txt")
        assert [block.locator for block in result.blocks] == ["ligne 1", "ligne 3"]

    def test_an_unsupported_format_is_declared_not_forced(self) -> None:
        result = extract_text(b"\x00\x01\x02\x03", name="plan.dwg")
        assert not result.supported
        assert result.blocks == ()


class TestArchive:
    def test_the_real_espd_archive_is_listed_entry_by_entry(self) -> None:
        reading = read_archive(load("espd-request.zip"))
        names = {entry.path for entry in reading.accepted}
        assert {"espd-request.xml", "espd-request.pdf", "README.txt"} <= names

    def test_expansion_keeps_the_path_of_a_nested_entry(self) -> None:
        # Un ZIP dans un ZIP est un cas réel : le dossier portugais en contient un.
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("dossier/espd-request.zip", load("espd-request.zip"))

        reading = expand(outer.getvalue())
        nested = [entry.path for entry in reading.accepted if "!/" in entry.path]
        assert any(path.endswith("!/README.txt") for path in nested)

    def test_depth_is_bounded_and_the_limit_is_announced(self) -> None:
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as archive:
            archive.writestr("feuille.txt", "contenu")
        middle = io.BytesIO()
        with zipfile.ZipFile(middle, "w") as archive:
            archive.writestr("inner.zip", inner.getvalue())
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("middle.zip", middle.getvalue())

        reading = expand(outer.getvalue(), limits=ArchiveLimits(max_depth=2))
        assert not any(entry.path.endswith("feuille.txt") for entry in reading.accepted)
        assert any("profondeur maximale" in warning for warning in reading.warnings)
