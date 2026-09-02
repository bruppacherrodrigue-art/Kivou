"""Deterministic recency, specificity and diversity selection."""

from __future__ import annotations

from collections import Counter, defaultdict

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
    """Select unique opportunities while preventing one trade or winner domination."""

    if limit < 1:
        return ()
    best_by_opportunity: dict[str, ShowcaseSignal] = {}
    for candidate in sorted(candidates, key=_rank):
        best_by_opportunity.setdefault(candidate.opportunity_key, candidate)

    groups: dict[str, list[ShowcaseSignal]] = defaultdict(list)
    for candidate in best_by_opportunity.values():
        groups[candidate.specialty].append(candidate)
    for values in groups.values():
        values.sort(key=_rank)

    specialty_order = sorted(groups, key=lambda value: _rank(groups[value][0]))
    selected: list[ShowcaseSignal] = []
    winner_counts: Counter[str] = Counter()
    seen_notices: set[tuple[str, str]] = set()
    cursors: dict[str, int] = {specialty: 0 for specialty in specialty_order}
    while len(selected) < limit:
        progressed = False
        for specialty in specialty_order:
            values = groups[specialty]
            cursor = cursors[specialty]
            candidate: ShowcaseSignal | None = None
            while cursor < len(values):
                current = values[cursor]
                cursor += 1
                notice = (
                    current.official_facts.source_system,
                    current.official_facts.source_notice_id,
                )
                if winner_counts[current.official_facts.awardee] >= 2:
                    continue
                if notice in seen_notices:
                    continue
                candidate = current
                break
            cursors[specialty] = cursor
            if candidate is None:
                continue
            notice = (
                candidate.official_facts.source_system,
                candidate.official_facts.source_notice_id,
            )
            selected.append(candidate)
            winner_counts[candidate.official_facts.awardee] += 1
            seen_notices.add(notice)
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    return tuple(selected)
