"""FR-DCE-1 — ce que le corpus français garantit avant d'être étiqueté.

Livré **sans gold**. Ces tests vérifient ce qui peut l'être sans étiquettes, et
surtout les deux propriétés que les corpus précédents n'avaient pas :

- les candidats sont des **phrases**, contenues dans un bloc plus large, donc la
  vérification de preuve a du mordant — sur HELD-OUT-3 l'extrait *était* le bloc,
  et le contrôle ne discriminait presque rien ;
- ils portent tous un verbe normatif, parce que le filtre de modalité fonctionne
  enfin : il comparait à la chaîne `"none"` alors que `detect_modality` rend
  `None`, et laissait donc passer titres, en-têtes et lignes de pointillés.
"""

from __future__ import annotations

import collections
import json
import pathlib

from signals.documents.extract import TextBlock
from signals.documents.language import detect_modality, normalize_for_match
from signals.documents.snapshot import CandidateSnapshot, excerpt_locates_in_blocks

CORPUS_PATH = pathlib.Path(__file__).parent / "fixtures" / "documents" / "fr_dce_candidates.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
ROWS = CORPUS["rows"]
SOURCES = {s["document_hash"]: s for s in CORPUS["sources"]}
PRIORITY = {"technical_specification", "contract_conditions", "bill_of_quantities", "annex"}


def blocks_of(row: dict) -> list[TextBlock]:
    return [
        TextBlock(locator=row["source_locator"], text=text, method="snapshot")
        for text in (row["current_block"], row["logical_span"])
        if text
    ]


class TestTheCorpusShape:
    def test_it_holds_two_hundred_candidates(self) -> None:
        assert len(ROWS) == 200

    def test_candidate_ids_are_contiguous(self) -> None:
        assert sorted(r["candidate_id"] for r in ROWS) == list(range(1, 201))

    def test_several_consultations_are_represented(self) -> None:
        assert len({SOURCES[r["document_hash"]]["consultation"] for r in ROWS}) >= 10

    def test_no_single_consultation_dominates(self) -> None:
        counts = collections.Counter(SOURCES[r["document_hash"]]["consultation"] for r in ROWS)
        assert max(counts.values()) <= len(ROWS) // 3

    def test_the_priority_document_kinds_carry_the_sample(self) -> None:
        """CCTP, CCAP, BPU/DQE et annexes techniques d'abord."""
        kinds = collections.Counter(SOURCES[r["document_hash"]]["kind"] for r in ROWS)
        assert sum(kinds[k] for k in PRIORITY) >= len(ROWS) * 0.6

    def test_the_three_office_formats_are_present(self) -> None:
        media = {r["media_type"] for r in ROWS}
        assert any("pdf" in m for m in media)
        assert any("spreadsheetml" in m for m in media)
        assert any("wordprocessingml" in m for m in media)


class TestTheCandidatesAreSentencesNotBlocks:
    def test_most_excerpts_sit_inside_a_larger_block(self) -> None:
        """C'est ce qui rend `evidence_coverage` capable de rejeter une invention."""
        inside = [r for r in ROWS if len(r["current_block"]) > len(r["excerpt"])]
        assert len(inside) >= len(ROWS) * 0.8

    def test_every_excerpt_is_found_in_its_source_blocks(self) -> None:
        for row in ROWS:
            assert excerpt_locates_in_blocks(row["excerpt"], blocks_of(row)), row["candidate_id"]

    def test_every_candidate_carries_a_normative_verb(self) -> None:
        """Le filtre de modalité qui ne filtrait rien est corrigé et vérifié ici."""
        without = [r["candidate_id"] for r in ROWS if detect_modality(r["excerpt"]) is None]
        assert without == []

    def test_no_sentence_appears_twice(self) -> None:
        """Un texte type répété dans chaque lot ne doit pas gaspiller l'annotation."""
        texts = [normalize_for_match(r["excerpt"]) for r in ROWS]
        assert len(set(texts)) == len(texts)


class TestTheContextIsReal:
    def test_each_row_rebuilds_into_a_snapshot(self) -> None:
        for row in ROWS:
            assert isinstance(CandidateSnapshot(**row), CandidateSnapshot)

    def test_most_candidates_have_a_neighbouring_block(self) -> None:
        with_neighbour = [r for r in ROWS if r["previous_block"] or r["next_block"]]
        assert len(with_neighbour) >= len(ROWS) * 0.8

    def test_every_document_hash_is_a_real_digest(self) -> None:
        for row in ROWS:
            assert len(row["document_hash"]) == 64, row["candidate_id"]

    def test_every_row_names_its_source_blocks(self) -> None:
        for row in ROWS:
            assert row["source_block_locators"], row["candidate_id"]


