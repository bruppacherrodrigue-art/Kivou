"""Les métriques et gates du vérificateur (SPEC-009A §31, §32, §39–§45).

Ce que ces tests garantissent : qu'un gate échoue quand il doit échouer, que la
précision et le rappel ne sont pas confondus, et qu'une panne d'API ne se compte
jamais comme un signal jugé mauvais.

Aucun accès réseau, aucune fixture : les lignes sont synthétiques.
"""

from __future__ import annotations

import pytest

from signals.verification.metrics import (
    DEV_GATES,
    FINAL_GATES,
    cost_and_latency,
    evaluate_gates,
    failure_analysis,
    headline,
    integrity,
    origin_analysis,
    shadow_diagnostics,
    top20,
)


def row(
    index: int = 0,
    *,
    gold: str = "A",
    shown: bool = True,
    origin: str = "show",
    score: int = 90,
    critical: bool = False,
    failure: str | None = None,
    errors: tuple[str, ...] = (),
    source: str = "ted",
) -> dict:
    return {
        "signal_candidate_id": f"sig-{index:03d}",
        "origin_decision": origin,
        "final_decision": "final_show" if shown else "hide",
        "hide_reason": None if shown else (failure or "verdict=reject"),
        "failure_kind": failure,
        "validation_errors": list(errors),
        "verification": None
        if failure in ("schema_failure", "api_rate_limit")
        else {
            "verdict": "approve" if shown else "reject",
            "need_credibility": "credible",
            "icp_fit": "strong",
            "specificity": "specific",
            "timing_status": "current",
            "commercial_reason": "raison",
        },
        "gold_verdict": gold,
        "gold_critical_false_signal": critical,
        "gold_primary_failure_layer": None if gold in ("A", "B") else "need graph",
        "gold_note": "note",
        "source": source,
        "icp_id": "icp-a",
        "contract_type": "construction",
        "matched_needs": ["workforce_capacity"],
        "normalized_score": score,
        "cost_usd": 0.0002,
        "latency_ms": 500.0,
        "input_tokens": 8000,
        "output_tokens": 900,
    }


def _rows(spec: list[tuple[str, bool]], **kwargs) -> list[dict]:
    return [row(i, gold=g, shown=s, **kwargs) for i, (g, s) in enumerate(spec)]


class TestHeadline:
    def test_precision_counts_what_is_shown_recall_what_should_be(self) -> None:
        """Confondre les deux est l'erreur qui rendrait un filtre trop strict flatteur."""
        rows = _rows([("A", True), ("B", True), ("C", True), ("A", False), ("B", False)])
        head = headline(rows)
        assert head["final_shows"] == 3
        # 2 utiles montrés sur 3 montrés
        assert head["final_show_useful_precision"] == pytest.approx(66.67, abs=0.01)
        # 2 utiles montrés sur 4 utiles existants
        assert head["useful_recall"] == 50.0

    def test_a_filter_that_shows_nothing_has_perfect_silence_not_perfect_precision(self) -> None:
        """Zéro montré doit donner 0 % de précision, pas 100 % — sinon le gate ment."""
        head = headline(_rows([("A", False), ("B", False), ("D", False)]))
        assert head["final_shows"] == 0
        assert head["final_show_useful_precision"] == 0.0
        assert head["useful_recall"] == 0.0

    def test_a_critical_false_shown_is_counted(self) -> None:
        rows = [row(0, gold="D", shown=True, critical=True), row(1, gold="A", shown=True)]
        assert headline(rows)["critical_false_final_shows"] == 1

    def test_recall_is_reported_per_grade(self) -> None:
        rows = _rows([("A", True), ("A", False), ("B", True), ("B", True)])
        head = headline(rows)
        assert head["A_recall"] == 50.0
        assert head["B_recall"] == 100.0


