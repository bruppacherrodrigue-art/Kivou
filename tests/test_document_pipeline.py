"""SPEC-006R4 §14 — la politique d'appel, et ce qu'elle refuse de dépenser.

Le vérificateur ne coûte que sur la minorité de candidats que le primaire a
acceptés. Ces tests fixent ce budget d'appels et vérifient qu'une panne de
transport ne devient jamais un verdict négatif.
"""

from __future__ import annotations

import pytest

from signals.documents.classification import SemanticClassification
from signals.documents.consensus import VerifierResponse
from signals.documents.pipeline import PipelineRun, run_candidates
from signals.documents.snapshot import CandidateSnapshot

BLOCK = (
    "Izvajalec mora naročniku mesečno predložiti poročilo o opravljenih delih "
    "v elektronski obliki, in sicer do petega dne v mesecu."
)
EXCERPT = "Izvajalec mora naročniku mesečno predložiti poročilo o opravljenih delih"


def snap(candidate_id: int, excerpt: str = EXCERPT) -> CandidateSnapshot:
    return CandidateSnapshot(
        candidate_id=candidate_id,
        award_reference="999999-2026",
        document_hash="b" * 64,
        document_name="pogodba.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        source_locator=f"paragraphe {candidate_id}",
        heading="13. člen",
        previous_block="Pogodbene obveznosti",
        current_block=BLOCK,
        next_block="Naročnik pregleda poročilo.",
        logical_span=BLOCK,
        source_block_locators=(f"paragraphe {candidate_id}",),
        excerpt=excerpt,
        language="sl",
    )


class StubPrimary:
    """Un classifieur primaire scriptable, qui compte ses appels."""

    name = "stub-primary"
    version = "v1"

    def __init__(self, replies: dict[int, SemanticClassification | None]) -> None:
        self.replies = replies
        self.calls: list[int] = []

    def classify_snapshot(self, snapshot: CandidateSnapshot):
        self.calls.append(snapshot.candidate_id)
        return self.replies.get(snapshot.candidate_id)


class StubVerifier:
    name = "stub-verifier"
    version = "v1"

    def __init__(self, replies: dict[int, VerifierResponse | None]) -> None:
        self.replies = replies
        self.calls: list[int] = []

    def verify(self, snapshot: CandidateSnapshot):
        self.calls.append(snapshot.candidate_id)
        return self.replies.get(snapshot.candidate_id)


def accepting(excerpt: str = EXCERPT) -> SemanticClassification:
    return SemanticClassification(
        phase="execution",
        obligated_actor="contractor",
        modality="mandatory",
        requirement_type="documentation_obligation",
        context_status="sufficient",
        source_excerpt=excerpt,
        confidence="high",
    )


def rejecting() -> SemanticClassification:
    return SemanticClassification(
        phase="procurement",
        obligated_actor="bidder",
        modality="mandatory",
        requirement_type="other",
        context_status="sufficient",
        source_excerpt=EXCERPT,
        confidence="high",
    )


def confirming() -> VerifierResponse:
    return VerifierResponse(
        verdict="confirm",
        reason="execution_contractor",
        source_excerpt=EXCERPT,
        confidence="high",
    )


class TestTheVerifierIsCalledSparingly:
    def test_the_verifier_is_not_called_when_the_primary_rejects(self) -> None:
        primary = StubPrimary({1: rejecting()})
        verifier = StubVerifier({})
        run_candidates([snap(1)], primary=primary, verifier=verifier)
        assert verifier.calls == []

    def test_the_verifier_is_called_only_on_accepted_candidates(self) -> None:
        primary = StubPrimary({1: accepting(), 2: rejecting(), 3: accepting()})
        verifier = StubVerifier({1: confirming(), 3: confirming()})
        run_candidates([snap(1), snap(2), snap(3)], primary=primary, verifier=verifier)
        assert verifier.calls == [1, 3]

    def test_the_primary_is_called_once_per_candidate(self) -> None:
        """Aucune seconde passe de contexte : §14 l'interdit."""
        primary = StubPrimary({1: accepting(), 2: accepting()})
        verifier = StubVerifier({1: confirming(), 2: confirming()})
        run_candidates([snap(1), snap(2)], primary=primary, verifier=verifier)
        assert primary.calls == [1, 2]

    def test_no_third_opinion_is_ever_requested(self) -> None:
        primary = StubPrimary({1: accepting()})
        verifier = StubVerifier(
            {
                1: VerifierResponse(
                    verdict="uncertain",
                    reason="fragment",
                    source_excerpt=EXCERPT,
                    confidence="low",
                )
            }
        )
        run_candidates([snap(1)], primary=primary, verifier=verifier)
        assert verifier.calls == [1]


