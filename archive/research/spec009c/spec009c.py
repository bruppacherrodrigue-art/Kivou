"""SPEC-009C — le banc du feed client, pas celui d'un composant.

Un seul client, un seul ICP, un seul feed (§3). Aucune compétition entre ICPs,
aucune règle « best ICP wins » : un award-lot est confronté à
`icp-construction-inputs-ch-eu-v0` et à rien d'autre. C'est la doctrine produit
que SPEC-009B avait établie, appliquée ici pour la première fois de bout en bout.

Ce module ne règle rien. Il sélectionne, décrit et gèle — les moteurs sont
appelés dans leur version committée, et SPEC-009C §4 interdit d'y toucher.

La politique de sélection reprend celle de SPEC-009 §14 : terciles de score,
au plus deux award-lots par notice, un seul signal par award-lot, et une
répartition déterministe entre strates. Elle est réécrite ici plutôt
qu'importée parce que le banc porte des dimensions que SPEC-009 n'avait pas —
corps de métier et tranche de montant.
"""

from __future__ import annotations

import collections
import dataclasses
from collections.abc import Sequence
from typing import Any

BENCHMARK_TARGET = 100
"""§12 — exactement 100 signaux quand le volume naturel le permet."""

MINIMUM_BENCHMARK = 50
"""§11 — en dessous, ce n'est plus une densité faible mais un blocage."""

MAX_AWARD_LOTS_PER_NOTICE = 2
"""§13 — une notice à quarante lots ne doit pas coloniser le banc."""

VALUE_BANDS: tuple[tuple[str, float], ...] = (
    ("under_250k", 250_000),
    ("250k_1m", 1_000_000),
    ("1m_5m", 5_000_000),
    ("over_5m", float("inf")),
)


@dataclasses.dataclass(frozen=True)
class WedgeSignal:
    """Un `show` du feed client, avec ce qui sert à le stratifier et à l'analyser."""

    signal_id: str
    source: str
    notice: str
    award_key: tuple
    normalized_score: int
    band: str
    confidence: str
    country: str | None
    trade_domain: str
    trade_source: str
    contract_type: str
    sector: str
    cpv: str | None
    bkp_codes: tuple[str, ...]
    amount: float | None
    currency: str | None
    matched_needs: tuple[str, ...]

    @property
    def value_band(self) -> str:
        if self.amount is None:
            return "unpublished"
        for name, ceiling in VALUE_BANDS:
            if self.amount < ceiling:
                return name
        return VALUE_BANDS[-1][0]

    @property
    def stratum(self) -> tuple:
        """Les dimensions que §13 demande de croiser."""
        return (self.source, self.country or "?", self.trade_domain, self.value_band)


def funnel(decisions: Sequence[str]) -> dict[str, int]:
    """L'entonnoir naturel du feed (§9), dans l'ordre où on le lit."""
    counts = collections.Counter(decisions)
    return {
        "award_lots": len(decisions),
        "show": counts["show"],
        "borderline": counts["borderline"],
        "exclude": counts["exclude"],
        "insufficient_data": counts["insufficient_data"],
    }


def density(funnel_counts: dict[str, int], *, construction_award_lots: int) -> dict[str, float]:
    """§38 — un feed très précis qui ne produit rien reste commercialement faible."""
    total = funnel_counts["award_lots"]
    show = funnel_counts["show"]
    return {
        "show_per_100_awards": round(100 * show / total, 2) if total else 0.0,
        "show_per_100_construction_awards": (
            round(100 * show / construction_award_lots, 2) if construction_award_lots else 0.0
        ),
    }


def cap_per_notice(
    signals: Sequence[WedgeSignal], *, cap: int = MAX_AWARD_LOTS_PER_NOTICE
) -> list[WedgeSignal]:
    """Au plus `cap` award-lots par notice, sans dépendre de l'ordre d'acquisition."""
    kept: list[WedgeSignal] = []
    seen: dict[tuple, int] = {}
    for signal in sorted(signals, key=lambda s: (-s.normalized_score, s.signal_id)):
        key = (signal.source, signal.notice)
        if seen.get(key, 0) >= cap:
            continue
        seen[key] = seen.get(key, 0) + 1
        kept.append(signal)
    return kept


def terciles(signals: Sequence[WedgeSignal]) -> dict[str, list[WedgeSignal]]:
    """Trois zones de score, découpées par RANG et non par valeur.

    Les scores sont très discrets : des bornes par valeur produiraient des
    zones vides.
    """
    ordered = sorted(signals, key=lambda s: (-s.normalized_score, s.signal_id))
    size = len(ordered)
    return {
        "top": ordered[: size // 3],
        "middle": ordered[size // 3 : 2 * size // 3],
        "bottom": ordered[2 * size // 3 :],
    }


def _spread(signals: Sequence[WedgeSignal], wanted: int) -> list[WedgeSignal]:
    """Prend `wanted` signaux en tournant sur les strates, de façon déterministe.

    Aucune sélection selon la qualité présumée (§12) : à l'intérieur d'une
    strate l'ordre reste (score décroissant, `signal_id`), et le tour de rôle
    entre strates ne regarde que leur clé.
    """
    buckets: dict[tuple, list[WedgeSignal]] = {}
    for signal in sorted(signals, key=lambda s: (-s.normalized_score, s.signal_id)):
        buckets.setdefault(signal.stratum, []).append(signal)
    picked: list[WedgeSignal] = []
    while len(picked) < wanted and any(buckets.values()):
        for key in sorted(buckets):
            if len(picked) >= wanted:
                break
            if buckets[key]:
                picked.append(buckets[key].pop(0))
    return picked


def select_benchmark(
    signals: Sequence[WedgeSignal], *, target: int = BENCHMARK_TARGET
) -> list[WedgeSignal]:
    """Le banc : tous les signaux si le volume est faible, sinon 33/34/33 (§12, §13)."""
    capped = cap_per_notice(signals)
    if len(capped) <= target:
        return sorted(capped, key=lambda s: s.signal_id)

    zones = terciles(capped)
    quotas = {"top": target // 3, "middle": target - 2 * (target // 3), "bottom": target // 3}
    picked: list[WedgeSignal] = []
    for zone in ("top", "middle", "bottom"):
        picked += _spread(zones[zone], quotas[zone])
    # Une zone trop maigre ne fait pas rater la cible : le complément vient des
    # signaux restants, toujours dans l'ordre déterministe.
    if len(picked) < target:
        chosen = {s.signal_id for s in picked}
        rest = [s for s in capped if s.signal_id not in chosen]
        picked += _spread(rest, target - len(picked))
    return sorted(picked, key=lambda s: s.signal_id)


def composition(signals: Sequence[WedgeSignal]) -> dict[str, Any]:
    """Ce que le banc contient réellement, dimension par dimension (§13, §14)."""
    zones = terciles(signals)
    return {
        "signals": len(signals),
        "by_source": dict(collections.Counter(s.source for s in signals)),
        "by_country": dict(collections.Counter(s.country or "?" for s in signals)),
        "by_trade_domain": dict(collections.Counter(s.trade_domain for s in signals)),
        "by_trade_source": dict(collections.Counter(s.trade_source for s in signals)),
        "by_value_band": dict(collections.Counter(s.value_band for s in signals)),
        "by_band": dict(collections.Counter(s.band for s in signals)),
        "by_score_zone": {zone: len(members) for zone, members in zones.items()},
        "with_bkp": sum(1 for s in signals if s.bkp_codes),
        "without_bkp": sum(1 for s in signals if not s.bkp_codes),
        "notices": len({(s.source, s.notice) for s in signals}),
    }
