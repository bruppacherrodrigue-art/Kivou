"""Le DEV set du vérificateur commercial, gelé (SPEC-009A §4, §28, §29, §48).

Deux choses sont épinglées ici :

* **Les artefacts SPEC-009 sont intacts.** §4 les déclare préservés ; leurs
  empreintes sont recalculées à chaque exécution de la suite.
* **Le gold des 50 borderline est figé**, avec sa composition et son accord
  inter-adjudicateurs — produits AVANT le premier appel au modèle, ce qui est la
  seule façon d'empêcher le gold de dériver vers ce que le modèle sait faire.

Aucun accès réseau.
"""

from __future__ import annotations

import collections
import hashlib
import json
import pathlib
from typing import Final

import pytest

from signals.research.signal100_adjudication import DIMENSIONS, needs_arbitration, resolve

FIXTURES = pathlib.Path("tests/fixtures/signal100")
DEV_GOLD = FIXTURES / "verifier_dev_gold.json"

#: §4 — les empreintes SPEC-009 que SPEC-009A ne doit pas toucher.
SIGNAL100_CORPUS_SHA256 = "7996beae4a7c1c609f2db1e7eea647f32beb4c06eb3349071e613aceb224aebf"
SIGNAL100_GOLD_SHA256 = "21be11fc89d27eb8a229b22213454073b0a02cfd2d23bc6b0b6833aaf1d3e5af"

DEV_GOLD_SHA256 = "ce02903d1b987858204e027357027047fd3b8ebd5b407048137aaedbf8195e8a"

#: La composition gelée du 17 août 2026, adjugée avant tout appel au vérificateur.
DEV_BORDERLINE_COMPOSITION = {"A": 6, "B": 21, "C": 16, "D": 7}

IMMUTABLE = (
    "Le gold DEV du vérificateur est IMMUABLE (SPEC-009A §29) : il a été adjugé "
    "et gelé avant le premier appel au modèle. Une divergence d'empreinte "
    "invalide la mesure — restaurer les octets gelés, jamais l'empreinte."
)


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestSpec009ArtefactsPreserved:
    """§4, §48 — SPEC-009A évalue par-dessus SPEC-009, elle ne la réécrit pas."""

    def test_the_signal100_corpus_and_gold_are_byte_identical(self) -> None:
        assert _sha(FIXTURES / "signal100_corpus.json") == SIGNAL100_CORPUS_SHA256, IMMUTABLE
        assert _sha(FIXTURES / "signal100_gold.json") == SIGNAL100_GOLD_SHA256, IMMUTABLE

    def test_every_spec009_artefact_is_still_present(self) -> None:
        for name in (
            "signal100_corpus.json",
            "signal100_blind.json",
            "signal100_gold.json",
            "signal100_metrics.json",
            "signal100_seal.json",
            "signal100_shadow.json",
            "signal100_text.json",
        ):
            assert (FIXTURES / name).exists(), name

    def test_the_frozen_engine_versions_have_not_moved(self) -> None:
        """§48 — un vérificateur ne vaut que confronté aux mêmes moteurs."""
        from signals.matching import (
            MATCH_POLICY_VERSION,
            REFERENCE_ICP_LIBRARY_VERSION,
            SCORE_POLICY_VERSION,
        )
        from signals.needs import ENGINE_VERSION as NEED_VERSION

        assert NEED_VERSION == "need-graph-v0.1"
        assert MATCH_POLICY_VERSION == "icp-match-v0.1"
        assert SCORE_POLICY_VERSION == "signal-score-v0.2"
        assert REFERENCE_ICP_LIBRARY_VERSION == "reference-icps-v0.1"

    def test_document_intelligence_is_still_disabled(self) -> None:
        from signals.documents import AUTO_DOCUMENT_REQUIREMENTS_ENABLED

        assert AUTO_DOCUMENT_REQUIREMENTS_ENABLED is False


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return _load(DEV_GOLD)["records"]


