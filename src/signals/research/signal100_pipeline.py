"""Le pipeline gelé, exécuté tel quel sur le corpus SIGNAL-100 (SPEC-009 §11).

Rien n'est réglé ici : Contract Understanding, Need Graph et ICP Matching sont
appelés dans leur version committée, avec la bibliothèque d'ICPs de référence
gelée. SPEC-009 mesure, elle ne tune pas (§6, §46).

Aucun accès réseau : ce module relit un corpus déjà acquis. Il est donc
utilisable par la suite de tests normale (§58).
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
from collections.abc import Sequence
from typing import Any

from signals.domain.awards import ContractAward
from signals.domain.events import PublicEvent
from signals.matching import (
    MATCH_POLICY_VERSION,
    REFERENCE_ICPS,
    SCORE_POLICY_VERSION,
    MatchingEngine,
    ScoredSignalMatch,
    TargetICP,
)
from signals.needs import NeedGraphEngine
from signals.research.signal100 import PoolEntry, award_identity, signal_id
from signals.understanding import ContractUnderstandingEngine


@dataclasses.dataclass(frozen=True)
class AwardLot:
    """Un award-lot du corpus, rechargé en objets canoniques."""

    source: str
    notice: str
    event: PublicEvent
    award: ContractAward
    key: tuple

    @classmethod
    def from_row(cls, row: dict) -> AwardLot:
        return cls(
            source=row["source"],
            notice=row["notice"],
            event=PublicEvent.model_validate(row["event"]),
            award=ContractAward.model_validate(row["award"]),
            key=award_identity(row),
        )


@dataclasses.dataclass(frozen=True)
class LotRun:
    """Le passage complet d'un award-lot : compréhension, besoins, 8 matchs."""

    lot: AwardLot
    understanding: Any
    needs: Any
    matches: tuple[ScoredSignalMatch, ...]


def run_pipeline(
    rows: Sequence[dict],
    *,
    as_of: dt.date,
    icps: Sequence[TargetICP] = REFERENCE_ICPS,
) -> list[LotRun]:
    """Fait passer chaque award-lot dans le pipeline gelé contre tous les ICPs.

    L'ordre de sortie suit l'ordre du corpus : le déterminisme du banc ne doit
    dépendre ni d'un dictionnaire ni d'une date d'exécution.
    """
    understanding_engine = ContractUnderstandingEngine()
    need_engine = NeedGraphEngine()
    matching_engine = MatchingEngine()

    runs: list[LotRun] = []
    for row in rows:
        lot = AwardLot.from_row(row)
        understanding = understanding_engine.understand(lot.award, lot.event)
        needs = need_engine.derive(understanding)
        matches = tuple(
            matching_engine.match(understanding, needs, icp, as_of=as_of) for icp in icps
        )
        runs.append(LotRun(lot=lot, understanding=understanding, needs=needs, matches=matches))
    return runs


def has_identified_winner(lot: AwardLot) -> bool:
    """Un signal sans gagnant nommé n'a pas de « WHO » (§3, §57).

    Ce n'est pas un filtre de qualité commerciale : c'est la condition minimale
    pour qu'un snapshot puisse exister. Les award-lots concernés restent comptés
    dans le pool et dans le rapport du entonnoir.
    """
    return lot.award.winner_status == "identified" and bool(lot.award.awardee_parties)


def pool_entries(runs: Sequence[LotRun], *, decision: str = "show") -> list[PoolEntry]:
    """Les signaux d'une décision donnée, un `PoolEntry` par couple (award-lot, ICP)."""
    entries: list[PoolEntry] = []
    for run in runs:
        for match in run.matches:
            if match.decision != decision:
                continue
            entries.append(
                PoolEntry(
                    signal_id=signal_id(
                        run.lot.key, match.icp_id, MATCH_POLICY_VERSION, SCORE_POLICY_VERSION
                    ),
                    source=run.lot.source,
                    notice=run.lot.notice,
                    award_key=run.lot.key,
                    icp_id=match.icp_id,
                    normalized_score=match.normalized_score,
                    band=match.band,
                    confidence=match.confidence,
                    contract_type=run.understanding.contract_type.value,
                    sector=run.understanding.sector.value,
                    country=run.understanding.geography.buyer_country,
                    matched_needs=tuple(match.matched_needs),
                )
            )
    return entries


def funnel(runs: Sequence[LotRun]) -> dict[str, Any]:
    """L'entonnoir complet, décision par décision — le contexte des gates §12."""
    decisions: collections.Counter[str] = collections.Counter()
    for run in runs:
        for match in run.matches:
            decisions[match.decision] += 1
    lots_with_needs = sum(1 for run in runs if run.needs.needs)
    return {
        "award_lots": len(runs),
        "award_lots_with_identified_winner": sum(1 for r in runs if has_identified_winner(r.lot)),
        "award_lots_with_at_least_one_need": lots_with_needs,
        "pairs_evaluated": sum(len(run.matches) for run in runs),
        "decisions": dict(decisions),
        "source_mode": sorted({run.needs.source_mode for run in runs}),
    }
