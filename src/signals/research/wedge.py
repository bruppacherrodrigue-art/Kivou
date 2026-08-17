"""Décomposition du feed par client et sélection de wedge (SPEC-009B).

SPEC-009 mesurait un banc global : chaque award-lot était mis en concurrence
entre les huit ICPs et un seul survivait. C'est une bonne façon de mesurer un
moteur, et une mauvaise façon de représenter un SaaS — dans Kivou, un client a
son ICP et son feed, et le feed d'un client n'est pas amputé parce qu'un autre
client aurait mieux « gagné » le même marché.

Ce module reconstruit donc les huit feeds **séparément**, sans aucune
déduplication cross-ICP (§4). À l'intérieur d'un même ICP, les règles
anti-duplication de SPEC-009 restent en vigueur : un signal par award-lot, deux
award-lots par notice au maximum.

Il ne modifie aucun moteur (§6) et fonctionne hors ligne à partir des fixtures
gelées (§5).
"""

from __future__ import annotations

import collections
import dataclasses
from collections.abc import Sequence
from typing import Any

#: §11 — combien de signaux d'un feed sont adjugés, selon son volume naturel.
FULL_REVIEW_CEILING = 40
MIN_FOR_RATE = 20
MIN_FOR_LOW_SAMPLE = 10

#: §11 — répartition déterministe quand le feed dépasse le plafond.
STRATUM_QUOTAS = {"top": 14, "middle": 13, "bottom": 13}

#: §34 — les gates d'un wedge GREEN.
GREEN = {
    "reviewed": 20,
    "useful_precision": 85.0,
    "false_rate": 5.0,
    "critical_false": 0,
    "factual_integrity": 100.0,
    "proof_coverage": 100.0,
    "top10_useful_precision": 90.0,
    "natural_show_volume": 15,
}

#: §36 — les gates d'un wedge AMBER.
AMBER = {"reviewed": 15, "useful_precision_min": 75.0, "false_rate": 7.5, "critical_false": 0}

#: §21 — seuils de publication d'une intersection.
INTERSECTION_PUBLISH = 8
INTERSECTION_INDICATIVE = 5


@dataclasses.dataclass(frozen=True)
class FeedEntry:
    """Un couple award-lot × ICP tel qu'il apparaîtrait dans le feed d'un client."""

    signal_id: str
    icp_id: str
    award_key: tuple
    source: str
    notice: str
    decision: str
    normalized_score: int
    band: str
    confidence: str
    contract_type: str
    sector: str
    country: str | None
    matched_needs: tuple[str, ...]
    has_amount: bool
    has_operational_timing: bool

    @property
    def pair_id(self) -> tuple:
        """L'identité exacte d'un couple, pour réutiliser un gold existant (§16)."""
        return (*self.award_key, self.icp_id)


def build_feeds(runs: Sequence[Any]) -> dict[str, list[FeedEntry]]:
    """Les huit feeds clients, sans aucune concurrence entre ICPs (§4, §7).

    Chaque `LotRun` porte déjà un match par ICP : il n'y a donc rien à
    dédupliquer entre ICPs, seulement à ne pas fusionner. C'est précisément ce
    que SPEC-009 faisait et que cette SPEC défait.
    """
    from signals.research.signal100 import signal_id

    feeds: dict[str, list[FeedEntry]] = collections.defaultdict(list)
    for run in runs:
        understanding = run.understanding
        timing = understanding.timing
        has_timing = bool(
            timing.contract_start_date or timing.contract_end_date or timing.award_date
        )
        has_amount = "amount" in understanding.facts
        for match in run.matches:
            feeds[match.icp_id].append(
                FeedEntry(
                    signal_id=signal_id(
                        run.lot.key,
                        match.icp_id,
                        match.match_policy_version,
                        match.score_policy_version,
                    ),
                    icp_id=match.icp_id,
                    award_key=run.lot.key,
                    source=run.lot.source,
                    notice=run.lot.notice,
                    decision=match.decision,
                    normalized_score=match.normalized_score,
                    band=match.band,
                    confidence=match.confidence,
                    contract_type=understanding.contract_type.value,
                    sector=understanding.sector.value,
                    country=understanding.geography.buyer_country,
                    matched_needs=tuple(match.matched_needs),
                    has_amount=has_amount,
                    has_operational_timing=has_timing,
                )
            )
    return dict(feeds)


