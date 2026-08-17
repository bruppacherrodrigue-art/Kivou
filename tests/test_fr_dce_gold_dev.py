"""SPEC-006R5 §3, §9 — la vue DEV corrigée du gold FR-DCE-1.

Le corpus FR-DCE-1 a servi au benchmark du 17 août 2026 : exécuté, analysé,
audité erreur par erreur. Il devient DEV-FR-DCE et ne peut plus servir de gate
final. L'audit contradictoire en double aveugle (14 agents,
`fr_dce_bench_audit_2026-08-17.json`) a établi des corrections d'étiquettes qui
sont appliquées ici dans une vue SÉPARÉE — le gold historique reste intact,
octet pour octet.

Aucune correction n'est motivée par les résultats DeepSeek : chaque entrée du
journal référence le verdict d'audit qui la justifie.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

FIXTURES = pathlib.Path("tests/fixtures/documents")
HISTORICAL_GOLD_SHA = "7ae20536bfaabe48979627adeb26db81f94d801482b834886a6f62e1d5d13673"

EXPECTED_CORRECTIONS = {
    155: ("auto_acceptable", "reject"),
    156: ("auto_acceptable", "reject"),
    208: ("auto_acceptable", "review_expected"),
    76: ("auto_acceptable", "review_expected"),
    34: ("reject", "review_expected"),
    289: ("reject", "review_expected"),
    178: ("reject", "review_expected"),
    225: ("reject", "review_expected"),
    284: ("reject", "review_expected"),
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestHistoricalGoldIsUntouched:
    def test_the_frozen_gold_still_has_its_original_sha(self) -> None:
        digest = hashlib.sha256((FIXTURES / "fr_dce_gold.json").read_bytes()).hexdigest()
        assert digest == HISTORICAL_GOLD_SHA


class TestDevGoldView:
    def test_the_dev_view_exists_and_covers_all_400_candidates(self) -> None:
        dev = _load("fr_dce_gold_dev.json")
        assert dev["corpus"] == "DEV-FR-DCE"
        assert len(dev["rows"]) == 400
        assert sorted(r["candidate_id"] for r in dev["rows"]) == list(range(1, 401))

    def test_the_dev_view_declares_its_origin(self) -> None:
        dev = _load("fr_dce_gold_dev.json")
        assert dev["derived_from"] == "fr_dce_gold.json"
        assert dev["source_gold_sha256"] == HISTORICAL_GOLD_SHA
        assert dev["audit_reference"] == "fr_dce_bench_audit_2026-08-17.json"

    def test_every_correction_is_journaled_with_its_audit_reference(self) -> None:
        dev = _load("fr_dce_gold_dev.json")
        journal = {c["candidate_id"]: c for c in dev["corrections"]}
        assert set(journal) == set(EXPECTED_CORRECTIONS)
        for cid, (old, new) in EXPECTED_CORRECTIONS.items():
            entry = journal[cid]
            assert entry["old_label"] == old
            assert entry["new_label"] == new
            assert entry["reason"].strip()
            assert entry["audit_reference"] == "fr_dce_bench_audit_2026-08-17.json"

    def test_corrections_match_the_recorded_audit_verdicts(self) -> None:
        """Chaque correction doit exister dans l'audit — jamais une correction
        inventée après coup, jamais une correction motivée par un modèle."""
        audit = _load("fr_dce_bench_audit_2026-08-17.json")
        audited = {
            v["candidate_id"]
            for batch in audit["batches"]
            for v in batch["verdicts"]
            if v["gold_verdict"] in ("incorrect", "borderline")
        }
        assert set(EXPECTED_CORRECTIONS) <= audited

    def test_corrected_rows_carry_the_new_label_and_others_are_identical(self) -> None:
        historical = {r["candidate_id"]: r for r in _load("fr_dce_gold.json")["rows"]}
        dev = {r["candidate_id"]: r for r in _load("fr_dce_gold_dev.json")["rows"]}
        for cid in range(1, 401):
            if cid in EXPECTED_CORRECTIONS:
                old, new = EXPECTED_CORRECTIONS[cid]
                assert historical[cid]["gold_disposition"] == old
                assert dev[cid]["gold_disposition"] == new
            else:
                assert dev[cid] == historical[cid]

    def test_the_corrected_gold_has_40_clear_execution_requirements(self) -> None:
        dev = _load("fr_dce_gold_dev.json")
        autos = [r for r in dev["rows"] if r["gold_disposition"] == "auto_acceptable"]
        assert len(autos) == 40
