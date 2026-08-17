"""FR-DCE-1 gold — intégrité du corpus et des étiquettes.

Le gold a été posé avant tout appel de modèle. Ces tests protègent trois choses :
que le corpus n'a pas bougé sous lui, que les étiquettes couvrent exactement les
candidats, et que chaque preuve reste retrouvable dans son bloc source.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"
CORPUS_PATH = FIXTURES / "fr_dce_candidates.json"
EXT_PATH = FIXTURES / "fr_dce_candidates_ext.json"
GOLD_PATH = FIXTURES / "fr_dce_gold.json"

CORPUS_SHA = "ed1c5fd7ac9858ea9d06b4a366b1ab30d75a206afb9ecbb7851b783284335d0b"
EXT_SHA = "ec9fc3c0e83a4da242e45379bbf7509f2743c81910353534d16482ccdd641e5f"
GOLD_SHA = "7ae20536bfaabe48979627adeb26db81f94d801482b834886a6f62e1d5d13673"

GOLD = json.loads(GOLD_PATH.read_text())
ROWS = {r["candidate_id"]: r for r in GOLD["rows"]}
CANDIDATES = {}
for path in (CORPUS_PATH, EXT_PATH):
    for row in json.loads(path.read_text())["rows"]:
        CANDIDATES[row["candidate_id"]] = row


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestNothingMovedUnderTheGold:
    def test_the_base_corpus_hash_is_unchanged(self) -> None:
        assert digest(CORPUS_PATH) == CORPUS_SHA

    def test_the_extension_hash_is_unchanged(self) -> None:
        assert digest(EXT_PATH) == EXT_SHA

    def test_the_gold_hash_is_unchanged(self) -> None:
        assert digest(GOLD_PATH) == GOLD_SHA

    def test_the_gold_names_the_corpus_it_was_built_on(self) -> None:
        declared = {f["file"]: f["sha256"] for f in GOLD["corpus_files"]}
        assert declared["fr_dce_candidates.json"] == CORPUS_SHA
        assert declared["fr_dce_candidates_ext.json"] == EXT_SHA


class TestIdsAreAligned:
    def test_every_candidate_has_exactly_one_label(self) -> None:
        assert sorted(ROWS) == sorted(CANDIDATES)

    def test_there_are_four_hundred(self) -> None:
        assert len(ROWS) == 400

    def test_no_candidate_id_repeats(self) -> None:
        ids = [r["candidate_id"] for r in GOLD["rows"]]
        assert len(set(ids)) == len(ids)


class TestEvidenceStaysReconstructible:
    def test_the_gold_excerpt_matches_the_candidate(self) -> None:
        for cid, row in ROWS.items():
            assert row["gold_exact_excerpt"] == CANDIDATES[cid]["excerpt"], cid

    def test_every_excerpt_is_found_in_its_source_block(self) -> None:
        for cid, row in ROWS.items():
            assert row["gold_exact_excerpt"] in CANDIDATES[cid]["current_block"], cid

    def test_locators_name_only_the_block_carrying_the_excerpt(self) -> None:
        """§3 : ne pas citer tout le span quand la phrase tient dans un bloc."""
        for cid, row in ROWS.items():
            assert row["gold_source_locators"] == [CANDIDATES[cid]["source_locator"]], cid

    def test_the_reconstructibility_rate_is_total(self) -> None:
        ok = sum(
            1
            for cid, r in ROWS.items()
            if r["gold_exact_excerpt"] in CANDIDATES[cid]["current_block"]
        )
        assert ok == len(ROWS)


class TestTheLabelsObeyTheGoldRule:
    def test_auto_acceptable_requires_execution_and_contractor(self) -> None:
        for row in GOLD["rows"]:
            if row["gold_disposition"] != "auto_acceptable":
                continue
            assert row["gold_phase"] == "execution", row["candidate_id"]
            assert row["gold_obligated_actor"] == "contractor", row["candidate_id"]
            assert row["gold_modality"] in {"mandatory", "prohibited", "optional"}
            assert row["gold_context_status"] == "sufficient", row["candidate_id"]

    def test_anything_not_auto_carries_a_reason(self) -> None:
        for row in GOLD["rows"]:
            if row["gold_disposition"] != "auto_acceptable":
                assert row["gold_reason"], row["candidate_id"]

    def test_auto_acceptable_carries_no_rejection_reason(self) -> None:
        for row in GOLD["rows"]:
            if row["gold_disposition"] == "auto_acceptable":
                assert row["gold_reason"] is None, row["candidate_id"]

    def test_the_sufficiency_floor_is_met(self) -> None:
        counts = collections.Counter(r["gold_disposition"] for r in GOLD["rows"])
        assert counts["auto_acceptable"] >= 40

    def test_the_three_dispositions_are_all_used(self) -> None:
        counts = collections.Counter(r["gold_disposition"] for r in GOLD["rows"])
        assert set(counts) == {"auto_acceptable", "review_expected", "reject"}


class TestTheGoldDeclaresItsOwnLimits:
    def test_it_records_who_adjudicated(self) -> None:
        assert "aveugle" in GOLD["adjudicator"]

    def test_it_records_that_the_adjudicator_is_a_model(self) -> None:
        """Un gold posé par un modèle mesure un accord, pas une vérité humaine."""
        assert "pas une vérité humaine" in GOLD["independence_caveat"]

    def test_it_records_the_fragment_rule(self) -> None:
        assert "syntaxiquement incomplet" in GOLD["adjudication_rule"]

    def test_every_review_change_is_journalled(self) -> None:
        for change in GOLD["review_changes"]:
            assert change["candidate_id"] in ROWS
            assert change["old_label"] and change["new_label"] and change["reason"]
