"""SPEC-009D — audit de fraîcheur et d'observabilité du canal d'achat.

SPEC-009C a mesuré 64 % de signaux utiles sur 100 signaux frais et a rattaché
23 des 36 échecs à la couche `matching`, avec un motif unique : *le gagnant est
un spécialiste dont la filière d'achat n'est pas celle d'un négoce*. Deux
questions restaient posées, et ce module ne répond qu'à celles-là.

    A. RECENCY
    ──────────
    Quand Kivou découvre le signal, depuis combien de temps l'entreprise a-t-elle
    réellement gagné ? La variable commerciale est `award_date`, jamais
    `publication_date` — et le moteur de matching, lui, ne connaît que la
    seconde (`MatchingEngine._freshness_filter`). L'audit mesure l'écart.

    B. PURCHASE-CHANNEL OBSERVABILITY
    ─────────────────────────────────
    Les données publiques déjà présentes permettent-elles de distinguer un
    gagnant qui *achète* les intrants d'un spécialiste ou d'un fabricant qui les
    produit ? On ne cherche pas à prédire : on inventorie ce qui est connaissable.

`AUDIT ONLY` (§1). Aucun moteur n'est touché, aucun label commercial n'est
rejugé, aucun seuil n'est posé. Le module est pur, hors ligne, sans horloge :
`as_of` est toujours explicite, comme dans le reste du dépôt.

Deux interdits sont exécutables plutôt que déclaratifs, parce qu'ils sont les
seuls qui pourraient discrètement fausser toute la partie B :

* §30 — le nom du gagnant n'est **pas** une donnée d'activité. `admit_feature`
  le refuse, ce qui empêche « Metallbau AG contient Metallbau » de devenir une
  règle.
* §26 — un verdict commercial et la motivation qui l'accompagne sont
  **postérieurs** au matching. Les réintroduire comme variable ferait passer une
  circularité pour une découverte.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

# ════════════════════════════════════════════════════════════════════════════════
# PARTIE A — RECENCY
# ════════════════════════════════════════════════════════════════════════════════

#: §8 — les tranches de fraîcheur, bornes hautes incluses. `unknown` n'est pas
#: une tranche par défaut : c'est le constat qu'aucune date d'attribution n'a
#: été publiée, et il ne doit jamais être fusionné avec les autres.
AWARD_AGE_BUCKETS: tuple[tuple[int, str], ...] = (
    (7, "0-7"),
    (14, "8-14"),
    (30, "15-30"),
    (60, "31-60"),
    (90, "61-90"),
    (120, "91-120"),
)

AWARD_AGE_BUCKET_ORDER: tuple[str, ...] = (
    "0-7",
    "8-14",
    "15-30",
    "31-60",
    "61-90",
    "91-120",
    ">120",
    "unknown",
)

PUBLICATION_DELAY_BUCKETS: tuple[tuple[int, str], ...] = (
    (0, "same_day"),
    (7, "1-7"),
    (14, "8-14"),
    (30, "15-30"),
    (60, "31-60"),
)

PUBLICATION_DELAY_BUCKET_ORDER: tuple[str, ...] = (
    "same_day",
    "1-7",
    "8-14",
    "15-30",
    "31-60",
    ">60",
    "unknown",
)

#: §9 — trois définitions de « vient de gagner », posées pour le diagnostic
#: seulement. Aucune politique produit n'en découle dans cette SPEC.
JUST_WON_THRESHOLDS: tuple[int, ...] = (7, 14, 30)

#: §11 — sous cinq observations, un taux de précision est du bruit affiché.
MINIMUM_BUCKET_SAMPLE = 5

#: §24 — les deux régimes de confiance de la partie B.
INSUFFICIENT_SAMPLE = 10
INDICATIVE_SAMPLE = 20


def parse_date(value: Any) -> dt.date | None:
    """Une date canonique, ou `None` — jamais une date reconstruite.

    Accepte ce que les snapshots gelés contiennent réellement : une `date`, un
    `datetime`, une chaîne ISO éventuellement horodatée. Tout le reste est
    absent, et l'absence est une mesure.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value)
    return dt.date.fromisoformat(text[:10])


@dataclasses.dataclass(frozen=True)
class RecencyRecord:
    """Les quatre dates d'un signal, et rien qui les remplace.

    `award_date` absente reste absente : §6 interdit la substitution par
    `publication_date`, qui ferait passer une attribution de mai pour une
    attribution du jour.
    """

    signal_id: str
    source: str
    as_of: dt.date
    award_date: dt.date | None = None
    publication_date: dt.date | None = None
    contract_start_date: dt.date | None = None
    contract_end_date: dt.date | None = None

    @property
    def award_date_status(self) -> str:
        return "known" if self.award_date is not None else "unknown"

    @property
    def award_age_days(self) -> int | None:
        if self.award_date is None:
            return None
        return (self.as_of - self.award_date).days

    @property
    def publication_age_days(self) -> int | None:
        if self.publication_date is None:
            return None
        return (self.as_of - self.publication_date).days

    @property
    def publication_delay_days(self) -> int | None:
        if self.award_date is None or self.publication_date is None:
            return None
        return (self.publication_date - self.award_date).days

    @property
    def days_to_contract_start(self) -> int | None:
        if self.contract_start_date is None:
            return None
        return (self.contract_start_date - self.as_of).days

    @property
    def days_until_contract_end(self) -> int | None:
        if self.contract_end_date is None:
            return None
        return (self.contract_end_date - self.as_of).days

    @property
    def has_started(self) -> bool:
        return self.contract_start_date is not None and self.contract_start_date < self.as_of

    def is_ending_soon(self, *, horizon_days: int = 30) -> bool:
        remaining = self.days_until_contract_end
        return remaining is not None and remaining <= horizon_days

    @property
    def award_age_bucket(self) -> str:
        return award_age_bucket(self.award_age_days)


