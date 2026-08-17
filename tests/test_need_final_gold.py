"""NEED-FINAL — l'intégrité du held-out final gelé (SPEC-007R1 §24).

Corpus et gold sont immuables depuis le 17 août 2026, AVANT toute exécution du
moteur. Ces tests épinglent les empreintes, la disjonction avec DEV-2 et les
invariants du gold : toute modification ultérieure doit casser ici.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

FIXTURES = pathlib.Path("tests/fixtures/needs")
CATEGORIES = {
    "workforce_capacity",
    "equipment_or_rental",
    "materials_or_components",
    "logistics_and_transport",
    "specialist_subcontracting",
    "safety_and_ppe",
    "waste_and_environment",
}
STATES = {"supported", "plausible_but_weak", "forbidden"}

FINAL_CORPUS_SHA256 = "666050002f7b386a6ac8e1f818a33c6caf38d14573f9b54134cfac9f87b4072e"
FINAL_GOLD_SHA256 = "addee475455140b276d1c8c2233e0bce2b637fee536d76f915f30e34a7cf1fb6"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _sha(name: str) -> str:
    return hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()


class TestFreeze:
    def test_the_corpus_matches_its_published_fingerprint(self) -> None:
        declared = _load("need_final_gold.json")["frozen"]["corpus_sha256"]
        assert _sha("need_final_corpus.json") == declared == FINAL_CORPUS_SHA256

    def test_the_gold_is_byte_identical_to_its_frozen_form(self) -> None:
        assert _sha("need_final_gold.json") == FINAL_GOLD_SHA256

    def test_the_gold_declares_the_versions_it_was_frozen_with(self) -> None:
        frozen = _load("need_final_gold.json")["frozen"]
        assert frozen["rubric_version"] == "need-support-rubric-v1"
        assert frozen["rule_library_version"] == "need-rules-v0.4"
        assert frozen["engine_version"] == "need-graph-v0.1"


class TestComposition:
    def test_the_corpus_meets_the_size_requirement(self) -> None:
        """§22 — au moins 60 award-lots et 40 notices distinctes."""
        corpus = _load("need_final_corpus.json")
        assert len(corpus["rows"]) >= 60
        assert len({row["notice"] for row in corpus["rows"]}) >= 40

    def test_the_unit_is_the_award_lot(self) -> None:
        assert _load("need_final_corpus.json")["unit"] == "award-lot"

    def test_every_award_lot_has_a_complete_gold_row(self) -> None:
        corpus = _load("need_final_corpus.json")
        gold = _load("need_final_gold.json")
        assert len(gold["rows"]) == len(corpus["rows"])
        for row in gold["rows"]:
            assert set(row["verdicts"]) == CATEGORIES
            assert set(row["verdicts"].values()) <= STATES
            assert row["gold_timing"] in (
                "immediate",
                "near_term",
                "medium_term",
                "recurring",
                "unknown",
            )


class TestDisjointness:
    def test_no_notice_is_shared_with_dev2(self) -> None:
        """§22 — aucune procédure commune avec le corpus qui a servi aux règles."""
        dev2 = json.loads((pathlib.Path("tests/fixtures/contract100") / "awards.json").read_text())
        used_notices = {str(row.get("notice")) for row in dev2}
        used_ids = {
            str((row["award"].get("event_ref") or {}).get("source_notice_id")) for row in dev2
        }
        for row in _load("need_final_corpus.json")["rows"]:
            assert str(row["notice"]) not in used_notices
            assert (
                str((row["award"].get("event_ref") or {}).get("source_notice_id")) not in used_ids
            )

    def test_no_award_identity_is_shared_with_dev2(self) -> None:
        dev2 = json.loads((pathlib.Path("tests/fixtures/contract100") / "awards.json").read_text())

        def identity(row: dict) -> str:
            ref = row["award"].get("event_ref") or {}
            return f"{ref.get('source_notice_id')}::{row['award'].get('source_award_id')}"

        used = {identity(row) for row in dev2}
        for row in _load("need_final_corpus.json")["rows"]:
            assert identity(row) not in used


class TestAdjudication:
    def test_the_gold_predates_any_engine_run(self) -> None:
        gold = _load("need_final_gold.json")
        assert "AVANT tout run du moteur" in gold["adjudicator"]

    def test_the_inter_pass_agreement_clears_its_gate(self) -> None:
        """§23 — sans 85 % d'accord entre deux passes, le gold serait invalide."""
        agreement = _load("need_final_gold.json")["agreement"]
        assert agreement["agreement"] >= 0.85

    def test_every_disagreement_was_arbitrated_and_journaled(self) -> None:
        gold = _load("need_final_gold.json")
        agreement = gold["agreement"]
        assert len(gold["arbitrations"]) == agreement["disagreements"]
        for entry in gold["arbitrations"]:
            assert entry["pass_a"] != entry["pass_b"]
            assert entry["arbitrated"] in STATES
