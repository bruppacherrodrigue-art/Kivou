"""SPEC-006R4 §9 — la politique de consensus rejouée hors ligne sur DEV-3.

Cette étude ne remplace pas le gate. Elle répond à une seule question, avant de
payer un nouveau run : la politique à deux modèles est-elle manifestement
mauvaise ? Elle est reproductible sans réseau et sans credential — les sorties
ligne à ligne des deux modèles sont figées dans une fixture.

Deux limites la rendent indicative et non probante, et les tests les nomment :

1. **Qwen a tourné avec le prompt classifieur**, pas avec le vérificateur de §4.
   Son verdict est *projeté* depuis sa classification. Un vrai vérificateur, qui
   ne répond qu'à une question fermée, se comportera différemment.
2. **Le corpus n'avait pas de voisinage** : `source_text` valait l'extrait. La
   couverture de preuve y est donc vraie par construction et ne prouve rien.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from signals.documents.classification import SemanticClassification
from signals.documents.consensus import VerifierResponse, resolve
from signals.documents.evaluation import evaluate_gate, score

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"
RUNS = json.loads((FIXTURES / "dev3_model_runs.json").read_text())
GOLD = json.loads((FIXTURES / "heldout2_gold.json").read_text())
GOLD_BY_ID = {row["candidate_id"]: row for row in GOLD["rows"]}

ACCEPTED_MODALITIES = {"mandatory", "prohibited", "optional"}

_PHASE_REASON = {
    "procurement": "procurement",
    "qualification": "qualification",
    "contract_formation": "contract_formation",
    "background": "background",
}
_ACTOR_REASON = {
    "buyer": "buyer_obligation",
    "bidder": "bidder_obligation",
    "third_party": "third_party",
}


def project_verifier(row: dict) -> VerifierResponse | None:
    """Projette une classification complète sur le contrat du vérificateur.

    La projection est mécanique et sans marge : elle applique exactement les
    conditions de la politique. Elle ne peut donc pas flatter le consensus —
    tout ce qu'elle fait est traduire un jugement déjà rendu.
    """
    if row["schema_failure"]:
        return None
    if row["phase"] != "execution":
        reason = _PHASE_REASON.get(row["phase"], "other")
        verdict = "uncertain" if row["phase"] == "unknown" else "reject"
    elif row["obligated_actor"] != "contractor":
        reason = _ACTOR_REASON.get(row["obligated_actor"], "other")
        verdict = "uncertain" if row["obligated_actor"] == "unknown" else "reject"
    elif row["modality"] not in ACCEPTED_MODALITIES:
        reason, verdict = "other", "reject"
    elif row["context_status"] != "sufficient":
        reason = "fragment" if row["context_status"] == "fragment" else "insufficient_context"
        verdict = "uncertain"
    else:
        reason, verdict = "execution_contractor", "confirm"
    return VerifierResponse(
        verdict=verdict,  # type: ignore[arg-type]
        reason=reason,  # type: ignore[arg-type]
        source_excerpt="projected",
        confidence=row["confidence"],
    )


def rebuild_primary(row: dict, excerpt: str) -> SemanticClassification | None:
    if row["schema_failure"]:
        return None
    return SemanticClassification(
        phase=row["phase"],
        obligated_actor=row["obligated_actor"],
        modality=row["modality"],
        requirement_type="other",
        context_status=row["context_status"],
        source_excerpt=excerpt,
        confidence=row["confidence"],
    )


def run_study() -> dict:
    decisions = {}
    for key, primary_row in RUNS["primary"].items():
        cid = int(key)
        excerpt = GOLD_BY_ID[cid]["excerpt"]
        primary = rebuild_primary(primary_row, excerpt)

        # Le vérificateur n'est appelé QUE si le primaire aurait accepté (§4).
        called = primary is not None and primary_row["accepted"]
        verifier = project_verifier(RUNS["verifier"][key]) if called else None
        if called and verifier is not None:
            verifier = verifier.model_copy(update={"source_excerpt": excerpt})

        decisions[cid] = resolve(
            primary,
            verifier,
            source_text=excerpt,
            evidence_complete=True,
            verifier_called=called,
        )
    gold = {cid: row["gold_accepted"] for cid, row in GOLD_BY_ID.items()}
    return {"decisions": decisions, "metrics": score(decisions=decisions, gold=gold)}


STUDY = run_study()
METRICS = STUDY["metrics"]


class TestTheStudyIsReproducible:
    def test_the_fixture_pairs_with_the_gold_it_was_measured_against(self) -> None:
        digest = hashlib.sha256((FIXTURES / "heldout2_gold.json").read_bytes()).hexdigest()
        assert RUNS["gold_sha256"] == digest

    def test_the_two_models_are_the_ones_retained_by_the_spec(self) -> None:
        assert RUNS["primary_model"] == "deepseek/deepseek-v4-flash"
        assert RUNS["verifier_model"] == "qwen/qwen3.6-flash"

    def test_the_fixture_carries_no_credential(self) -> None:
        blob = (FIXTURES / "dev3_model_runs.json").read_text()
        for marker in ("sk-or", "Bearer", "Authorization", "api_key"):
            assert marker not in blob

    def test_every_candidate_got_a_decision(self) -> None:
        assert len(STUDY["decisions"]) == 100

    def test_the_verifier_ran_only_where_the_primary_accepted(self) -> None:
        """Le coût du vérificateur suit ce nombre, pas les 100 candidats."""
        called = sum(1 for d in STUDY["decisions"].values() if d.verifier_called)
        accepted_by_primary = sum(1 for row in RUNS["primary"].values() if row["accepted"])
        assert called == accepted_by_primary
        assert called < 40


class TestTheConsensusImprovesOnTheClassifierAlone:
    def test_the_primary_alone_was_below_the_precision_gate(self) -> None:
        """Le point de départ : 26 acceptations, 4 fausses."""
        accepted = [k for k, r in RUNS["primary"].items() if r["accepted"]]
        true_accepts = sum(1 for k in accepted if GOLD_BY_ID[int(k)]["gold_accepted"])
        assert len(accepted) == 26
        assert true_accepts / len(accepted) == pytest.approx(0.846, abs=0.001)

    def test_the_consensus_raises_precision(self) -> None:
        assert METRICS.auto_accepted_precision == pytest.approx(0.947, abs=0.001)

    def test_the_consensus_removes_every_high_confidence_false_accept(self) -> None:
        assert METRICS.high_confidence_false_auto_accepted == 0

    def test_the_single_false_auto_accept_is_the_known_context_artefact(self) -> None:
        """#32 est une phrase tronquée que le gold marque `context_fragment`.

        Les trois modèles l'ont acceptée parce qu'aucun ne voyait le document —
        c'est l'artefact que HELD-OUT-3 doit supprimer, pas une faute de politique.
        """
        false_ids = [
            cid
            for cid, d in STUDY["decisions"].items()
            if d.outcome == "auto_accepted" and not GOLD_BY_ID[cid]["gold_accepted"]
        ]
        assert false_ids == [32]
        assert GOLD_BY_ID[32]["gold_reason"] == "context_fragment"


class TestTheStudyPinsItsNumbers:
    def test_the_three_states_are_all_populated(self) -> None:
        assert METRICS.auto_accepted == 19
        assert METRICS.review_required == 7
        assert METRICS.rejected == 74

    def test_the_review_bucket_holds_real_requirements(self) -> None:
        assert METRICS.true_retained_for_review == 4

    def test_candidate_recall_exceeds_the_floor(self) -> None:
        assert METRICS.candidate_recall == pytest.approx(0.88, abs=0.001)

    def test_auto_recall_exceeds_the_floor(self) -> None:
        assert METRICS.auto_accepted_recall == pytest.approx(0.72, abs=0.001)

    def test_three_real_requirements_were_lost(self) -> None:
        """Un rejet définitif d'une vraie exigence : le coût de la prudence."""
        assert METRICS.true_requirements_lost == 3


class TestTheStudyIsNotTheGate:
    def test_the_policy_is_not_manifestly_bad(self) -> None:
        """Le seul critère que cette étude devait trancher."""
        result = evaluate_gate(METRICS)
        assert result.failures in ((), ("auto_accepted_precision",))

    def test_the_precision_gate_is_still_missed_on_this_corpus(self) -> None:
        assert METRICS.auto_accepted_precision < 0.95

    def test_the_evidence_coverage_here_proves_nothing(self) -> None:
        """`source_text` valait l'extrait : la couverture est vraie par construction."""
        assert METRICS.evidence_coverage == 1.0
        assert "extrait seul" in RUNS["transport"]["context"]

    def test_the_study_records_that_the_verifier_was_a_proxy(self) -> None:
        assert "CLASSIFIEUR" in RUNS["verifier_caveat"]