class TestTransportFailuresAreNotVerdicts:
    def test_a_primary_failure_becomes_review_not_rejected(self) -> None:
        run = run_candidates([snap(1)], primary=StubPrimary({1: None}), verifier=StubVerifier({}))
        assert run.decisions[1].outcome == "review_required"
        assert run.decisions[1].technical_failure is True

    def test_a_verifier_failure_becomes_review_not_rejected(self) -> None:
        run = run_candidates(
            [snap(1)], primary=StubPrimary({1: accepting()}), verifier=StubVerifier({1: None})
        )
        assert run.decisions[1].outcome == "review_required"
        assert run.decisions[1].technical_failure is True

    def test_technical_failures_are_counted(self) -> None:
        run = run_candidates(
            [snap(1), snap(2)],
            primary=StubPrimary({1: None, 2: accepting()}),
            verifier=StubVerifier({2: confirming()}),
        )
        assert run.technical_failures == 1


class TestEvidenceIsCheckedAgainstTheSnapshotBlocks:
    def test_an_excerpt_absent_from_the_blocks_is_never_auto_accepted(self) -> None:
        """La garantie que DEV-3 ne pouvait pas offrir, appliquée ici."""
        invented = "Le titulaire doit repeindre la Lune."
        primary = StubPrimary({1: accepting(invented)})
        run = run_candidates([snap(1)], primary=primary, verifier=StubVerifier({1: confirming()}))
        assert run.decisions[1].outcome != "auto_accepted"

    def test_an_exact_excerpt_is_auto_accepted(self) -> None:
        run = run_candidates(
            [snap(1)],
            primary=StubPrimary({1: accepting()}),
            verifier=StubVerifier({1: confirming()}),
        )
        assert run.decisions[1].outcome == "auto_accepted"


class TestTheRunReportsItsCost:
    def test_it_records_latency_per_model(self) -> None:
        run = run_candidates(
            [snap(1)],
            primary=StubPrimary({1: accepting()}),
            verifier=StubVerifier({1: confirming()}),
        )
        assert run.primary_latencies
        assert run.verifier_latencies

    def test_it_reports_percentiles(self) -> None:
        primary = StubPrimary({i: accepting() for i in range(1, 6)})
        verifier = StubVerifier({i: confirming() for i in range(1, 6)})
        run = run_candidates([snap(i) for i in range(1, 6)], primary=primary, verifier=verifier)
        stats = run.latency_stats()
        assert set(stats) == {"primary", "verifier"}
        for model in stats.values():
            assert {"p50", "p95", "max"} <= set(model)

    def test_the_verifier_call_count_is_lower_than_the_primary(self) -> None:
        primary = StubPrimary({1: accepting(), 2: rejecting(), 3: rejecting()})
        run = run_candidates(
            [snap(1), snap(2), snap(3)],
            primary=primary,
            verifier=StubVerifier({1: confirming()}),
        )
        assert run.primary_calls == 3
        assert run.verifier_calls == 1

    def test_an_empty_run_reports_no_percentile(self) -> None:
        run = PipelineRun()
        assert run.latency_stats()["primary"]["p50"] is None


class TestOrderIsPreserved:
    def test_every_candidate_gets_exactly_one_decision(self) -> None:
        snaps = [snap(i) for i in range(1, 8)]
        primary = StubPrimary({i: rejecting() for i in range(1, 8)})
        run = run_candidates(snaps, primary=primary, verifier=StubVerifier({}))
        assert sorted(run.decisions) == list(range(1, 8))

    def test_a_duplicate_candidate_id_is_refused(self) -> None:
        with pytest.raises(ValueError, match="dupliqué"):
            run_candidates(
                [snap(1), snap(1)],
                primary=StubPrimary({1: rejecting()}),
                verifier=StubVerifier({}),
            )