class TestProvenanceAndAccess:
    def test_the_corpus_is_french(self) -> None:
        assert CORPUS["language"] == "fr"

    def test_it_records_how_the_documents_were_obtained(self) -> None:
        note = CORPUS["access_note"]
        assert "VIDES" in note
        assert "Aucun login" in note
        assert "aucune identité fabriquée" in note

    def test_it_records_that_candidates_are_sentences(self) -> None:
        assert "phrase" in CORPUS["candidate_unit"]

    def test_it_carries_no_credential(self) -> None:
        """La note d'accès NOMME les champs de contact : c'est la documentation
        de la méthode, pas une donnée. Ce qui est interdit, c'est un secret.

        Les adresses de contact que le corpus contient viennent du TEXTE des
        documents publiés — un CCAP nomme le délégué à la protection des données
        de l'acheteur. C'est du contenu public de marché, pas notre identité.
        """
        blob = CORPUS_PATH.read_text()
        for marker in ("password", "PROD_APC_ID", "Bearer ", "Authorization", "sk-"):
            assert marker not in blob

    def test_no_contact_field_ever_holds_a_value(self) -> None:
        for row in ROWS:
            for key in ("nomEntiteContact", "nomPointContact", "mailPointContact"):
                assert key not in row


class TestTheGoldIsStillMissing:
    def test_no_row_carries_a_label(self) -> None:
        for row in ROWS:
            assert not [k for k in row if k.startswith("gold")], row["candidate_id"]

    def test_the_file_says_so(self) -> None:
        assert CORPUS["gold_status"].startswith("ABSENT")


def _pieces_reconstruct(excerpt: str, blocks: list[str]) -> bool:
    """L'extrait se recompose-t-il de morceaux exacts, dans l'ordre des blocs ?

    Chaque morceau doit se retrouver **tel quel** dans son bloc, et les blocs
    doivent être consommés dans l'ordre déclaré. Un collage qui inverserait deux
    blocs, sauterait du texte ou en ajouterait échoue ici.
    """
    remaining = excerpt.strip()
    for block in blocks:
        if not remaining:
            return True
        # Le plus long préfixe de ce qui reste que ce bloc porte exactement.
        cut = len(remaining)
        while cut > 0 and remaining[:cut] not in block:
            cut -= 1
        if cut == 0:
            continue
        remaining = remaining[cut:].strip()
    return not remaining


class TestEvidenceIsAlwaysReconstructible:
    """Deux cas autorisés, jamais un troisième — SPEC pre-gold integrity gate.

    Soit l'extrait figure **tel quel** dans un bloc source brut, soit il se
    recompose de morceaux exacts pris dans l'ordre de ses blocs déclarés. Rien
    d'autre : un texte introuvable dans la source ne peut pas fonder une preuve,
    quelle que soit la confiance du modèle qui le citerait.
    """

    def test_every_candidate_is_exact_or_reconstructible(self) -> None:
        failures = []
        for row in ROWS:
            exact = row["excerpt"] in row["current_block"]
            rebuilt = _pieces_reconstruct(
                row["excerpt"],
                [t for t in (row["previous_block"], row["current_block"], row["next_block"]) if t],
            )
            if not (exact or rebuilt):
                failures.append(row["candidate_id"])
        assert failures == []

    def test_the_reconstructibility_rate_is_total(self) -> None:
        ok = sum(1 for r in ROWS if r["excerpt"] in r["current_block"])
        assert ok == len(ROWS)

    def test_no_candidate_needs_normalisation_to_be_found(self) -> None:
        """Aucun ne dépend d'un espacement retouché : tous sont bruts."""
        normalised_only = [
            r["candidate_id"]
            for r in ROWS
            if r["excerpt"] not in r["current_block"]
            and normalize_for_match(r["excerpt"]) in normalize_for_match(r["current_block"])
        ]
        assert normalised_only == []

    def test_a_fabricated_excerpt_would_be_caught(self) -> None:
        """Le contrôle mord : une phrase absente échoue les deux cas."""
        row = dict(ROWS[0])
        row["excerpt"] = "Le titulaire doit repeindre la Lune avant le 30 février."
        exact = row["excerpt"] in row["current_block"]
        rebuilt = _pieces_reconstruct(row["excerpt"], [row["current_block"]])
        assert not (exact or rebuilt)

    def test_span_locators_may_exceed_the_blocks_the_excerpt_touches(self) -> None:
        """`source_block_locators` nomme les blocs du SPAN, pas ceux de l'extrait.

        Douze candidats déclarent plusieurs blocs alors que leur phrase tient
        dans un seul. La couche Evidence doit citer le bloc porteur, pas tout le
        span — sinon elle sur-citerait.
        """
        multi = [r for r in ROWS if len(r["source_block_locators"]) > 1]
        assert multi
        for row in multi:
            assert row["excerpt"] in row["current_block"], row["candidate_id"]
