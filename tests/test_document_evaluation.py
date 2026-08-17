"""SPEC-006R4 §15/§16 — ce que la mesure compte, et ce que le gate exige.

Le piège d'un système à trois états est de tout mettre en revue : la précision
devient parfaite et le produit inutile. Ces tests fixent les dénominateurs pour
que ce cas se voie.
"""

from __future__ import annotations

import pytest

from signals.documents.consensus import ConsensusDecision
from signals.documents.evaluation import GATE_THRESHOLDS, evaluate_gate, score


def outcome(
    state: str, *, confidence: str = "medium", technical: bool = False
) -> ConsensusDecision:
    return ConsensusDecision(
        outcome=state,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        technical_failure=technical,
    )


class TestDenominators:
    def test_the_gold_count_is_the_number_of_real_requirements(self) -> None:
        metrics = score(
            decisions={1: outcome("auto_accepted"), 2: outcome("rejected")},
            gold={1: True, 2: False},
        )
        assert metrics.gold_execution_requirements == 1

    def test_a_corpus_without_any_requirement_yields_no_recall(self) -> None:
        """Diviser par zéro n'est pas un score de 100 %."""
        metrics = score(decisions={1: outcome("rejected")}, gold={1: False})
        assert metrics.auto_accepted_recall is None
        assert metrics.candidate_recall is None

    def test_a_decision_without_a_gold_label_is_refused(self) -> None:
        with pytest.raises(KeyError):
            score(decisions={1: outcome("auto_accepted")}, gold={})


class TestAutoAcceptedMetrics:
    def test_precision_counts_only_auto_accepted(self) -> None:
        """Un candidat en revue n'entre pas au dénominateur de la précision."""
        metrics = score(
            decisions={
                1: outcome("auto_accepted"),
                2: outcome("auto_accepted"),
                3: outcome("review_required"),
            },
            gold={1: True, 2: False, 3: False},
        )
        assert metrics.auto_accepted == 2
        assert metrics.true_auto_accepted == 1
        assert metrics.false_auto_accepted == 1
        assert metrics.auto_accepted_precision == pytest.approx(0.5)

    def test_recall_is_measured_against_the_gold_requirements(self) -> None:
        metrics = score(
            decisions={
                1: outcome("auto_accepted"),
                2: outcome("review_required"),
                3: outcome("rejected"),
            },
            gold={1: True, 2: True, 3: True},
        )
        assert metrics.auto_accepted_recall == pytest.approx(1 / 3)

    def test_a_false_auto_accept_in_high_confidence_is_counted_apart(self) -> None:
        metrics = score(
            decisions={
                1: outcome("auto_accepted", confidence="high"),
                2: outcome("auto_accepted", confidence="medium"),
            },
            gold={1: False, 2: False},
        )
        assert metrics.false_auto_accepted == 2
        assert metrics.high_confidence_false_auto_accepted == 1


class TestReviewIsNotFree:
    def test_requirements_kept_for_review_are_counted(self) -> None:
        metrics = score(
            decisions={1: outcome("review_required"), 2: outcome("review_required")},
            gold={1: True, 2: False},
        )
        assert metrics.review_required == 2
        assert metrics.true_retained_for_review == 1
        assert metrics.false_retained_for_review == 1

    def test_candidate_recall_credits_review_but_precision_does_not(self) -> None:
        """C'est ce qui distingue « conservé » de « affirmé »."""
        metrics = score(
            decisions={1: outcome("auto_accepted"), 2: outcome("review_required")},
            gold={1: True, 2: True},
        )
        assert metrics.candidate_recall == pytest.approx(1.0)
        assert metrics.auto_accepted_recall == pytest.approx(0.5)

    def test_a_system_that_reviews_everything_has_no_auto_recall(self) -> None:
        metrics = score(
            decisions={1: outcome("review_required"), 2: outcome("review_required")},
            gold={1: True, 2: True},
        )
        assert metrics.candidate_recall == pytest.approx(1.0)
        assert metrics.auto_accepted_recall == pytest.approx(0.0)


class TestGate:
    def perfect(self) -> dict[int, ConsensusDecision]:
        return {i: outcome("auto_accepted", confidence="high") for i in range(1, 11)}

    def test_a_perfect_run_passes(self) -> None:
        metrics = score(decisions=self.perfect(), gold=dict.fromkeys(range(1, 11), True))
        assert evaluate_gate(metrics).passed is True

    def test_one_high_confidence_false_accept_fails_the_gate(self) -> None:
        decisions = self.perfect()
        gold = dict.fromkeys(range(1, 11), True)
        gold[10] = False
        result = evaluate_gate(score(decisions=decisions, gold=gold))
        assert result.passed is False
        assert "high_confidence_false_auto_accepted" in result.failures

    def test_reviewing_everything_fails_the_auto_recall_floor(self) -> None:
        """Précision parfaite, produit inutile : le gate doit le voir."""
        metrics = score(
            decisions={i: outcome("review_required") for i in range(1, 11)},
            gold=dict.fromkeys(range(1, 11), True),
        )
        result = evaluate_gate(metrics)
        assert result.passed is False
        assert "auto_accepted_recall" in result.failures

    def test_losing_too_many_requirements_fails_candidate_recall(self) -> None:
        decisions = {i: outcome("rejected") for i in range(1, 11)}
        decisions[1] = outcome("auto_accepted", confidence="high")
        result = evaluate_gate(score(decisions=decisions, gold=dict.fromkeys(range(1, 11), True)))
        assert result.passed is False
        assert "candidate_recall" in result.failures

    def test_incomplete_evidence_coverage_fails_the_gate(self) -> None:
        metrics = score(
            decisions=self.perfect(),
            gold=dict.fromkeys(range(1, 11), True),
            evidence_exact={i: i != 3 for i in range(1, 11)},
        )
        result = evaluate_gate(metrics)
        assert result.passed is False
        assert "evidence_coverage" in result.failures

    def test_an_invented_excerpt_fails_the_gate(self) -> None:
        metrics = score(
            decisions=self.perfect(),
            gold=dict.fromkeys(range(1, 11), True),
            excerpts_invented=1,
        )
        result = evaluate_gate(metrics).failures
        assert "excerpts_invented" in result

    def test_the_thresholds_are_the_published_ones(self) -> None:
        assert GATE_THRESHOLDS["auto_accepted_precision"] == 0.95
        assert GATE_THRESHOLDS["candidate_recall"] == 0.85
        assert GATE_THRESHOLDS["auto_accepted_recall"] == 0.60