@pytest.mark.skipif(not DEV_GOLD.exists(), reason="le gold DEV n'a pas encore été produit")
class TestDevBorderlineGold:
    def test_the_frozen_fingerprint_matches(self) -> None:
        assert _sha(DEV_GOLD) == DEV_GOLD_SHA256, IMMUTABLE

    def test_fifty_borderline_signals_with_the_frozen_composition(
        self, records: list[dict]
    ) -> None:
        assert len(records) == 50
        composition = collections.Counter(r["final_verdict"] for r in records)
        assert dict(composition) == DEV_BORDERLINE_COMPOSITION, IMMUTABLE

    def test_every_record_is_a_borderline_candidate(self, records: list[dict]) -> None:
        """§28 — le DEV mélange 100 SHOW et 50 BORDERLINE, sans les confondre."""
        assert {r["origin_decision"] for r in records} == {"borderline"}

    def test_the_same_rubric_and_arbitration_doctrine_as_spec009(self, records: list[dict]) -> None:
        """§29 — même rubrique, même règle d'arbitrage : les deux golds sont comparables."""
        assert _load(DEV_GOLD)["rubric"] == "commercial-signal-rubric-v1"
        for record in records:
            required = needs_arbitration(record["review_a"], record["review_b"])
            assert (record["arbitration"] is not None) == required, record["signal_id"]
            resolved = resolve(record["review_a"], record["review_b"], record["arbitration"])
            assert resolved["final_verdict"] == record["final_verdict"]

    def test_grades_stay_inside_the_closed_vocabulary(self, records: list[dict]) -> None:
        for record in records:
            for dimension, allowed in DIMENSIONS.items():
                assert record["final_dimensions"][dimension] in allowed

    def test_the_commercial_doctrine_was_stable(self, records: list[dict]) -> None:
        """Sans ce gate, un mauvais résultat pourrait n'être qu'un désaccord de rubrique."""
        agreement = _load(DEV_GOLD)["agreement"]
        assert agreement["agreement_within_one_grade_rate"] == 100.0
        assert agreement["exact_agreement_rate"] == 80.0
        assert agreement["arbitrations"] == 19

    def test_the_gold_was_frozen_before_any_verifier_output_existed(self) -> None:
        """§29 — aucun champ du vérificateur n'a pu contaminer l'adjudication."""
        blob = json.dumps(_load(DEV_GOLD), ensure_ascii=False)
        for leaked in (
            "commercial_reason",
            "supporting_fact_ids",
            "deliverable_overlap",
            "winner_already_provides_need",
            "final_decision",
        ):
            assert leaked not in blob, leaked


@pytest.mark.skipif(not DEV_GOLD.exists(), reason="le gold DEV n'a pas encore été produit")
class TestDevCandidateSet:
    def test_the_dev_set_is_exactly_one_hundred_and_fifty_candidates(self) -> None:
        """§28 — 100 SHOW + 50 BORDERLINE."""
        from signals.research.verifier_dev import build_dev_candidates

        candidates, gold = build_dev_candidates()
        assert len(candidates) == 150
        assert len(gold) == 150
        origins = collections.Counter(c.origin_decision for c in candidates)
        assert origins == {"show": 100, "borderline": 50}

    def test_every_candidate_carries_a_gold_verdict(self) -> None:
        from signals.research.verifier_dev import build_dev_candidates

        _, gold = build_dev_candidates()
        assert all(entry["gold_verdict"] in ("A", "B", "C", "D") for entry in gold.values())
        composition = collections.Counter(entry["gold_verdict"] for entry in gold.values())
        assert dict(composition) == {"A": 11, "B": 68, "C": 54, "D": 17}

    def test_every_real_candidate_builds_a_usable_view(self) -> None:
        """La vue doit tenir sur les 150 vraies vues aveugles, pas seulement en test."""
        from signals.research.verifier_dev import build_dev_candidates
        from signals.verification.view import build_verifier_input

        candidates, _ = build_dev_candidates()
        for candidate in candidates:
            view = build_verifier_input(candidate.blind)
            assert view.fact_catalog, view.signal_candidate_id
            assert view.derived_needs, view.signal_candidate_id
            assert view.target_icp["primary_need_categories"]

    def test_no_real_candidate_is_lost_to_the_language_gate(self) -> None:
        """§16 — l'interprétation retenue ne détruit pas le rappel sur un marché CH + UE.

        17 des 150 vues ne sont ni clairement françaises ni clairement anglaises,
        mais toutes portent un squelette structuré (CPV + type de contrat) : les
        écarter mécaniquement reviendrait à créer la règle par pays que §16
        interdit.
        """
        from signals.research.verifier_dev import build_dev_candidates
        from signals.verification.view import build_verifier_input

        candidates, _ = build_dev_candidates()
        views = [build_verifier_input(candidate.blind) for candidate in candidates]
        assert sum(1 for view in views if not view.language_supported) == 0
        assert sum(1 for view in views if view.language is None) == 17


