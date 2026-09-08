"""Sélection Signal-100 : une politique déterministe, fixée avant adjudication.

SPEC-009 §13 et §14. Deux exigences qui tirent en sens inverse :

* **Ne pas cherry-picker par score** (§14) — le banc doit couvrir le spectre du
  feed, pas seulement son sommet. D'où trois zones de score et un quota par zone.
* **Couvrir la diversité** (§13) — sources, notices, pays, types de contrat,
  catégories de besoin, sans laisser un ICP ou un type de contrat dominer.

L'algorithme est un glouton à priorité de couverture : à chaque tour il retient
le candidat qui fait avancer le plus de minima encore non atteints, les égalités
étant tranchées par (zone la plus en retard, score décroissant, `signal_id`).
Aucun aléa, aucune date : deux exécutions donnent le même banc.

Un minimum de diversité impossible n'est jamais fabriqué : il est rapporté avec
ce que le pool pouvait offrir (§13, dernière phrase). Un *plafond* de diversité
qui empêcherait d'atteindre les cent signaux exigés cède au contraire d'un cran
à la fois, et chaque relaxation est publiée dans le rapport de conformité.
"""

from __future__ import annotations

import collections
import dataclasses
from collections.abc import Sequence

from signals.research.signal100 import PoolEntry, terciles

#: Quotas par zone de score (§14) — 33 / 34 / 33.
TERCILE_QUOTAS = {"top": 33, "middle": 34, "bottom": 33}

SIGNAL100_SIZE = 100

#: Plafonds durs (§8, §13) : ils ne sont jamais dépassés, même pour atteindre
#: un minimum de diversité.
MAX_PER_NOTICE = 2
MAX_PER_ICP = 25
MAX_PER_CONTRACT_TYPE = 35

#: Minima de diversité (§13) : visés, jamais forcés contre la réalité du pool.
MIN_PER_SOURCE = {"ted": 35, "simap": 35}
MIN_DISTINCT_NOTICES = 75
MIN_COUNTRIES = 5
MIN_CONTRACT_TYPES = 5
MIN_NEED_CATEGORIES = 5


@dataclasses.dataclass
class _Caps:
    """Les plafonds effectifs d'un tour de sélection.

    `MAX_PER_ICP` et `MAX_PER_CONTRACT_TYPE` sont des **objectifs** de diversité
    (§13), tandis que « exactement 100 signaux » est l'exigence dure, gatée par
    §59. Quand les deux s'opposent, l'objectif cède — d'un cran à la fois, et la
    relaxation est publiée. `MAX_PER_NOTICE` ne bouge jamais : ce n'est pas un
    objectif de diversité mais la règle anti-duplication de §8.
    """

    per_icp: int = MAX_PER_ICP
    per_contract_type: int = MAX_PER_CONTRACT_TYPE


@dataclasses.dataclass
class _State:
    """Ce que la sélection a déjà consommé, par dimension."""

    per_notice: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    per_icp: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    per_contract_type: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    per_source: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    per_tercile: collections.Counter = dataclasses.field(default_factory=collections.Counter)
    countries: set[str] = dataclasses.field(default_factory=set)
    contract_types: set[str] = dataclasses.field(default_factory=set)
    need_categories: set[str] = dataclasses.field(default_factory=set)
    notices: set[tuple] = dataclasses.field(default_factory=set)

    def admits(self, entry: PoolEntry, tercile: str, caps: _Caps) -> bool:
        """Les plafonds en vigueur, et eux seuls, décident de l'admissibilité."""
        if self.per_tercile[tercile] >= TERCILE_QUOTAS[tercile]:
            return False
        if self.per_notice[(entry.source, entry.notice)] >= MAX_PER_NOTICE:
            return False
        if self.per_icp[entry.icp_id] >= caps.per_icp:
            return False
        return self.per_contract_type[entry.contract_type] < caps.per_contract_type

    def take(self, entry: PoolEntry, tercile: str) -> None:
        self.per_tercile[tercile] += 1
        self.per_notice[(entry.source, entry.notice)] += 1
        self.per_icp[entry.icp_id] += 1
        self.per_contract_type[entry.contract_type] += 1
        self.per_source[entry.source] += 1
        self.notices.add((entry.source, entry.notice))
        self.contract_types.add(entry.contract_type)
        if entry.country:
            self.countries.add(entry.country)
        self.need_categories.update(entry.matched_needs)

    def coverage_gain(self, entry: PoolEntry) -> int:
        """Combien de minima encore non atteints ce candidat fait-il avancer ?"""
        gain = 0
        notice = (entry.source, entry.notice)
        if self.per_source[entry.source] < MIN_PER_SOURCE.get(entry.source, 0):
            gain += 1
        if len(self.notices) < MIN_DISTINCT_NOTICES and notice not in self.notices:
            gain += 1
        if (
            entry.country
            and len(self.countries) < MIN_COUNTRIES
            and entry.country not in self.countries
        ):
            gain += 1
        if (
            len(self.contract_types) < MIN_CONTRACT_TYPES
            and entry.contract_type not in self.contract_types
        ):
            gain += 1
        if len(self.need_categories) < MIN_NEED_CATEGORIES and (
            set(entry.matched_needs) - self.need_categories
        ):
            gain += 1
        return gain


