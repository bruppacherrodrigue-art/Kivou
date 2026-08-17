"""SPEC-006R5 §5-§8 — plus aucune phrase tronquée par une frontière de page.

Le benchmark FR-DCE-1 a chiffré le coût de l'ancien découpage (page → phrases) :
136 étiquettes gold `context_fragment` sur 400 candidats, et 27 des 42 fausses
acceptations DeepSeek portaient sur ces fragments. Le pipeline attendu est :

    TextBlocks bruts
      → reconstruction déterministe LogicalTextSpan
      → découpage en phrases
      → extraction de candidats

Ces tests utilisent les blocs BRUTS du corpus DEV-FR-DCE (candidat 62 : pages
3-5 réelles du CCTP « 2026/31 fourniture de végétaux »), pas des exemples
fabriqués. La phrase témoin y est coupée par la frontière de pages 4/5 :

    page 4  « … Le titulaire du marché devra tenir compte de l'évolution de la »
    page 5  « législation et informer la personne publique en cas de modification. »
"""

from __future__ import annotations

import json
import pathlib

import pytest

from signals.documents.extract import TextBlock
from signals.documents.language import normalize_for_match, sentences
from signals.documents.snapshot import snapshot_candidate
from signals.documents.spans import logical_spans
from signals.research.fr_corpus_run import span_candidates

FIXTURES = pathlib.Path("tests/fixtures/documents")

FULL_SENTENCE = (
    "Le titulaire du marché devra tenir compte de l’évolution de la "
    "législation et informer la personne publique en cas de modification."
)
TRUNCATED = "Le titulaire du marché devra tenir compte de l’évolution de la"


@pytest.fixture(scope="module")
def real_pages() -> tuple[TextBlock, ...]:
    """Pages 3-5 brutes du document du candidat DEV 62, telles que figées."""
    rows = json.loads((FIXTURES / "fr_dce_candidates.json").read_text())["rows"]
    row = next(r for r in rows if r["candidate_id"] == 62)
    return (
        TextBlock(locator="page 3", text=row["previous_block"], method="pdf_page"),
        TextBlock(locator="page 4", text=row["current_block"], method="pdf_page"),
        TextBlock(locator="page 5", text=row["next_block"], method="pdf_page"),
    )