APPROVED_MODEL_STUB: Final[dict] = {
    "available": True,
    "model_id": "approved/model",
    "prompt_usd_per_token": 7.98e-08,
    "completion_usd_per_token": 1.596e-07,
    "context_length": 1048576,
}


class TestPreflight:
    """§6, §9 — la garde qui gouverne toute dépense, testée sans réseau."""

    def _preflight(self, candidates: int, model: dict, credits, **kwargs):
        from signals.research.verifier_dev import preflight

        return preflight(
            candidates=candidates,
            approved_model="approved/model",
            model_check=lambda _: model,
            credits_check=credits,
            credentials_required_message="BLOCKED — KEY REQUIRED",
            **kwargs,
        )

    def test_an_unavailable_model_blocks_before_anything_else(self) -> None:
        """§6 — sans le modèle approuvé, on ne cherche pas un remplaçant."""
        report = self._preflight(150, {"available": False}, dict)
        assert report["blocked"] == "SPEC-009A BLOCKED — APPROVED MODEL UNAVAILABLE"
        assert "credits" not in report

    def test_a_missing_credential_blocks_with_the_injected_message(self) -> None:
        """§8 — le libellé vient de l'adaptateur ; ce module ne nomme aucun fournisseur."""

        def missing() -> dict:
            raise RuntimeError("no key")

        report = self._preflight(150, APPROVED_MODEL_STUB, missing)
        assert report["blocked"] == "BLOCKED — KEY REQUIRED"
        assert report["credits"]["reachable"] is False

    def test_the_worst_case_cost_is_estimated_before_spending(self) -> None:
        """§9 — estimer le maximum, pas espérer la moyenne."""
        report = self._preflight(
            150, APPROVED_MODEL_STUB, lambda: {"reachable": True, "remaining_usd": 10.0}
        )
        assert report["estimated_max_cost_usd"] == pytest.approx(0.2035, abs=0.001)
        assert report["budget_usd"] == 1.00
        assert "blocked" not in report

    def test_insufficient_credits_block_the_run(self) -> None:
        report = self._preflight(
            150, APPROVED_MODEL_STUB, lambda: {"reachable": True, "remaining_usd": 0.01}
        )
        assert "INSUFFICIENT CREDITS" in report["blocked"]

    def test_a_run_over_budget_blocks_even_with_credits_available(self) -> None:
        """§9 — le budget SPEC-009A est un plafond propre, indépendant du solde."""
        report = self._preflight(
            5000, APPROVED_MODEL_STUB, lambda: {"reachable": True, "remaining_usd": 999.0}
        )
        assert "COST BUDGET EXHAUSTED" in report["blocked"]


class TestBudgetCeiling:
    def test_the_runner_stops_instead_of_overspending(self) -> None:
        """§9 — aucune augmentation automatique : la course s'arrête."""
        from conftest import make_blind

        from signals.verification.fake import FakeVerificationModel, approving_verification
        from signals.verification.protocol import ModelResponse
        from signals.verification.runner import BudgetExhausted, Candidate, verify_all
        from signals.verification.view import build_verifier_input

        view = build_verifier_input(make_blind())
        expensive = ModelResponse(
            verification=approving_verification(view),
            cost_usd=0.60,
            input_tokens=1,
            output_tokens=1,
        )
        candidates = [Candidate(make_blind(signal_id=f"{i:064d}"), "show") for i in range(5)]
        with pytest.raises(BudgetExhausted, match="COST BUDGET EXHAUSTED"):
            verify_all(
                candidates,
                FakeVerificationModel(default=expensive),
                max_workers=1,
                budget_usd=1.00,
            )