class TestOrigin:
    def test_retention_and_promotion_are_reported_separately(self) -> None:
        """§41 — nettoyer les SHOW et récupérer des BORDERLINE sont deux effets distincts."""
        rows = [
            row(0, gold="A", shown=True, origin="show"),
            row(1, gold="C", shown=False, origin="show"),
            row(2, gold="B", shown=True, origin="borderline"),
            row(3, gold="D", shown=False, origin="borderline"),
        ]
        analysis = origin_analysis(rows)
        assert analysis["show"]["retained"] == 1
        assert analysis["show"]["hidden"] == 1
        assert analysis["borderline"]["promoted"] == 1
        assert analysis["borderline"]["useful_opportunities_recovered"] == 1

    def test_the_filter_effect_on_precision_is_visible(self) -> None:
        """Avant / après : c'est la seule façon de voir si le filtre sert à quelque chose."""
        rows = [
            row(0, gold="A", shown=True, origin="show"),
            row(1, gold="C", shown=False, origin="show"),
            row(2, gold="D", shown=False, origin="show"),
            row(3, gold="B", shown=True, origin="show"),
        ]
        analysis = origin_analysis(rows)["show"]
        assert analysis["useful_precision_before_verifier"] == 50.0
        assert analysis["useful_precision_after_verifier"] == 100.0


class TestIntegrity:
    def test_a_fact_reference_error_lowers_validity(self) -> None:
        rows = [
            row(0, errors=("supporting_fact_ids cite des faits inexistants : ['F99']",)),
            row(1),
        ]
        checks = integrity(rows)
        assert checks["fact_reference_errors"] == 1
        assert checks["fact_reference_validity"] == 50.0

    def test_forbidden_wording_is_counted_separately(self) -> None:
        rows = [row(0, errors=("commercial_reason contient une formulation de certitude : []",))]
        assert integrity(rows)["forbidden_wording"] == 1

    def test_an_api_failure_is_not_a_validation_failure(self) -> None:
        """§25 — les deux se corrigent différemment ; les confondre masque une panne."""
        rows = [
            row(0, shown=False, failure="api_rate_limit"),
            row(1, shown=False, failure="validation_failure"),
        ]
        checks = integrity(rows)
        assert checks["api_failures"] == 1
        assert checks["validation_failures"] == 1

    def test_an_unsupported_language_hide_is_visible(self) -> None:
        rows = [row(0, shown=False)]
        rows[0]["hide_reason"] = "unsupported_language"
        assert integrity(rows)["unsupported_language"] == 1


class TestTop20:
    def test_the_best_scores_are_the_ones_measured(self) -> None:
        rows = [row(i, gold="A" if i < 20 else "D", shown=True, score=100 - i) for i in range(30)]
        best = top20(rows)
        assert best["final_shows"] == 20
        assert best["useful_precision"] == 100.0

    def test_a_low_scoring_false_show_does_not_pollute_the_top(self) -> None:
        rows = [row(i, gold="A", shown=True, score=90) for i in range(20)]
        rows.append(row(99, gold="D", shown=True, score=10, critical=True))
        best = top20(rows)
        assert best["critical_false"] == 0
        assert best["useful_precision"] == 100.0


class TestShadowDiagnostics:
    def test_the_precision_recall_tradeoff_is_visible(self) -> None:
        """§43 — un filtre qui cache tout doit se voir, pas se déduire."""
        rows = [
            row(0, gold="A", shown=False),
            row(1, gold="B", shown=False),
            row(2, gold="C", shown=False),
            row(3, gold="D", shown=False),
            row(4, gold="A", shown=True),
        ]
        diagnostics = shadow_diagnostics(rows)
        assert diagnostics["useful_candidates_hidden"] == 2
        assert diagnostics["actionable_candidates_hidden"] == 1
        assert diagnostics["false_candidates_correctly_blocked"] == 1
        assert diagnostics["weak_candidates_correctly_blocked"] == 1