class TestPageBoundaryReconstruction:
    def test_the_sentence_cut_by_the_page_boundary_is_reconstructed(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        found = [s for span in spans for s in sentences(span.text)]
        assert any(normalize_for_match(FULL_SENTENCE) == normalize_for_match(s) for s in found)

    def test_block_order_is_preserved_in_the_span(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        glued = next(s for s in spans if len(s.blocks) > 1)
        assert [b.locator for b in glued.blocks] == ["page 4", "page 5"]

    def test_independent_paragraphs_are_not_fused_into_one_sentence(self, real_pages) -> None:
        """« …modification. » clôt la phrase ; « Les indications portées… »
        appartient au paragraphe suivant et doit rester une phrase distincte."""
        spans = logical_spans(real_pages)
        found = [s for span in spans for s in sentences(span.text)]
        witness = [s for s in found if "tenir compte" in s]
        assert witness
        assert all("Les indications" not in s for s in witness)

    def test_a_real_heading_still_blocks_fusion(self) -> None:
        """« ARTICLE 2 : RÉCEPTION DES VÉHICULES » (candidat DEV 128) est un
        titre : le bloc qui le suit ne se recolle pas au bloc précédent."""
        blocks = (
            TextBlock(
                locator="page 2", text="Le titulaire s'engage à faciliter la", method="pdf_page"
            ),
            TextBlock(
                locator="page 3", text="ARTICLE 2 : RÉCEPTION DES VÉHICULES", method="pdf_page"
            ),
            TextBlock(
                locator="page 4", text="réception des véhicules dans l'atelier.", method="pdf_page"
            ),
        )
        spans = logical_spans(blocks)
        assert all(len(span.blocks) == 1 for span in spans)


class TestMultiBlockEvidence:
    def test_the_reconstructed_sentence_carries_one_raw_piece_per_page(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        glued = next(s for s in spans if len(s.blocks) > 1)
        sentence = next(
            s
            for s in sentences(glued.text)
            if normalize_for_match(s) == normalize_for_match(FULL_SENTENCE)
        )
        pieces = glued.pieces_for(sentence)
        assert [p.block.locator for p in pieces] == ["page 4", "page 5"]
        for piece in pieces:
            assert piece.text in piece.block.text  # citation brute, jamais recomposée

    def test_no_text_is_invented_by_the_reconstruction(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        glued = next(s for s in spans if len(s.blocks) > 1)
        sentence = next(
            s
            for s in sentences(glued.text)
            if normalize_for_match(s) == normalize_for_match(FULL_SENTENCE)
        )
        pieces = glued.pieces_for(sentence)
        rebuilt = " ".join(piece.text for piece in pieces)
        assert normalize_for_match(rebuilt) == normalize_for_match(sentence)


class TestSpanCandidates:
    """Le constructeur de corpus découpe sur les spans, plus jamais sur les pages."""

    def test_the_page_truncated_candidate_disappears(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        picked = span_candidates(real_pages, spans)
        excerpts = [normalize_for_match(sentence) for _, sentence in picked]
        # Le gate §8 : zéro candidat tronqué au seul motif d'une frontière de page.
        assert normalize_for_match(TRUNCATED) not in excerpts
        assert normalize_for_match(FULL_SENTENCE) in excerpts

    def test_each_candidate_maps_back_to_the_block_where_it_starts(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        picked = span_candidates(real_pages, spans)
        index = next(
            i
            for i, sentence in picked
            if normalize_for_match(sentence) == normalize_for_match(FULL_SENTENCE)
        )
        assert real_pages[index].locator == "page 4"


class TestSnapshotAcceptsMultiBlockExcerpts:
    def test_a_page_crossing_excerpt_is_frozen_with_its_raw_pieces(self, real_pages) -> None:
        spans = logical_spans(real_pages)
        glued = next(s for s in spans if len(s.blocks) > 1)
        sentence = next(
            s
            for s in sentences(glued.text)
            if normalize_for_match(s) == normalize_for_match(FULL_SENTENCE)
        )
        snapshot = snapshot_candidate(
            candidate_id=1,
            award_reference="26-134567",
            document_name="CCTP.pdf",
            document_hash="cafe",
            media_type="application/pdf",
            blocks=real_pages,
            index=1,
            excerpt=sentence,
            spans=spans,
        )
        assert len(snapshot.evidence_pieces) == 2
        locators = [locator for locator, _ in snapshot.evidence_pieces]
        assert locators == ["page 4", "page 5"]
        for locator, text in snapshot.evidence_pieces:
            block = next(b for b in real_pages if b.locator == locator)
            assert text in block.text

    def test_a_single_block_excerpt_keeps_an_empty_pieces_list(self, real_pages) -> None:
        snapshot = snapshot_candidate(
            candidate_id=2,
            award_reference="26-134567",
            document_name="CCTP.pdf",
            document_hash="cafe",
            media_type="application/pdf",
            blocks=real_pages,
            index=1,
            excerpt="Le titulaire du marché devra tenir compte",
            spans=logical_spans(real_pages),
        )
        assert snapshot.evidence_pieces == ()

    def test_an_absent_excerpt_is_still_refused(self, real_pages) -> None:
        with pytest.raises(ValueError):
            snapshot_candidate(
                candidate_id=3,
                award_reference="26-134567",
                document_name="CCTP.pdf",
                document_hash="cafe",
                media_type="application/pdf",
                blocks=real_pages,
                index=1,
                excerpt="Cette phrase n'existe nulle part dans le document source.",
                spans=logical_spans(real_pages),
            )