def _greedy(
    pool: Sequence[PoolEntry],
    tercile_of: dict[str, str],
    caps: _Caps,
    size: int,
) -> tuple[list[PoolEntry], _State]:
    """Un tour de glouton à priorité de couverture, sous des plafonds donnés."""
    state = _State()
    selected: list[PoolEntry] = []
    remaining = sorted(pool, key=lambda e: (-e.normalized_score, e.signal_id))

    while len(selected) < size:
        best: tuple | None = None
        chosen: PoolEntry | None = None
        for entry in remaining:
            tercile = tercile_of[entry.signal_id]
            if not state.admits(entry, tercile, caps):
                continue
            # Le retard d'une zone départage : sans cela le glouton remplirait
            # la zone haute d'abord et §14 ne tiendrait que par accident.
            shortfall = TERCILE_QUOTAS[tercile] - state.per_tercile[tercile]
            rank = (-state.coverage_gain(entry), -shortfall, -entry.normalized_score)
            if best is None or rank < best:
                best, chosen = rank, entry
        if chosen is None:
            break
        state.take(chosen, tercile_of[chosen.signal_id])
        selected.append(chosen)
        remaining.remove(chosen)
    return selected, state


def select_signal100(
    pool: Sequence[PoolEntry], *, size: int = SIGNAL100_SIZE
) -> tuple[list[PoolEntry], dict]:
    """Construit le banc et rend compte de ce qui a été atteint ou non.

    Le pool reçu est déjà dédupliqué (un signal par award-lot, §8) : cette
    fonction n'arbitre plus entre ICPs, elle compose un échantillon.

    Si les objectifs de diversité rendent 100 signaux inatteignables, le
    plafond qui bloque est relâché d'un cran et la sélection recommence. C'est
    la lecture de §13 : « exactement 100 » est l'exigence, les maxima par ICP et
    par type de contrat sont des objectifs, et quand une dimension est
    impossible on documente la distribution réelle au lieu de la maquiller.
    """
    zones = terciles(pool)
    tercile_of = {entry.signal_id: name for name, entries in zones.items() for entry in entries}

    caps = _Caps()
    relaxations: list[dict] = []
    selected, state = _greedy(pool, tercile_of, caps, size)

    while len(selected) < size:
        icp_binding = any(count >= caps.per_icp for count in state.per_icp.values())
        type_binding = any(
            count >= caps.per_contract_type for count in state.per_contract_type.values()
        )
        if icp_binding and caps.per_icp < size:
            caps.per_icp += 1
            relaxations.append({"cap": "max_per_icp", "raised_to": caps.per_icp})
        elif type_binding and caps.per_contract_type < size:
            caps.per_contract_type += 1
            relaxations.append(
                {"cap": "max_per_contract_type", "raised_to": caps.per_contract_type}
            )
        else:
            # Ni plafond ni quota ne bloque : le pool lui-même est épuisé.
            break
        selected, state = _greedy(pool, tercile_of, caps, size)

    compliance = _compliance(selected, state, pool)
    compliance["caps_applied"] = {
        "max_per_icp": caps.per_icp,
        "max_per_contract_type": caps.per_contract_type,
        "max_per_notice": MAX_PER_NOTICE,
    }
    compliance["relaxations"] = relaxations
    return sorted(selected, key=lambda e: (-e.normalized_score, e.signal_id)), compliance


def _compliance(selected: Sequence[PoolEntry], state: _State, pool: Sequence[PoolEntry]) -> dict:
    """Le respect, dimension par dimension, avec la réalité du pool en regard.

    Un minimum non atteint n'est pas masqué : il est rapporté avec ce que le
    pool pouvait offrir, pour distinguer « sélection ratée » de « le pool ne
    contient pas la diversité demandée » (§13).
    """
    pool_sources = collections.Counter(e.source for e in pool)
    pool_countries = {e.country for e in pool if e.country}
    pool_types = {e.contract_type for e in pool}
    pool_needs = {need for e in pool for need in e.matched_needs}
    pool_notices = {(e.source, e.notice) for e in pool}

    return {
        "selected": len(selected),
        "per_tercile": dict(state.per_tercile),
        "tercile_quotas": TERCILE_QUOTAS,
        "per_source": dict(state.per_source),
        "pool_per_source": dict(pool_sources),
        "distinct_notices": len(state.notices),
        "pool_distinct_notices": len(pool_notices),
        "countries": sorted(state.countries),
        "pool_countries": len(pool_countries),
        "contract_types": sorted(state.contract_types),
        "pool_contract_types": len(pool_types),
        "need_categories": sorted(state.need_categories),
        "pool_need_categories": len(pool_needs),
        "max_per_icp_observed": max(state.per_icp.values(), default=0),
        "max_per_contract_type_observed": max(state.per_contract_type.values(), default=0),
        "max_per_notice_observed": max(state.per_notice.values(), default=0),
        "per_icp": dict(state.per_icp),
        "targets": {
            "size": SIGNAL100_SIZE,
            "min_per_source": MIN_PER_SOURCE,
            "min_distinct_notices": MIN_DISTINCT_NOTICES,
            "min_countries": MIN_COUNTRIES,
            "min_contract_types": MIN_CONTRACT_TYPES,
            "min_need_categories": MIN_NEED_CATEGORIES,
            "max_per_icp": MAX_PER_ICP,
            "max_per_contract_type": MAX_PER_CONTRACT_TYPE,
            "max_per_notice": MAX_PER_NOTICE,
        },
    }