def award_age_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    for ceiling, name in AWARD_AGE_BUCKETS:
        if days <= ceiling:
            return name
    return ">120"


def publication_delay_bucket(days: int | None) -> str:
    if days is None:
        return "unknown"
    for ceiling, name in PUBLICATION_DELAY_BUCKETS:
        if days <= ceiling:
            return name
    return ">60"


def distribution(values: Iterable[int]) -> dict[str, int]:
    """Percentiles par rang le plus proche — aucune interpolation.

    Les séries de l'audit comptent quelques dizaines de valeurs entières : une
    interpolation y inventerait des jours qui n'existent dans aucun avis.
    """
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}

    def rank(pct: float) -> int:
        return ordered[max(0, math.ceil(pct * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "median": rank(0.50),
        "p25": rank(0.25),
        "p75": rank(0.75),
        "p90": rank(0.90),
        "p95": rank(0.95),
        "max": ordered[-1],
    }


def quality_breakdown(verdicts: Sequence[str]) -> dict[str, Any]:
    """A/B/C/D et les quatre taux — muets sous cinq observations (§11)."""
    counts = collections.Counter(verdicts)
    total = len(verdicts)
    result: dict[str, Any] = {
        "n": total,
        "A": counts["A"],
        "B": counts["B"],
        "C": counts["C"],
        "D": counts["D"],
    }
    if total < MINIMUM_BUCKET_SAMPLE:
        result["sample"] = "sample too small"
        return result
    result["sample"] = "reportable"
    result["useful_precision"] = round(100 * (counts["A"] + counts["B"]) / total, 1)
    result["actionable_rate"] = round(100 * counts["A"] / total, 1)
    result["weak_rate"] = round(100 * counts["C"] / total, 1)
    result["false_rate"] = round(100 * counts["D"] / total, 1)
    return result


def just_won(records: Sequence[RecencyRecord], *, max_age_days: int) -> list[RecencyRecord]:
    """Les signaux dont l'attribution est datée et récente (§9).

    Un `award_date` inconnu n'entre jamais dans un `JUST_WON` : le doute ne se
    résout pas en faveur de la fraîcheur.
    """
    return [
        r for r in records if r.award_age_days is not None and 0 <= r.award_age_days <= max_age_days
    ]


def stale_but_recently_published(
    records: Sequence[RecencyRecord],
    *,
    publication_age_max: int = 14,
    award_age_min: int = 60,
) -> list[RecencyRecord]:
    """§14 — l'avis vient de paraître, l'attribution date. Le cas le plus dangereux.

    C'est exactement ce que la promesse « il vient de gagner » achète comme
    risque : le moteur ne regarde que la publication, et la publication ment sur
    l'événement commercial.
    """
    flagged = [
        r
        for r in records
        if r.publication_age_days is not None
        and r.publication_age_days <= publication_age_max
        and r.award_age_days is not None
        and r.award_age_days > award_age_min
    ]
    return sorted(flagged, key=lambda r: (-(r.award_age_days or 0), r.signal_id))


def contracts_already_started(records: Sequence[RecencyRecord]) -> list[RecencyRecord]:
    return sorted((r for r in records if r.has_started), key=lambda r: r.signal_id)


def contracts_ending_soon(
    records: Sequence[RecencyRecord], *, horizon_days: int = 30
) -> list[RecencyRecord]:
    return sorted(
        (r for r in records if r.is_ending_soon(horizon_days=horizon_days)),
        key=lambda r: r.signal_id,
    )


def sample_label(n: int) -> str:
    """§24 — nommer le régime de confiance plutôt que de laisser lire un taux nu."""
    if n < INSUFFICIENT_SAMPLE:
        return "insufficient sample"
    if n < INDICATIVE_SAMPLE:
        return "indicative only"
    return "reportable"


def recency_verdict(
    *,
    award_date_coverage: float,
    just_won_30_share: float,
    quality_gradient: float,
) -> str:
    """§16 — la fraîcheur est-elle démontrée, partiellement lisible, ou absente ?

    Trois conditions, dans cet ordre : peut-on l'observer, les signaux sont-ils
    réellement récents, et la récence achète-t-elle de la qualité commerciale ?
    `quality_gradient` est la différence, en points de précision utile, entre
    les attributions de moins de trente jours et les plus anciennes.
    """
    if award_date_coverage < 60:
        return "RECENCY NOT RELIABLY OBSERVABLE"
    if just_won_30_share < 50:
        return "RECENCY WEAK"
    if award_date_coverage < 90:
        return "RECENCY PARTIALLY OBSERVABLE"
    if quality_gradient >= 10:
        return "RECENCY STRONG"
    return "RECENCY PARTIALLY OBSERVABLE"


# ════════════════════════════════════════════════════════════════════════════════
# PARTIE B — PURCHASE-CHANNEL OBSERVABILITY
# ════════════════════════════════════════════════════════════════════════════════

#: §19, §31 — les faits que le moteur déterministe expose **canoniquement** et
#: **avant** la décision de matching. Un fait qui n'existe que dans un titre ou
#: une description libre n'est pas ici : il n'est pas observable tant qu'aucun
#: extracteur ne le rend structuré. Les sorties du matching (score, bande,
#: besoins retenus) sont exclues — ce sont des résultats, pas des entrées.
CANONICAL_PRE_MATCH_FACTS: dict[str, str] = {
    # provenance
    "source": "source",
    "notice": "notice",
    "publication_date": "publication_date",
    "source_mode": "source_mode",
    # dates canoniques
    "award_date": "understanding.timing.award_date",
    "contract_signature_date": "understanding.timing.contract_signature_date",
    "contract_start_date": "understanding.timing.contract_start_date",
    "contract_end_date": "understanding.timing.contract_end_date",
    # objet du marché
    "contract_title": "contract.title",
    "contract_description": "contract.description",
    "contract_reference": "contract.contract_reference",
    "lot_title": "contract.lot_title",
    "object_summary": "understanding.object_summary",
    "characteristics": "understanding.characteristics",
    # classifications
    "cpv_main": "contract.cpv_main",
    "cpv_additional": "contract.cpv_additional",
    "bkp_codes": "bkp_codes",
    "trade_domain": "trade_domain",
    "trade_domain_source": "trade_domain_source",
    "contract_type": "understanding.contract_type.value",
    "sector": "understanding.sector.value",
    # valeur et géographie
    "amount": "contract.value.amount",
    "currency": "contract.value.currency",
    "place_of_performance": "contract.place_of_performance",
    "buyers": "contract.buyers",
    # gagnant — identité et localisation, jamais activité
    "winner_status": "winner.status",
    "winner_is_group": "winner.parties[].is_group",
    "winner_country": "winner.parties[].members[].country",
    "winner_address": "winner.parties[].members[].address",
    "winner_identifiers": "winner.parties[].members[].identifiers",
    "winner_website": "winner.parties[].members[].website",
    # besoins dérivés — produits avant le matching
    "need_categories": "needs.needs[].category",
    "need_timings": "needs.needs[].timing",
}

#: §26, §30 — ce qui ne peut jamais devenir une variable. La liste est courte
#: parce qu'elle ne recense pas des champs peu fiables, mais des champs dont
#: l'usage produirait un résultat faux tout en paraissant juste.
FORBIDDEN_FEATURES: dict[str, str] = {
    "winner_legal_name": (
        "§30 — le nom d'une société n'est pas une donnée d'activité ; deviner "
        "« fabricant » ou « grossiste » d'une raison sociale n'est pas une mesure"
    ),
    "winner_name": "§30 — voir winner_legal_name",
    "winner_brand": "§30 — une marque ne décrit pas une filière d'achat",
    "final_verdict": "§26 — un verdict commercial est un résultat, jamais une entrée",
    "final_dimensions": "§26 — dimensions d'adjudication, postérieures au matching",
    "final_note": "§26 — la motivation d'un adjudicateur est postérieure au matching",
    "review_a": "§26 — avis de reviewer, postérieur au matching",
    "review_b": "§26 — avis de reviewer, postérieur au matching",
    "arbitration": "§26 — arbitrage, postérieur au matching",
    "primary_failure_layer": "§26 — attribution d'échec, postérieure au matching",
    "critical_false_signal": "§26 — qualification d'échec, postérieure au matching",
    "normalized_score": "§21 — sortie du matching, pas un fait disponible avant lui",
    "score_band": "§21 — sortie du matching, pas un fait disponible avant lui",
    "matched_needs": "§21 — sortie du matching, pas un fait disponible avant lui",
}


def admit_feature(name: str) -> str:
    """Le chemin canonique d'un fait, ou un refus motivé (§26, §30, §31)."""
    if name in FORBIDDEN_FEATURES:
        raise ValueError(f"{name} : {FORBIDDEN_FEATURES[name]}")
    if name not in CANONICAL_PRE_MATCH_FACTS:
        raise ValueError(
            f"{name} : fait inconnu du catalogue canonique pré-matching — "
            "§31 interdit de supposer qu'un champ existe"
        )
    return CANONICAL_PRE_MATCH_FACTS[name]


def field_coverage(
    signals: Mapping[str, Any],
    present: Callable[[Any], bool],
    *,
    useful_ids: set[str],
) -> dict[str, Any]:
    """§19 — couverture d'un champ, et la même couverture dans les deux camps.

    Les dénominateurs sont les tailles des deux populations, jamais le total :
    une couverture « A+B » rapportée sur 100 signaux ne dirait rien.
    """
    ids = list(signals)
    useful = [sid for sid in ids if sid in useful_ids]
    non_useful = [sid for sid in ids if sid not in useful_ids]

    def share(population: Sequence[str]) -> float | None:
        if not population:
            return None
        return round(
            100 * sum(1 for sid in population if present(signals[sid])) / len(population), 1
        )

    return {
        "n": len(ids),
        "n_useful": len(useful),
        "n_non_useful": len(non_useful),
        "coverage": share(ids),
        "coverage_useful": share(useful),
        "coverage_non_useful": share(non_useful),
    }


def contingency(values: Mapping[str, str], *, useful_ids: set[str]) -> dict[str, dict[str, Any]]:
    """§22, §23 — une table de contingence, sans modèle derrière."""
    table: dict[str, dict[str, Any]] = {}
    for sid, value in values.items():
        row = table.setdefault(value, {"n": 0, "useful": 0, "non_useful": 0})
        row["n"] += 1
        row["useful" if sid in useful_ids else "non_useful"] += 1
    for row in table.values():
        row["useful_precision"] = round(100 * row["useful"] / row["n"], 1)
    return table


def odds_ratio(
    useful_with: int, useful_without: int, non_useful_with: int, non_useful_without: int
) -> dict[str, Any]:
    """Rapport de cotes brut, avec correction de Haldane si une case est vide.

    §23 autorise le rapport de cotes et rien de plus : pas d'ajustement, pas
    d'intervalle, pas d'apprentissage. La correction est signalée quand elle
    s'applique, parce qu'elle change ce que le chiffre veut dire.
    """
    cells = [useful_with, useful_without, non_useful_with, non_useful_without]
    corrected = any(cell == 0 for cell in cells)
    a, b, c, d = (cell + 0.5 for cell in cells) if corrected else cells
    return {
        "odds_ratio": round((a * d) / (b * c), 2),
        "haldane_corrected": corrected,
        "sample": sample_label(sum(cells)),
    }


def control_sample(
    candidates: Mapping[str, tuple],
    failure_strata: Sequence[tuple],
    *,
    size: int,
) -> tuple[str, ...]:
    """§28 — un témoin A/B apparié aux strates des échecs, strictement déterministe.

    Chaque strate d'échec réclame d'abord son homologue utile, dans l'ordre des
    `signal_id` ; ce qui manque est complété dans ce même ordre. Aucun tirage,
    aucune horloge : le témoin doit être identique d'une exécution à l'autre.
    """
    by_stratum: dict[tuple, list[str]] = {}
    for sid in sorted(candidates):
        by_stratum.setdefault(candidates[sid], []).append(sid)

    picked: list[str] = []
    taken: set[str] = set()
    for stratum in failure_strata:
        if len(picked) >= size:
            break
        pool = by_stratum.get(stratum, [])
        for sid in pool:
            if sid not in taken:
                picked.append(sid)
                taken.add(sid)
                break
    for sid in sorted(candidates):
        if len(picked) >= size:
            break
        if sid not in taken:
            picked.append(sid)
            taken.add(sid)
    return tuple(picked[:size])


OBSERVABILITY_VALUES: tuple[str, ...] = ("YES", "PARTIAL", "NO")


def observability_rate(values: Sequence[str]) -> dict[str, Any]:
    """§27 — la métrique centrale de la partie B. Les trois compteurs somment."""
    for value in values:
        if value not in OBSERVABILITY_VALUES:
            raise ValueError(f"observabilité {value!r} hors des trois valeurs autorisées")
    counts = collections.Counter(values)
    total = len(values)
    result: dict[str, Any] = {"n": total}
    for value in OBSERVABILITY_VALUES:
        result[value] = counts[value]
    if total:
        result["yes_rate"] = round(100 * counts["YES"] / total, 1)
        result["partial_rate"] = round(100 * counts["PARTIAL"] / total, 1)
        result["not_observable_rate"] = round(100 * counts["NO"] / total, 1)
    return result


def channel_verdict(*, winner_activity_fields: int, fully_observable_rate: float) -> str:
    """§34 — ce que les données actuelles permettent de savoir du canal d'achat.

    `winner_activity_fields` compte les champs décrivant l'**activité** du
    gagnant (code NACE/NOGA, forme juridique, statut fabricant ou grossiste,
    taille). L'identité et l'adresse n'en font pas partie : elles disent où
    écrire, pas ce que l'entreprise achète.
    """
    if fully_observable_rate >= 90 and winner_activity_fields > 0:
        return "PURCHASE CHANNEL OBSERVABLE WITH CURRENT DATA"
    if fully_observable_rate >= 50:
        return "PURCHASE CHANNEL PARTIALLY OBSERVABLE"
    return "PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA"


def decision_matrix(recency: str, channel: str) -> dict[str, str]:
    """§35, §46, §47 — le croisement, et l'unique prochaine étape qu'il autorise.

    Seul `RECENCY STRONG` compte comme fraîcheur démontrée : une fraîcheur
    partiellement observable ne soutient pas une promesse produit, elle la
    documente comme incertaine.
    """
    strong = recency == "RECENCY STRONG"
    observable = channel == "PURCHASE CHANNEL OBSERVABLE WITH CURRENT DATA"
    if strong and observable:
        return {
            "scenario": "A",
            "verdict": "RECENCY + CHANNEL OBSERVABLE",
            "next_step": "targeted deterministic correction",
        }
    if strong:
        return {
            "scenario": "B",
            "verdict": "RECENCY STRONG / CHANNEL NOT OBSERVABLE",
            "next_step": "external winner enrichment study OR narrower signal definition",
        }
    if observable:
        return {
            "scenario": "C",
            "verdict": "RECENCY WEAK / CHANNEL OBSERVABLE",
            "next_step": "source/timing strategy correction",
        }
    return {
        "scenario": "D",
        "verdict": "RECENCY + CHANNEL NOT OBSERVABLE",
        "next_step": "rethink MVP signal promise",
    }


# ─── §25–§27 — l'étude des 23 échecs de matching ────────────────────────────────

#: §25 — les six motifs commerciaux autorisés. Ils décrivent *pourquoi* le
#: gagnant n'achète pas au négoce, pas la gravité de l'erreur.
CHANNEL_REASONS: tuple[str, ...] = (
    "specialist_contractor",
    "manufacturer",
    "integrated_supplier",
    "trade_specific_buyer_channel",
    "deliverable_overlap",
    "other",
)


@dataclasses.dataclass(frozen=True)
class FailureCase:
    """Un échec de matching, relu — jamais rejugé (§3, §25, §40).

    `channel_reason` reprend le mécanisme commercial que l'adjudication a déjà
    écrit. `observability` répond à la seule question de §26 : un fait canonique
    disponible **avant** le matching permettait-il de le prévoir ?

    La règle appliquée pour trancher est unique et vérifiable sur le banc :

    * ``YES``     — un code canonique (BKP ou CPV) nomme un métier hors
                    catalogue de l'ICP, et sa valeur n'apparaît sur aucun signal
                    utile du banc.
    * ``PARTIAL`` — un code canonique existe mais sa valeur se retrouve aussi
                    sur des signaux utiles : il oriente sans trancher.
    * ``NO``      — aucun code ne distingue, ou le code décrit un type de
                    bâtiment, ou il nomme un métier *du* catalogue alors que le
                    problème tient à l'activité du gagnant.
    """

    signal_id: str
    channel_reason: str
    observability: str
    fact_ids: tuple[str, ...]
    reason: str


MATCHING_FAILURE_STUDY: tuple[FailureCase, ...] = (
    FailureCase(
        signal_id="19284980bc7ea7f572afbe592e0d09ba7124cdcee9d8c0f8c96cb43f46e2ded0",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason=(
            "BKP 422 « Einfriedungen » : famille 42 (Gartenanlagen), absente de "
            "la taxonomie de métiers et de tout signal utile du banc"
        ),
    ),
    FailureCase(
        signal_id="1bca9c53f942d491084601f262caa510abfd5dba548678b448dea00bc7e56b43",
        channel_reason="specialist_contractor",
        observability="PARTIAL",
        fact_ids=("cpv_main", "contract_start_date"),
        reason=(
            "CPV 45221119 (réparation d'ouvrage d'art) oriente vers le génie "
            "civil spécialisé, mais porte aussi un signal utile du banc"
        ),
    ),
    FailureCase(
        signal_id="1c3ca2d29739aac10316ca47efa55ab031734361e8e56f0657bd02f92a8c446d",
        channel_reason="specialist_contractor",
        observability="PARTIAL",
        fact_ids=("bkp_codes",),
        reason="BKP 272 (Metallbau) présent sur deux signaux utiles du banc : il n'exclut pas",
    ),
    FailureCase(
        signal_id="2f40938a6a503fde4132a37b8789e8b47e92df0f434c28856a5f9b9b876f2c3f",
        channel_reason="integrated_supplier",
        observability="YES",
        fact_ids=("cpv_main",),
        reason="CPV 45421151 (Kücheneinrichtung) exclusif aux échecs, hors catalogue ICP",
    ),
    FailureCase(
        signal_id="3e043bd7947075a238b86f214d8fc342859736594571691883738778bb35e08b",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("cpv_main",),
        reason="CPV 45262220 (forage de puits) exclusif aux échecs, filière d'achat propre",
    ),
    FailureCase(
        signal_id="42bd8585c2224de20dbed387a57821421a7f3df40ce3bc8dd72eb98de892733b",
        channel_reason="specialist_contractor",
        observability="PARTIAL",
        fact_ids=("cpv_main",),
        reason="CPV 45262670 (Metallbau) porte deux signaux utiles du banc autant que deux échecs",
    ),
    FailureCase(
        signal_id="48b30b9519a7a3f087624f206f0be2e207e4da3fa500906fbda6108a21bba4ec",
        channel_reason="manufacturer",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason="BKP 277.1 (Schiebe- und Faltwände) exclusif aux échecs",
    ),
    FailureCase(
        signal_id="52f5b6f58488682f95a65744e8f62aaa1afbc5e4723bfe5559b34ebc894f43eb",
        channel_reason="specialist_contractor",
        observability="YES",
        fact_ids=("cpv_main",),
        reason="CPV 45223210 (Stahlbau) exclusif aux échecs, intrants sidérurgiques",
    ),
    FailureCase(
        signal_id="61fe1e4906a4190f544140196e200834ed63da9ead0de5249a8d8f648a17fa66",
        channel_reason="manufacturer",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason="BKP 228 (Äussere Abschlüsse, Sonnenschutz) exclusif aux échecs",
    ),
    FailureCase(
        signal_id="65195148b6959c7b355a8fb61279e66f61a7d03df1578fcb44a4601214650bb0",
        channel_reason="integrated_supplier",
        observability="NO",
        fact_ids=("cpv_main",),
        reason=(
            "CPV 45421130 nomme la menuiserie, qui est **dans** le catalogue de "
            "l'ICP : le code décrit le lot, l'échec tient à l'activité du gagnant"
        ),
    ),
    FailureCase(
        signal_id="7550a394b401eb63281420593961fbd9a6a7a14de9e1d7079398beda27192bc8",
        channel_reason="deliverable_overlap",
        observability="NO",
        fact_ids=("bkp_codes",),
        reason="BKP 273 porte quatre signaux utiles du banc : le recouvrement livrable n'est pas lisible du code",
    ),
    FailureCase(
        signal_id="780564b171374710140f88c5fa596c8fa8c802884ab1ac6d842772707fe734c6",
        channel_reason="deliverable_overlap",
        observability="NO",
        fact_ids=("bkp_codes", "cpv_main"),
        reason="BKP 273.0, même famille que quatre signaux utiles ; CPV 45213331 partagé",
    ),
    FailureCase(
        signal_id="783db7c9dd3b5a9ee73dee5c20cc7d4e2d067d0c28423cf2d5e19339f211a246",
        channel_reason="deliverable_overlap",
        observability="NO",
        fact_ids=("bkp_codes",),
        reason=(
            "BKP 221.5 partagé avec des signaux utiles ; la réserve "
            "« unter Vorbehalt der Kreditgenehmigung » n'existe qu'en texte libre (§31)"
        ),
    ),
    FailureCase(
        signal_id="82a8af8318dad722047a9af26882bc0c4d9ffd17d6f89a85802edc181d21efff",
        channel_reason="specialist_contractor",
        observability="PARTIAL",
        fact_ids=("bkp_codes",),
        reason="BKP 272.2 : la racine 272 porte aussi un signal utile du banc",
    ),
    FailureCase(
        signal_id="8dd986660b5d1dc75e3eb8c194c02e40782641ab94a32be99d00132cce0750af",
        channel_reason="manufacturer",
        observability="PARTIAL",
        fact_ids=("bkp_codes",),
        reason="BKP 215 (Montagebau als Leichtkonstruktion) porte aussi un signal utile",
    ),
    FailureCase(
        signal_id="92587889f66d81f609eb1b5f19fb0ad68a6cbddf77a84ea4aea87fc3789d1b8b",
        channel_reason="specialist_contractor",
        observability="NO",
        fact_ids=("bkp_codes", "cpv_main"),
        reason=(
            "aucun code BKP extrait — l'objet publie « CFC 242 Chauffage » et "
            "l'extracteur ne reconnaît que le marqueur « BKP » ; le CPV 45212421 "
            "désigne un type de bâtiment, pas un métier"
        ),
    ),
    FailureCase(
        signal_id="974a67e479f76edc8bf12e06586b83ce804d46b7f5c431e84c56e3b5689a0c48",
        channel_reason="specialist_contractor",
        observability="NO",
        fact_ids=("bkp_codes", "cpv_main"),
        reason=(
            "aucun code BKP extrait — l'objet publie « 275.00 Schliessanlagen » "
            "sans marqueur ; le CPV 45211200 désigne un type de bâtiment"
        ),
    ),
    FailureCase(
        signal_id="9fe93a3cda25a35118ce8c1dc7109f704d0d2238a8d9b1d11ec207c5773bb3a4",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason="BKP 227 et 285 (peinture) exclusifs aux échecs : filière grossiste peinture",
    ),
    FailureCase(
        signal_id="a7198f485545e2a85fca074b31ebb6c7adac913230f0190b2393b95d30770b3f",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason="BKP 285 (Malerarbeiten) exclusif aux échecs",
    ),
    FailureCase(
        signal_id="b45adc669bf5450a56002d223c466cfee35ff3a6f44e841d8d57e1af272015a6",
        channel_reason="specialist_contractor",
        observability="PARTIAL",
        fact_ids=("cpv_main",),
        reason="CPV 45262670 partagé entre deux échecs et deux signaux utiles",
    ),
    FailureCase(
        signal_id="b6719611719288d19abf485c144c68de50f8866b5ce55451941080d61df60678",
        channel_reason="specialist_contractor",
        observability="NO",
        fact_ids=("cpv_main",),
        reason=(
            "CPV 45214610 désigne un type de bâtiment et porte un signal utile ; "
            "la nature électrique du lot n'existe que dans le titre"
        ),
    ),
    FailureCase(
        signal_id="bbf780f7a760d78b55b08fb8843fa99e57d2db8a4bcccaa0d15af33ba464e0e0",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("bkp_codes", "cpv_main"),
        reason="BKP 285.1 et CPV 45442110 (travaux de peinture) tous deux exclusifs aux échecs",
    ),
    FailureCase(
        signal_id="eb947063b5fc68a3eb45baf5aac677b312dc3b2b36bc5e0882fd508973f2b6de",
        channel_reason="trade_specific_buyer_channel",
        observability="YES",
        fact_ids=("bkp_codes",),
        reason="BKP 285.1 (Malerarbeiten) exclusif aux échecs",
    ),
)


def failure_reason_counts() -> dict[str, int]:
    counts = collections.Counter(case.channel_reason for case in MATCHING_FAILURE_STUDY)
    return {reason: counts[reason] for reason in CHANNEL_REASONS if counts[reason]}


# ─── §20, §32, §33 — ce que Kivou sait du gagnant, et ce qui lui manque ──────────


@dataclasses.dataclass(frozen=True)
class IdentifierScheme:
    """Un schéma d'identifiant observé sur les gagnants du banc.

    La distinction qui compte tient en un booléen : identifier une entreprise
    n'est pas la classer. `SIMAP-VENDOR-ID` et `TED-BT-501` sont des clés de
    plateforme — elles ouvrent une fiche, elles ne disent pas ce qu'on y vend.
    """

    observed: int
    is_industry_classification: bool
    note: str


WINNER_IDENTIFIER_SCHEMES: dict[str, IdentifierScheme] = {
    "SIMAP-VENDOR-ID": IdentifierScheme(
        observed=66,
        is_industry_classification=False,
        note="clé de fournisseur interne à la plateforme SIMAP",
    ),
    "TED-BT-501": IdentifierScheme(
        observed=33,
        is_industry_classification=False,
        note="identifiant national d'organisation publié par TED (BT-501)",
    ),
    "eu": IdentifierScheme(
        observed=1,
        is_industry_classification=False,
        note="identifiant européen ; un seul gagnant du banc en porte un",
    ),
}


@dataclasses.dataclass(frozen=True)
class CompanyField:
    """Un champ d'activité d'entreprise, et sa présence réelle dans le modèle."""

    name: str
    available: bool
    coverage: float
    source: str | None
    note: str


#: §20 — la question posée telle quelle : que sait Kivou de l'activité
#: commerciale du gagnant ? La réponse est un inventaire, pas une intention.
#: `coverage` est mesurée sur les 100 signaux adjugés de SPEC-009C.
COMPANY_ACTIVITY_FIELDS: tuple[CompanyField, ...] = (
    CompanyField(
        name="legal_name",
        available=True,
        coverage=100.0,
        source="winner.parties[].members[].legal_name",
        note="présent partout, et inutilisable comme donnée d'activité (§30)",
    ),
    CompanyField(
        name="country",
        available=True,
        coverage=100.0,
        source="winner.parties[].members[].country",
        note="pays du siège ; ne dit rien de la filière d'achat",
    ),
    CompanyField(
        name="address",
        available=True,
        coverage=100.0,
        source="winner.parties[].members[].address",
        note="adresse postale ; permet d'écrire, pas de qualifier",
    ),
    CompanyField(
        name="identifiers",
        available=True,
        coverage=100.0,
        source="winner.parties[].members[].identifiers",
        note="clés de plateforme uniquement — aucun code d'activité (§20)",
    ),
    CompanyField(
        name="website",
        available=True,
        coverage=6.0,
        source="winner.parties[].members[].website",
        note="six gagnants sur cent ; trop rare pour fonder une classification",
    ),
    CompanyField(
        name="legal_form",
        available=False,
        coverage=0.0,
        source=None,
        note="AG, GmbH, SA n'apparaissent que dans la raison sociale, jamais comme champ",
    ),
    CompanyField(
        name="industry_code_nace",
        available=False,
        coverage=0.0,
        source=None,
        note="aucun code NACE dans le modèle canonique",
    ),
    CompanyField(
        name="industry_code_noga",
        available=False,
        coverage=0.0,
        source=None,
        note="aucun code NOGA dans le modèle canonique",
    ),
    CompanyField(
        name="business_activity",
        available=False,
        coverage=0.0,
        source=None,
        note="aucune description d'activité",
    ),
    CompanyField(
        name="company_size",
        available=False,
        coverage=0.0,
        source=None,
        note="absent",
    ),
    CompanyField(
        name="employee_count",
        available=False,
        coverage=0.0,
        source=None,
        note="absent",
    ),
    CompanyField(
        name="turnover",
        available=False,
        coverage=0.0,
        source=None,
        note="absent",
    ),
    CompanyField(
        name="manufacturer_status",
        available=False,
        coverage=0.0,
        source=None,
        note="aucun champ ne distingue un fabricant d'un poseur",
    ),
    CompanyField(
        name="wholesaler_status",
        available=False,
        coverage=0.0,
        source=None,
        note="aucun champ ne distingue un négoce d'un installateur",
    ),
    CompanyField(
        name="contractor_status",
        available=False,
        coverage=0.0,
        source=None,
        note="le rôle publié vaut « sole » ou « member », jamais un métier",
    ),
)


def winner_activity_field_count() -> int:
    """Combien de champs décrivent l'**activité** du gagnant, et non son identité.

    C'est l'entrée de `channel_verdict` : identité, adresse et clé de plateforme
    ne comptent pas — elles disent à qui écrire, pas ce que l'entreprise achète.
    """
    identity_only = {"legal_name", "country", "address", "identifiers"}
    return sum(
        1
        for field in COMPANY_ACTIVITY_FIELDS
        if field.available and field.name not in identity_only
    )


@dataclasses.dataclass(frozen=True)
class MissingField:
    """Une donnée absente, sa valeur au regard des 23 échecs, et sa provenance possible.

    `failures_addressed` n'est pas une promesse de correction : c'est le nombre
    de cas parmi les 23 où cette donnée aurait décrit le mécanisme documenté.
    """

    name: str
    value: str
    availability: str
    failures_addressed: int
    note: str


#: §32, §33 — le classement se lit contre les 23 échecs, pas contre une intuition
#: de marché. Deux données seulement portent la totalité des cas.
MISSING_INFORMATION: tuple[MissingField, ...] = (
    MissingField(
        name="manufacturer_distributor_installer_classification",
        value="HIGH VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=23,
        note=(
            "la variable exacte que le banc réclame : elle sépare celui qui "
            "achète des intrants de celui qui les produit ou les revend"
        ),
    ),
    MissingField(
        name="winner_business_description",
        value="HIGH VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=23,
        note="une description de produits et prestations couvre les 23 mécanismes documentés",
    ),
    MissingField(
        name="winner_industry_classification_nace_noga",
        value="HIGH VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=20,
        note=(
            "nomme le métier du gagnant ; reste muette sur les trois "
            "recouvrements de livrable, où le métier est justement dans le catalogue"
        ),
    ),
    MissingField(
        name="bkp_trade_semantics_at_three_digits",
        value="HIGH VALUE",
        availability="canonical award data",
        failures_addressed=13,
        note=(
            "le code BKP à trois chiffres est déjà publié et déjà stocké ; seule "
            "sa signification métier manque à la table (21/22/27/28 aujourd'hui)"
        ),
    ),
    MissingField(
        name="cfc_marker_recognition",
        value="MEDIUM VALUE",
        availability="SIMAP",
        failures_addressed=1,
        note=(
            "l'extracteur ne reconnaît que le marqueur « BKP » ; « CFC », son "
            "équivalent romand, laisse le code non extrait — 2 cas sur les 100"
        ),
    ),
    MissingField(
        name="winner_website",
        value="MEDIUM VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=23,
        note="présent à 6 % aujourd'hui ; porte l'activité mais exige une lecture, pas un champ",
    ),
    MissingField(
        name="winner_legal_form",
        value="LOW VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=0,
        note="AG, GmbH ou SA ne distinguent aucun canal d'achat",
    ),
    MissingField(
        name="winner_size_and_turnover",
        value="LOW VALUE",
        availability="EXTERNAL COMPANY ENRICHMENT",
        failures_addressed=0,
        note="la taille ne dit pas si l'entreprise achète ou fabrique",
    ),
)


#: §21, §29 — les faits qui, en principe, pourraient décrire une **filière
#: d'achat**. La liste est étroite à dessein : une variable qui sépare le banc
#: sans décrire le canal (le montant du lot, la source, le pays) est un proxy de
#: taille ou de plateforme, et l'ériger en critère reviendrait à vendre du
#: hasard sous un nom sérieux.
PURCHASE_CHANNEL_RELEVANT_FACTS: frozenset[str] = frozenset(
    {
        "bkp_codes",
        "cpv_main",
        "cpv_additional",
        "trade_domain",
        "trade_domain_source",
        "lot_title",
        "contract_title",
        "contract_description",
        "object_summary",
        "characteristics",
        "need_categories",
        "winner_website",
    }
)

#: §23 — en dessous, l'écart de précision utile entre deux valeurs d'une même
#: variable n'a rien qui ressemble à une séparation.
DISCRIMINATION_THRESHOLD_POINTS = 20.0


def matchability_candidate(name: str, *, spread_points: float | None) -> str:
    """§29, dernière colonne — un fait mérite-t-il d'être retenu pour la suite ?

    Deux conditions cumulatives : il doit séparer les deux populations, et il
    doit décrire le canal d'achat. Une seule des deux ne suffit pas.
    """
    admit_feature(name)
    if spread_points is None:
        return "UNKNOWN"
    if name not in PURCHASE_CHANNEL_RELEVANT_FACTS:
        return "NO"
    return "YES" if spread_points >= DISCRIMINATION_THRESHOLD_POINTS else "NO"
