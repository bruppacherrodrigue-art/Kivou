"""Deterministic recency, specificity and diversity selection."""

from __future__ import annotations

import math
from collections import Counter

from signals.phase_a_btp.contracts import ShowcaseSignal


def _rank(signal: ShowcaseSignal) -> tuple[int, int, int, str]:
    return (
        0 if signal.outbound_ready else 1,
        signal.age_days,
        -signal.specificity_score,
        signal.opportunity_key,
    )


def select_showcase(
    candidates: list[ShowcaseSignal] | tuple[ShowcaseSignal, ...], *, limit: int = 10
) -> tuple[ShowcaseSignal, ...]:
    """Select the best rows with bounded market, winner and specialty repetition."""

    if limit < 1:
        return ()
    specialty_cap = max(3, math.ceil(limit / 4))
    selected: list[ShowcaseSignal] = []
    seen_opportunities: set[str] = set()
    seen_notices: set[tuple[str, str]] = set()
    winner_counts: Counter[str] = Counter()
    specialty_counts: Counter[str] = Counter()
    ranked = sorted(candidates, key=_rank)
    for enforce_specialty_cap in (True, False):
        for candidate in ranked:
            notice = (
                candidate.official_facts.source_system,
                candidate.official_facts.source_notice_id,
            )
            if candidate.opportunity_key in seen_opportunities or notice in seen_notices:
                continue
            if winner_counts[candidate.official_facts.awardee] >= 2:
                continue
            if enforce_specialty_cap and specialty_counts[candidate.specialty] >= specialty_cap:
                continue
            selected.append(candidate)
            seen_opportunities.add(candidate.opportunity_key)
            seen_notices.add(notice)
            winner_counts[candidate.official_facts.awardee] += 1
            specialty_counts[candidate.specialty] += 1
            if len(selected) == limit:
                return tuple(selected)
    return tuple(selected)
