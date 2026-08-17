"""FR-DCE-FINAL — l'intégrité du held-out final gelé (SPEC-006R5.1 §7).

Corpus et gold sont immuables depuis le 17 août 2026, AVANT le premier appel
modèle. Ces tests épinglent les empreintes et les invariants : toute
modification ultérieure — même bien intentionnée — doit casser ici.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

FIXTURES = pathlib.Path("tests/fixtures/documents")
FINAL_CORPUS_SHA256 = "2e3c86fd31c366c1782babd97a985a916484b60995c0e7cf77b3f8a431141105"
FINAL_GOLD_SHA256 = "beb1eb060ca53cd77a0960ecfb52abb4ec76eba87881e0a174c55ee3034e6431"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestFreeze:
    def test_the_corpus_is_byte_identical_to_its_frozen_form(self) -> None:
        digest = hashlib.sha256(
            (FIXTURES / "fr_dce_final_candidates.json").read_bytes()
        ).hexdigest()
        assert digest == FINAL_CORPUS_SHA256

    def test_the_gold_is_byte_identical_to_its_frozen_form(self) -> None:
        digest = hashlib.sha256((FIXTURES / "fr_dce_final_gold.json").read_bytes()).hexdigest()
        assert digest == FINAL_GOLD_SHA256

    def test_the_gold_declares_the_corpus_it_was_built_on(self) -> None:
        gold = _load("fr_dce_final_gold.json")
        declared = {f["file"]: f["sha256"] for f in gold["corpus_files"]}
        assert declared == {"fr_dce_final_candidates.json": FINAL_CORPUS_SHA256}


class TestAlignment:
    def test_every_candidate_has_exactly_one_gold_row(self) -> None:
        corpus_ids = sorted(
            r["candidate_id"] for r in _load("fr_dce_final_candidates.json")["rows"]
        )
        gold_ids = sorted(r["candidate_id"] for r in _load("fr_dce_final_gold.json")["rows"])
        assert corpus_ids == gold_ids == list(range(1, 301))

    def test_every_gold_excerpt_is_the_candidate_sentence(self) -> None:
        candidates = {r["candidate_id"]: r for r in _load("fr_dce_final_candidates.json")["rows"]}
        for row in _load("fr_dce_final_gold.json")["rows"]:
            assert row["gold_exact_excerpt"] == candidates[row["candidate_id"]]["excerpt"]
            assert row["document_hash"] == candidates[row["candidate_id"]]["document_hash"]


class TestGoldInvariants:
    def test_the_composition_matches_the_declared_counts(self) -> None:
        gold = _load("fr_dce_final_gold.json")
        counts = {"auto_acceptable": 0, "review_expected": 0, "reject": 0}
        for row in gold["rows"]:
            counts[row["gold_disposition"]] += 1
        assert counts == gold["gold"]
        assert counts["auto_acceptable"] == 66

    def test_every_clear_requirement_is_internally_coherent(self) -> None:
        for row in _load("fr_dce_final_gold.json")["rows"]:
            if row["gold_disposition"] != "auto_acceptable":
                continue
            assert row["gold_phase"] == "execution"
            assert row["gold_obligated_actor"] == "contractor"
            assert row["gold_modality"] in ("mandatory", "prohibited", "optional")
            assert row["gold_context_status"] == "sufficient"
            assert row["gold_reason"] is None

    def test_every_pass_b_correction_is_journaled(self) -> None:
        gold = _load("fr_dce_final_gold.json")
        assert len(gold["review_changes"]) == 28
        for change in gold["review_changes"]:
            assert change["old"] != change["new"]
            assert change["source"] in ("pass_b_refutation", "pass_b_border_readjudication")
            assert change["note"].strip()

    def test_the_adjudication_predates_any_model_call(self) -> None:
        gold = _load("fr_dce_final_gold.json")
        assert "AVANT tout appel modèle" in gold["adjudicator"]
        assert "DeepSeek" in gold["independence_caveat"]


class TestDisjointness:
    def test_no_final_sentence_exists_in_any_previous_corpus(self) -> None:
        from signals.documents.heldout3_build import known_sentence_hashes
        from signals.documents.language import normalize_for_match

        previous = known_sentence_hashes(
            exclude=("fr_dce_final_candidates.json", "fr_dce_final_gold.json")
        )
        for row in _load("fr_dce_final_candidates.json")["rows"]:
            digest = hashlib.sha256(normalize_for_match(row["excerpt"]).encode()).hexdigest()
            assert digest not in previous

    def test_no_final_document_exists_in_any_previous_corpus(self) -> None:
        import signals.documents.heldout3_build as build

        previous = build.known_document_hashes(
            exclude=("fr_dce_final_candidates.json", "fr_dce_final_gold.json", "MANIFEST.json")
        )
        for row in _load("fr_dce_final_candidates.json")["rows"]:
            assert row["document_hash"] not in previous

    def test_no_final_consultation_was_sampled_before(self) -> None:
        from signals.documents.heldout3_build import known_consultations

        previous = known_consultations(
            exclude=("fr_dce_final_candidates.json", "fr_dce_final_gold.json")
        )
        corpus = _load("fr_dce_final_candidates.json")
        for source in corpus["sources"]:
            assert source["consultation"] not in previous
