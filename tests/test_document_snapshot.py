"""SPEC-006R4 §11 — le contexte figé d'un candidat, et sa preuve réelle.

DEV-3 a été mesuré avec `source_text` égal à l'extrait : la validation de preuve
y était vraie par construction et ne prouvait rien. Ces tests fixent la forme
d'un candidat qui porte son voisinage réel, et exigent que l'extrait se retrouve
dans les **blocs sources**, pas dans un champ qui le recopie.
"""

from __future__ import annotations

import pathlib

import pytest

from signals.documents.extract import extract_text
from signals.documents.snapshot import (
    CandidateSnapshot,
    excerpt_locates_in_blocks,
    snapshot_candidate,
)
from signals.documents.spans import logical_spans

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def docx_blocks():
    result = extract_text(load("dokumentacija.docx"), name="dokumentacija.docx")
    return result.blocks


def build(blocks, index: int, excerpt: str | None = None) -> CandidateSnapshot:
    spans = logical_spans(blocks)
    return snapshot_candidate(
        candidate_id=1,
        award_reference="999999-2026",
        document_name="dokumentacija.docx",
        document_hash="a" * 64,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        blocks=blocks,
        index=index,
        excerpt=excerpt if excerpt is not None else blocks[index].text.strip(),
        spans=spans,
    )


class TestTheSnapshotCarriesItsContext:
    def test_it_records_the_current_block_verbatim(self, docx_blocks) -> None:
        snap = build(docx_blocks, 120)
        assert snap.current_block == docx_blocks[120].text

    def test_it_records_the_previous_and_next_blocks(self, docx_blocks) -> None:
        snap = build(docx_blocks, 120)
        assert snap.previous_block == docx_blocks[119].text
        assert snap.next_block == docx_blocks[121].text

    def test_the_first_block_has_no_predecessor(self, docx_blocks) -> None:
        assert build(docx_blocks, 0).previous_block is None

    def test_the_last_block_has_no_successor(self, docx_blocks) -> None:
        assert build(docx_blocks, len(docx_blocks) - 1).next_block is None

    def test_it_records_the_source_locator(self, docx_blocks) -> None:
        snap = build(docx_blocks, 120)
        assert snap.source_locator == docx_blocks[120].locator

    def test_it_records_the_document_hash_and_name(self, docx_blocks) -> None:
        snap = build(docx_blocks, 120)
        assert snap.document_hash == "a" * 64
        assert snap.document_name == "dokumentacija.docx"

    def test_it_records_the_ordered_source_block_locators(self, docx_blocks) -> None:
        """Une exigence à cheval sur deux blocs doit pouvoir les nommer tous."""
        snap = build(docx_blocks, 120)
        assert snap.source_block_locators
        assert docx_blocks[120].locator in snap.source_block_locators

    def test_it_records_the_logical_span_text(self, docx_blocks) -> None:
        snap = build(docx_blocks, 120)
        assert docx_blocks[120].text.strip()[:40] in snap.logical_span.replace("\n", " ")


class TestTheEvidenceIsRealOrAbsent:
    def test_an_excerpt_present_in_a_block_is_located(self, docx_blocks) -> None:
        excerpt = docx_blocks[120].text.strip()[:50]
        assert excerpt_locates_in_blocks(excerpt, docx_blocks) is True

    def test_an_invented_excerpt_is_not_located(self, docx_blocks) -> None:
        assert (
            excerpt_locates_in_blocks("Le titulaire doit repeindre la Lune.", docx_blocks) is False
        )

    def test_the_snapshot_refuses_an_excerpt_absent_from_the_document(self, docx_blocks) -> None:
        """C'est la garantie que DEV-3 ne pouvait pas offrir."""
        with pytest.raises(ValueError, match="introuvable"):
            build(docx_blocks, 120, excerpt="Le titulaire doit repeindre la Lune.")

    def test_the_snapshot_does_not_store_a_source_text_equal_to_the_excerpt(
        self, docx_blocks
    ) -> None:
        snap = build(docx_blocks, 120, excerpt=docx_blocks[120].text.strip()[:40])
        assert snap.current_block != snap.excerpt
        assert len(snap.current_block) > len(snap.excerpt)

    def test_an_excerpt_spanning_two_blocks_names_both(self, docx_blocks) -> None:
        spans = [s for s in logical_spans(docx_blocks) if len(s.blocks) > 1]
        if not spans:
            pytest.skip("aucun span multi-blocs dans ce document")
        span = spans[0]
        pieces = span.pieces_for(span.text[:60])
        # Chaque morceau cite SON bloc : aucune citation recomposée.
        assert pieces
        for piece in pieces:
            assert piece.text in piece.block.text


class TestLanguageUsesTheProductionDetector:
    """Pas de table de mots par langue propre au snapshot.

    Une seconde heuristique linguistique, écrite à côté de celle du tri, aurait
    dérivé — et surtout elle figeait des mots d'une langue choisie d'avance dans
    un module qui doit rester agnostique.
    """

    def test_it_delegates_to_the_triage_detector(self, docx_blocks, monkeypatch) -> None:
        import signals.documents.snapshot as module

        seen: list[str] = []

        def fake(text: str) -> str:
            seen.append(text)
            return "xx"

        monkeypatch.setattr(module, "detect_language", fake)
        snap = build(docx_blocks, 120)
        assert seen
        assert snap.language == "xx"

    def test_the_module_holds_no_per_language_word_list(self) -> None:
        import signals.documents.snapshot as module

        source = pathlib.Path(module.__file__).read_text().casefold()
        for word in ("titulaire", "acheteur", "izvajalec", "adjudicat", "auftragnehmer"):
            assert word not in source, word


class TestTheSnapshotIsSerialisable:
    def test_it_round_trips_through_json(self, docx_blocks) -> None:
        import json

        snap = build(docx_blocks, 120)
        restored = CandidateSnapshot(**json.loads(json.dumps(snap.as_dict())))
        assert restored == snap

    def test_every_required_field_of_the_spec_is_present(self, docx_blocks) -> None:
        keys = set(build(docx_blocks, 120).as_dict())
        assert {
            "candidate_id",
            "award_reference",
            "document_hash",
            "document_name",
            "media_type",
            "source_locator",
            "heading",
            "previous_block",
            "current_block",
            "next_block",
            "logical_span",
            "source_block_locators",
            "excerpt",
            "language",
        } <= keys