class TestFailureAnalysis:
    def test_every_false_final_show_is_named_and_attributed(self) -> None:
        """§42 — un faux montré sans explication ne se corrige pas."""
        rows = [row(0, gold="D", shown=True), row(1, gold="A", shown=True)]
        analysis = failure_analysis(rows)
        assert analysis["false_final_shows"] == 1
        case = analysis["cases"][0]
        assert case["gold_verdict"] == "D"
        assert case["gold_primary_failure_layer"] == "need graph"
        assert case["verifier_verdict"] == "approve"

    def test_a_weak_shown_signal_counts_as_a_failure_too(self) -> None:
        assert failure_analysis([row(0, gold="C", shown=True)])["false_final_shows"] == 1


class TestCost:
    def test_measured_and_projected_are_never_mixed(self) -> None:
        """§44 — une projection présentée comme une mesure est un mensonge budgétaire."""
        rows = _rows([("A", True)] * 10)
        report = cost_and_latency(rows, {"calls": 10, "input_tokens": 80000})
        assert report["MEASURED"]["cost_usd"] == pytest.approx(0.002)
        assert report["PROJECTED"]["cost_per_100_candidates"] == pytest.approx(0.02)
        assert report["PROJECTED"]["cost_per_1000_deterministic_candidates"] == pytest.approx(0.2)

    def test_cost_per_final_show_is_none_when_nothing_is_shown(self) -> None:
        rows = _rows([("A", False)] * 5)
        assert cost_and_latency(rows, {})["PROJECTED"]["cost_per_100_final_shows"] is None


class TestGates:
    def test_a_perfect_run_passes_the_dev_gates(self) -> None:
        rows = _rows([("A", True)] * 60 + [("D", False)] * 40)
        result = evaluate_gates(rows, gates=DEV_GATES)
        assert result["failed_gates"] == []
        assert result["passed"] is True

    def test_a_single_false_final_show_breaks_precision(self) -> None:
        """95 % sur 100 montrés : deux faux suffisent à faire tomber le gate DEV."""
        rows = _rows([("A", True)] * 94 + [("D", True)] * 6)
        result = evaluate_gates(rows, gates=DEV_GATES)
        assert "final_show_useful_precision" in result["failed_gates"]
        assert "false_final_show_rate" in result["failed_gates"]

    def test_a_filter_that_hides_too_much_fails_recall_and_volume(self) -> None:
        """§32 — un filtre parfait mais muet n'est pas un produit."""
        rows = _rows([("A", True)] * 10 + [("A", False)] * 90)
        result = evaluate_gates(rows, gates=DEV_GATES)
        assert "useful_recall" in result["failed_gates"]
        assert "final_show_rate" in result["failed_gates"]
        assert "final_show_useful_precision" not in result["failed_gates"]

    def test_a_critical_false_show_is_an_absolute_failure(self) -> None:
        rows = _rows([("A", True)] * 99) + [row(99, gold="D", shown=True, critical=True)]
        assert "critical_false_final_shows" in evaluate_gates(rows, gates=DEV_GATES)["failed_gates"]

    def test_the_final_gates_are_looser_than_the_dev_gates(self) -> None:
        """§32 vs §39 — on veut savoir avant de payer un corpus frais."""
        assert DEV_GATES["final_show_useful_precision"]["min"] == 95.0
        assert FINAL_GATES["final_show_useful_precision"]["min"] == 90.0
        assert DEV_GATES["weak_final_show_rate"]["max"] == 8.0
        assert FINAL_GATES["weak_final_show_rate"]["max"] == 10.0

    def test_the_final_gates_add_a_minimum_volume_and_rubric_agreement(self) -> None:
        assert "final_show_count" in FINAL_GATES
        assert "rubric_agreement_within_one" in FINAL_GATES
        assert "final_show_count" not in DEV_GATES

    def test_an_absent_measure_is_not_silently_passed(self) -> None:
        """Sans accord de rubrique fourni, le gate correspondant n'est pas inventé."""
        rows = _rows([("A", True)] * 60 + [("D", False)] * 40)
        result = evaluate_gates(rows, gates=FINAL_GATES, agreement_within_one=None)
        assert "rubric_agreement_within_one" not in result["gates"]
        result = evaluate_gates(rows, gates=FINAL_GATES, agreement_within_one=98.0)
        assert result["gates"]["rubric_agreement_within_one"]["passed"] is True
