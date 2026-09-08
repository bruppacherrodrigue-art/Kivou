"""L'adjudication commerciale et ses gates — la mécanique, pas les verdicts.

SPEC-009 §30, §31, §33–§45. Ces tests garantissent que le banc ne peut pas se
compléter au jugé : vocabulaire fermé, arbitrage obligatoire là où §30 l'exige,
résolution déclarée à l'avance, et gates qui échouent quand ils doivent échouer.

Aucun accès réseau, aucune fixture : tout est synthétique.
"""

from __future__ import annotations

import pytest

from signals.research.signal100_adjudication import (
    AdjudicationError,
    assemble,
    needs_arbitration,
    resolve,
    rubric_consistency,
    validate_review,
)
from signals.research.signal100_metrics import evaluate_gates, headline, safety


def review(signal_id: str = "sig-1", verdict: str = "B", **overrides: object) -> dict:
    """Une revue par défaut cohérente ; les tests n'écrasent que ce qui compte."""
    base = {
        "signal_id": signal_id,
        "factual_integrity": "pass",
        "need": "credible",
        "icp_fit": "strong_fit",
        "actionability": "worth_investigating",
        "specificity": "specific",
        "timing": "acceptable",
        "proof": "adequate",
        "verdict": verdict,
        "critical_false_signal": False,
        "critical_overclaiming": False,
        "primary_failure_layer": None,
        "secondary_failure_layers": [],
        "note": "note",
    }
    base.update(overrides)
    return base


def snapshot(signal_id: str = "sig-1", score: int = 80, tercile: str = "top") -> dict:
    return {
        "signal_id": signal_id,
        "source": "ted",
        "icp": {"icp_id": "icp-a"},
        "understanding": {"contract_type": {"value": "construction"}},
        "matched_needs": ["workforce_capacity"],
        "score": {"normalized_score": score, "band": "strong", "confidence": "medium"},
        "tercile": tercile,
    }


class TestClosedVocabulary:
    def test_a_grade_outside_the_rubric_is_refused(self) -> None:
        """Une nuance inventée par un adjudicateur n'entre pas dans le gold."""
        with pytest.raises(AdjudicationError, match="hors rubrique"):
            validate_review(review(need="quite_credible"), role="reviewer_a")

    def test_a_missing_field_is_refused(self) -> None:
        broken = review()
        del broken["proof"]
        with pytest.raises(AdjudicationError, match="champs manquants"):
            validate_review(broken, role="reviewer_a")

    def test_an_unknown_failure_layer_is_refused(self) -> None:
        """§45 — les couches sont un vocabulaire fermé, pas du texte libre."""
        with pytest.raises(AdjudicationError, match="couche primaire inconnue"):
            validate_review(review(primary_failure_layer="le moteur"), role="reviewer_a")


class TestRubricConsistency:
    def test_a_generic_signal_cannot_be_actionable(self) -> None:
        """§22 — la règle est nommée dans la rubrique, elle doit être détectée."""
        problems = rubric_consistency(review(specificity="generic", actionability="actionable"))
        assert any("§22" in problem for problem in problems)

    def test_a_hard_trigger_without_a_d_verdict_is_flagged(self) -> None:
        """§25 — un besoin contredit impose `D`, sinon la rubrique est mal lue."""
        problems = rubric_consistency(review(need="contradicted", verdict="C"))
        assert any("§25" in problem for problem in problems)

    def test_a_critical_false_signal_without_d_is_flagged(self) -> None:
        """§26 — un critical false signal implique toujours `D`."""
        problems = rubric_consistency(review(critical_false_signal=True, verdict="B"))
        assert any("§26" in problem for problem in problems)

    def test_an_unearned_a_verdict_is_flagged(self) -> None:
        """§25 — `A` exige ses six conditions, pas seulement un bon ressenti."""
        problems = rubric_consistency(
            review(verdict="A", actionability="worth_investigating", need="plausible_but_weak")
        )
        assert any("conditions minimales" in problem for problem in problems)

    def test_a_coherent_review_raises_nothing(self) -> None:
        assert rubric_consistency(review(verdict="B")) == []


class TestArbitration:
    def test_two_adjacent_verdicts_need_no_arbitration(self) -> None:
        assert not needs_arbitration(review(verdict="A"), review(verdict="B"))

    def test_a_gap_of_two_grades_triggers_arbitration(self) -> None:
        """§30 — au-delà d'un niveau d'écart, un tiers tranche."""
        assert needs_arbitration(review(verdict="A"), review(verdict="C"))

    def test_any_d_triggers_arbitration_even_when_adjacent(self) -> None:
        """§30 — un `D` d'un seul côté suffit : c'est le verdict le plus lourd."""
        assert needs_arbitration(review(verdict="C"), review(verdict="D"))

    def test_agreement_on_d_still_triggers_arbitration(self) -> None:
        assert needs_arbitration(review(verdict="D"), review(verdict="D"))


