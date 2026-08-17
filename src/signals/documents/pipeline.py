"""Le run à deux modèles : qui est appelé, quand, et ce que ça coûte.

SPEC-006R4 §14 borne la dépense, et la borne est structurelle plutôt que
paramétrable :

- **un** appel primaire par candidat (la retentative de schéma vit dans
  l'adaptateur, pas ici) ;
- le vérificateur n'est appelé que sur les candidats que le primaire a acceptés
  — sur DEV-3, 26 sur 100 ;
- aucune seconde passe de contexte élargi, aucun troisième avis.

Rien ici ne décide : la politique est dans `consensus.resolve`. Ce module
orchestre les appels, mesure leur latence, et fait remonter les pannes telles
quelles pour qu'elles restent des pannes.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from signals.documents.classification import SemanticClassification
from signals.documents.consensus import ConsensusDecision, VerifierResponse, resolve
from signals.documents.snapshot import CandidateSnapshot, excerpt_locates_in_blocks


class SnapshotClassifier(Protocol):
    """Le primaire : que dit cette phrase ?"""

    name: str
    version: str

    def classify_snapshot(self, snapshot: CandidateSnapshot) -> SemanticClassification | None: ...


class SnapshotVerifier(Protocol):
    """Le vérificateur : une seule question, fermée."""

    name: str
    version: str

    def verify(self, snapshot: CandidateSnapshot) -> VerifierResponse | None: ...


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return round(ordered[index], 3)


@dataclass
class PipelineRun:
    """Ce qu'un run a produit — décisions, appels, latences."""

    decisions: dict[int, ConsensusDecision] = field(default_factory=dict)
    primary_calls: int = 0
    verifier_calls: int = 0
    primary_latencies: list[float] = field(default_factory=list)
    verifier_latencies: list[float] = field(default_factory=list)

    @property
    def technical_failures(self) -> int:
        return sum(1 for d in self.decisions.values() if d.technical_failure)

    def latency_stats(self) -> dict[str, dict[str, float | None]]:
        """p50, p95 et maximum, par modèle. Un run vide ne rend pas de zéro."""
        return {
            "primary": {
                "p50": _percentile(self.primary_latencies, 0.50),
                "p95": _percentile(self.primary_latencies, 0.95),
                "max": round(max(self.primary_latencies), 3) if self.primary_latencies else None,
            },
            "verifier": {
                "p50": _percentile(self.verifier_latencies, 0.50),
                "p95": _percentile(self.verifier_latencies, 0.95),
                "max": round(max(self.verifier_latencies), 3) if self.verifier_latencies else None,
            },
        }


def _blocks_of(snapshot: CandidateSnapshot):
    """Les textes réellement disponibles pour vérifier une preuve.

    On confronte l'extrait au bloc courant et au span logique — jamais à une
    copie de l'extrait lui-même, qui rendrait la vérification tautologique.
    """
    from signals.documents.extract import TextBlock

    texts = [snapshot.current_block, snapshot.logical_span]
    return [
        TextBlock(locator=snapshot.source_locator, text=text, method="snapshot")
        for text in texts
        if text
    ]


def run_candidates(
    snapshots: Iterable[CandidateSnapshot],
    *,
    primary: SnapshotClassifier,
    verifier: SnapshotVerifier,
) -> PipelineRun:
    """Fait tourner la politique à deux modèles sur une liste de candidats figés."""
    run = PipelineRun()
    seen: set[int] = set()

    for snapshot in snapshots:
        if snapshot.candidate_id in seen:
            raise ValueError(f"candidate_id dupliqué : {snapshot.candidate_id}")
        seen.add(snapshot.candidate_id)

        started = time.perf_counter()
        classification = primary.classify_snapshot(snapshot)
        run.primary_latencies.append(time.perf_counter() - started)
        run.primary_calls += 1

        blocks = _blocks_of(snapshot)
        # Le texte confronté est le bloc source, pas l'extrait : c'est la
        # différence entre une preuve et une tautologie.
        source_text = snapshot.logical_span or snapshot.current_block

        # Le vérificateur ne part que si le primaire aurait accepté (§14).
        answer: VerifierResponse | None = None
        called = False
        if classification is not None:
            provisional = resolve(classification, None, source_text=source_text)
            if provisional.outcome != "rejected":
                called = True
                started = time.perf_counter()
                answer = verifier.verify(snapshot)
                run.verifier_latencies.append(time.perf_counter() - started)
                run.verifier_calls += 1

        evidence_complete = classification is not None and excerpt_locates_in_blocks(
            classification.source_excerpt, blocks
        )
        run.decisions[snapshot.candidate_id] = resolve(
            classification,
            answer,
            source_text=source_text,
            evidence_complete=evidence_complete,
            verifier_called=called,
        )

    return run