def cap_per_notice(entries: Sequence[FeedEntry], *, cap: int = 2) -> list[FeedEntry]:
    """Au plus `cap` award-lots par notice, à l'intérieur d'un même feed (§4).

    Déterministe : score décroissant puis `signal_id`. La règle est celle de
    SPEC-009 §8, appliquée par feed et non plus globalement.
    """
    kept: list[FeedEntry] = []
    seen: collections.Counter = collections.Counter()
    for entry in sorted(entries, key=lambda e: (-e.normalized_score, e.signal_id)):
        if seen[(entry.source, entry.notice)] >= cap:
            continue
        seen[(entry.source, entry.notice)] += 1
        kept.append(entry)
    return kept


def feed_profile(entries: Sequence[FeedEntry]) -> dict[str, Any]:
    """Le portrait d'un feed client (§7), toutes décisions confondues."""
    decisions = collections.Counter(e.decision for e in entries)
    shows = [e for e in entries if e.decision == "show"]
    scores = sorted(e.normalized_score for e in shows)
    return {
        "pairs_total": len(entries),
        "show": decisions["show"],
        "borderline": decisions["borderline"],
        "exclude": decisions["exclude"],
        "insufficient_data": decisions["insufficient_data"],
        "unique_award_lots_shown": len({e.award_key for e in shows}),
        "source": dict(collections.Counter(e.source for e in shows)),
        "countries": dict(collections.Counter(e.country for e in shows if e.country).most_common()),
        "contract_types": dict(collections.Counter(e.contract_type for e in shows).most_common()),
        "need_categories": dict(
            collections.Counter(need for e in shows for need in e.matched_needs).most_common()
        ),
        "score_distribution": dict(sorted(collections.Counter(scores).items())),
        "score_median": scores[len(scores) // 2] if scores else None,
        "known_amount_coverage": _pct(sum(1 for e in shows if e.has_amount), len(shows)),
        "known_timing_coverage": _pct(
            sum(1 for e in shows if e.has_operational_timing), len(shows)
        ),
    }


def _pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


# ─── Effet de la concurrence entre ICPs (§8) ────────────────────────────────────


def cross_icp_dedup_impact(
    feeds: dict[str, list[FeedEntry]], signal100_ids: set[str]
) -> dict[str, Any]:
    """Ce que la règle « meilleur ICP gagne » a coûté à chaque feed.

    C'est la mesure décisive de SPEC-009B : elle dit si le mauvais résultat
    global venait pour partie du fait que deux ICPs très larges écrasaient les
    ICPs spécialisés, plutôt que d'un défaut propre à ces derniers.
    """
    impact = {}
    for icp_id, entries in sorted(feeds.items()):
        raw = [e for e in entries if e.decision == "show"]
        survivors = [e for e in raw if e.signal_id in signal100_ids]
        impact[icp_id] = {
            "raw_show_pairs": len(raw),
            "surviving_signal100": len(survivors),
            "survival_rate": _pct(len(survivors), len(raw)),
        }
    return impact


# ─── Échantillonnage (§11, §12) ─────────────────────────────────────────────────


def strata(entries: Sequence[FeedEntry]) -> dict[str, list[FeedEntry]]:
    """Trois zones de score par rang, comme SPEC-009 §14."""
    ordered = sorted(entries, key=lambda e: (-e.normalized_score, e.signal_id))
    size = len(ordered)
    first, second = size // 3, 2 * size // 3
    return {"top": ordered[:first], "middle": ordered[first:second], "bottom": ordered[second:]}


def sample_for_review(entries: Sequence[FeedEntry]) -> tuple[list[FeedEntry], str]:
    """L'échantillon d'un feed et son statut (§11), aveugle à toute qualité (§12).

    La sélection n'utilise que l'ICP, la zone de score, la source et le
    `signal_id` : ni gold, ni verdict LLM, ni commentaire de relecteur n'entrent
    dans la décision. C'est ce qui interdit le cherry-picking.
    """
    shows = cap_per_notice([e for e in entries if e.decision == "show"])
    count = len(shows)
    if count < MIN_FOR_LOW_SAMPLE:
        return [], "INSUFFICIENT SAMPLE"
    if count <= FULL_REVIEW_CEILING:
        status = "OK" if count >= MIN_FOR_RATE else "LOW SAMPLE"
        return sorted(shows, key=lambda e: e.signal_id), status

    zones = strata(shows)
    picked: list[FeedEntry] = []
    for name, quota in STRATUM_QUOTAS.items():
        zone = sorted(zones[name], key=lambda e: e.signal_id)
        picked.extend(zone[:quota])
    # Une zone plus petite que son quota est complétée par les suivantes, dans
    # un ordre stable : le banc doit faire exactement 40, sans hasard.
    if len(picked) < FULL_REVIEW_CEILING:
        remaining = [e for e in sorted(shows, key=lambda e: e.signal_id) if e not in picked]
        picked.extend(remaining[: FULL_REVIEW_CEILING - len(picked)])
    return sorted(picked, key=lambda e: e.signal_id), "OK"


# ─── Classement d'un wedge (§34–§37) ────────────────────────────────────────────


def classify(metrics: dict[str, Any]) -> tuple[str, list[str]]:
    """GREEN, AMBER, RED ou INSUFFICIENT SAMPLE — et pourquoi.

    L'ordre compte : RED l'emporte sur tout le reste, parce qu'un faux signal
    critique ou une précision sous 75 % disqualifie un wedge quel que soit son
    volume.
    """
    reviewed = metrics["reviewed"]
    if reviewed < MIN_FOR_LOW_SAMPLE:
        return "INSUFFICIENT SAMPLE", ["moins de 10 signaux évaluables"]

    reasons: list[str] = []
    precision = metrics["useful_precision"]
    if precision < 75.0 or metrics["critical_false"] > 0 or metrics["false_rate"] > 10.0:
        if precision < 75.0:
            reasons.append(f"précision utile {precision} % < 75 %")
        if metrics["critical_false"] > 0:
            reasons.append(f"{metrics['critical_false']} faux signal critique")
        if metrics["false_rate"] > 10.0:
            reasons.append(f"taux de faux {metrics['false_rate']} % > 10 %")
        return "RED", reasons

    green_blockers: list[str] = []
    if reviewed < GREEN["reviewed"]:
        green_blockers.append(f"{reviewed} signaux évalués < {GREEN['reviewed']}")
    if precision < GREEN["useful_precision"]:
        green_blockers.append(f"précision utile {precision} % < {GREEN['useful_precision']} %")
    if metrics["false_rate"] > GREEN["false_rate"]:
        green_blockers.append(f"taux de faux {metrics['false_rate']} % > {GREEN['false_rate']} %")
    if metrics["factual_integrity"] < GREEN["factual_integrity"]:
        green_blockers.append(f"intégrité factuelle {metrics['factual_integrity']} %")
    if metrics["proof_coverage"] < GREEN["proof_coverage"]:
        green_blockers.append(f"couverture de preuve {metrics['proof_coverage']} %")
    if metrics["top10_useful_precision"] < GREEN["top10_useful_precision"]:
        green_blockers.append(
            f"TOP10 {metrics['top10_useful_precision']} % < {GREEN['top10_useful_precision']} %"
        )
    if metrics["natural_show_volume"] < GREEN["natural_show_volume"]:
        green_blockers.append(
            f"volume naturel {metrics['natural_show_volume']} < {GREEN['natural_show_volume']}"
        )

    if not green_blockers:
        return "GREEN", []

    # §36 — AMBER couvre deux cas : la qualité intermédiaire, et la qualité
    # GREEN sur un volume naturel trop faible.
    volume_only = all("volume naturel" in reason for reason in green_blockers)
    if volume_only:
        return "AMBER", [*green_blockers, "qualité GREEN mais volume naturel insuffisant"]
    if (
        reviewed >= AMBER["reviewed"]
        and precision >= AMBER["useful_precision_min"]
        and metrics["critical_false"] == AMBER["critical_false"]
        and metrics["false_rate"] <= AMBER["false_rate"]
    ):
        return "AMBER", green_blockers
    return "RED", green_blockers
