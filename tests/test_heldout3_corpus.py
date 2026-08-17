"""SPEC-006R4 §10/§11 — ce que HELD-OUT-3 doit garantir avant d'être étiqueté.

Le corpus est livré **sans gold**. Ces tests vérifient ce qui peut l'être sans
étiquettes : disjonction avec tous les corpus antérieurs, présence réelle du
voisinage, et surtout que chaque extrait se retrouve dans ses blocs sources —
la garantie que DEV-3 ne pouvait pas offrir, puisque son `source_text` recopiait
l'extrait.

Ils échouent délibérément le jour où quelqu'un ajoute des colonnes `gold_*`
produites par un modèle : le fichier doit rester vierge jusqu'à une revue humaine.
"""

from __future__ import annotations

import collections
import json
import pathlib

from signals.documents.extract import TextBlock
from signals.documents.heldout3_build import known_awards, known_document_hashes
from signals.documents.snapshot import CandidateSnapshot, excerpt_locates_in_blocks

CORPUS_PATH = pathlib.Path(__file__).parent / "fixtures" / "documents" / "heldout3_candidates.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
ROWS = CORPUS["rows"]


def blocks_of(row: dict) -> list[TextBlock]:
    return [
        TextBlock(locator=row["source_locator"], text=text, method="snapshot")
        for text in (row["current_block"], row["logical_span"])
        if text
    ]


class TestTheCorpusIsHeldOut:
    def test_no_document_was_used_by_an_earlier_corpus(self) -> None:
        hashes = {row["document_hash"] for row in ROWS}
        assert hashes.isdisjoint(known_document_hashes(exclude={CORPUS_PATH.name}))

    def test_no_award_was_used_by_an_earlier_corpus(self) -> None:
        awards = {row["award_reference"] for row in ROWS}
        assert awards.isdisjoint(known_awards(exclude={CORPUS_PATH.name}))

    def test_every_document_hash_is_a_real_digest(self) -> None:
        for row in ROWS:
            assert len(row["document_hash"]) == 64, row["candidate_id"]


class TestTheCorpusHasTheRequiredShape:
    def test_it_holds_the_required_number_of_candidates(self) -> None:
        assert len(ROWS) == 150

    def test_candidate_ids_are_unique_and_contiguous(self) -> None:
        assert sorted(row["candidate_id"] for row in ROWS) == list(range(1, 151))

    def test_several_dossiers_are_represented(self) -> None:
        assert len({row["award_reference"] for row in ROWS}) >= 5

    def test_the_three_office_formats_are_present(self) -> None:
        media = {row["media_type"] for row in ROWS}
        assert any("pdf" in m for m in media)
        assert any("wordprocessingml" in m for m in media)
        assert any("spreadsheetml" in m for m in media)

    def test_the_shortfall_against_the_spec_is_recorded(self) -> None:
        """8 dossiers sur 12 : le manque est écrit dans le fichier, pas caché."""
        assert "shortfall" in CORPUS
        assert "8 dossiers" in CORPUS["shortfall"]

    def test_no_single_dossier_dominates(self) -> None:
        counts = collections.Counter(row["award_reference"] for row in ROWS)
        assert max(counts.values()) <= len(ROWS) // 2


class TestEveryCandidateCarriesItsRealContext:
    def test_each_row_has_every_field_the_spec_requires(self) -> None:
        required = {
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
        }
        for row in ROWS:
            assert required <= set(row), row["candidate_id"]

    def test_each_row_rebuilds_into_a_snapshot(self) -> None:
        for row in ROWS:
            assert isinstance(CandidateSnapshot(**row), CandidateSnapshot)

    def test_the_weak_evidence_discrimination_is_recorded(self) -> None:
        """Le candidat EST le bloc source : la preuve garde du sens, pas du mordant.

        Au run, `evidence_coverage` confronte la réponse du modèle — qui peut
        différer du candidat — donc le contrôle n'est pas tautologique comme il
        l'était sur DEV-3. Mais tant que la meule égale l'aiguille sur la
        plupart des lignes, ce critère du gate discrimine peu, et le corpus doit
        le dire lui-même plutôt que laisser lire un 100 % flatteur.
        """
        identical = [r["candidate_id"] for r in ROWS if r["current_block"] == r["excerpt"]]
        assert CORPUS["evidence_caveat"]
        assert str(len(identical)) in CORPUS["evidence_caveat"]

    def test_a_few_candidates_span_several_blocks(self) -> None:
        """Ceux-là valident vraiment le recollement et la preuve multi-blocs."""
        assert CORPUS["context_stats"]["multi_block_spans"] >= 5

    def test_most_candidates_have_a_neighbouring_block(self) -> None:
        with_neighbour = [r for r in ROWS if r["previous_block"] or r["next_block"]]
        assert len(with_neighbour) >= len(ROWS) * 0.9

    def test_every_excerpt_is_found_in_its_source_blocks(self) -> None:
        """La règle absolue de SPEC-006, vérifiée sur le corpus lui-même."""
        for row in ROWS:
            assert excerpt_locates_in_blocks(row["excerpt"], blocks_of(row)), row["candidate_id"]

    def test_every_row_names_its_source_blocks(self) -> None:
        for row in ROWS:
            assert row["source_block_locators"], row["candidate_id"]


class TestTheGoldIsStillMissing:
    def test_the_corpus_carries_no_label(self) -> None:
        """Un gold posé par un modèle ferait mesurer un accord, pas une justesse."""
        for row in ROWS:
            assert not [key for key in row if key.startswith("gold")], row["candidate_id"]

    def test_the_file_says_so_explicitly(self) -> None:
        assert CORPUS["gold_status"].startswith("ABSENT")

    def test_it_records_the_sampling_method(self) -> None:
        assert "tourniquet" in CORPUS["sampling"]
        assert "aucune sélection" in CORPUS["sampling"]