class TestResolution:
    def test_without_arbitration_the_most_severe_verdict_wins(self) -> None:
        """Règle déclarée avant adjudication : un banc precision-first ne se flatte pas."""
        resolved = resolve(review(verdict="A"), review(verdict="B"), None)
        assert resolved["final_verdict"] == "B"
        assert resolved["final_source"] == "most_severe"

    def test_arbitration_overrides_both_reviews(self) -> None:
        """§30 — l'arbitre a vu la preuve brute sans les verdicts précédents."""
        resolved = resolve(
            review(verdict="D", critical_false_signal=True),
            review(verdict="C"),
            review(verdict="B"),
        )
        assert resolved["final_verdict"] == "B"
        assert resolved["final_source"] == "arbitration"
        assert resolved["critical_false_signal"] is False

    def test_assemble_refuses_to_complete_a_missing_arbitration(self) -> None:
        """§30 — un désaccord non arbitré ne devient pas un verdict par défaut."""
        with pytest.raises(AdjudicationError, match="arbitrage requis"):
            assemble(
                [snapshot()],
                {"sig-1": review(verdict="A")},
                {"sig-1": review(verdict="D")},
                {},
            )

    def test_assemble_refuses_a_missing_review(self) -> None:
        with pytest.raises(AdjudicationError, match="revue manquante"):
            assemble([snapshot()], {"sig-1": review()}, {}, {})

    def test_assemble_keeps_both_reviews_and_the_engine_facts(self) -> None:
        """Le gold garde la trace des deux perspectives ET du score jamais montré."""
        records = assemble(
            [snapshot(score=77)],
            {"sig-1": review(verdict="A")},
            {"sig-1": review(verdict="B")},
        )
        assert len(records) == 1
        record = records[0]
        assert record["review_a"]["verdict"] == "A"
        assert record["review_b"]["verdict"] == "B"
        assert record["final_verdict"] == "B"
        assert record["normalized_score"] == 77
        assert record["arbitration"] is None


def _gold(verdicts: str, **flags: object) -> list[dict]:
    """Construit un gold synthétique à partir d'une chaîne comme `"AAB..."`."""
    records = []
    for index, verdict in enumerate(verdicts):
        reviewed = review(f"sig-{index}", verdict=verdict)
        record = {
            "signal_id": f"sig-{index}",
            "source": "ted",
            "icp_id": "icp-a",
            "contract_type": "construction",
            "matched_needs": ["workforce_capacity"],
            "normalized_score": 90 - index,
            "band": "strong",
            "confidence": "medium",
            "tercile": ("top", "middle", "bottom")[index % 3],
            "review_a": reviewed,
            "review_b": reviewed,
            "arbitration": None,
            "final_verdict": verdict,
            "final_dimensions": {
                "factual_integrity": "pass",
                "need": "credible",
                "icp_fit": "strong_fit",
                "actionability": "actionable",
                "specificity": "specific",
                "timing": "acceptable",
                "proof": "adequate",
            },
            "critical_false_signal": False,
            "critical_overclaiming": False,
            "primary_failure_layer": None,
            "secondary_failure_layers": [],
            "final_note": "note",
        }
        record.update(flags)
        records.append(record)
    return records


class TestGates:
    def test_a_perfect_bench_passes_every_gate(self) -> None:
        result = evaluate_gates(_gold("A" * 100))
        assert result["failed_gates"] == []
        assert result["verdict"] == "SPEC-009 DONE"

    def test_a_low_actionable_rate_fails_its_own_gate(self) -> None:
        """§35 — « pas faux » ne suffit pas : 60 % doivent être directement actionnables."""
        result = evaluate_gates(_gold("A" * 50 + "B" * 50))
        assert "actionable_rate" in result["failed_gates"]
        assert "useful_precision" not in result["failed_gates"]
        assert result["verdict"] == "SPEC-009 NOT DONE"

    def test_a_single_critical_false_signal_fails_the_absolute_gate(self) -> None:
        """§36 — zéro veut dire zéro."""
        records = _gold("A" * 100)
        records[0]["critical_false_signal"] = True
        assert "critical_false_signals" in evaluate_gates(records)["failed_gates"]

    def test_three_false_signals_break_the_two_percent_ceiling(self) -> None:
        """§36 — D <= 2 %."""
        result = evaluate_gates(_gold("A" * 97 + "D" * 3))
        assert "false_rate" in result["failed_gates"]

    def test_eleven_weak_signals_break_the_ten_percent_ceiling(self) -> None:
        """§37 — un feed de signaux vrais mais vagues n'est pas acceptable."""
        assert "weak_rate" in evaluate_gates(_gold("A" * 89 + "C" * 11))["failed_gates"]

    def test_a_bench_that_is_not_one_hundred_signals_is_never_done(self) -> None:
        """§59 — SIGNALS = 100 est une condition, pas une approximation."""
        result = evaluate_gates(_gold("A" * 99))
        assert result["signal_count_is_100"] is False
        assert result["verdict"] == "SPEC-009 NOT DONE"

    def test_safety_counts_report_each_dimension_failure(self) -> None:
        records = _gold("A" * 100)
        records[0]["final_dimensions"]["timing"] = "wrong"
        records[1]["final_dimensions"]["proof"] = "insufficient"
        records[2]["final_dimensions"]["factual_integrity"] = "critical_failure"
        counts = safety(records)
        assert counts["timing_errors"] == 1
        assert counts["proof_failures"] == 1
        assert counts["factual_integrity_failures"] == 1
        assert counts["proof_coverage"] == 99.0

    def test_headline_rates_sum_to_one_hundred(self) -> None:
        head = headline(_gold("A" * 40 + "B" * 40 + "C" * 15 + "D" * 5))
        total = (
            head["actionable_rate"]
            + head["weak_rate"]
            + head["false_rate"]
            + (head["useful_precision"] - head["actionable_rate"])
        )
        assert total == pytest.approx(100.0)
