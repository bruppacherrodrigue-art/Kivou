"""La politique SIGNAL-100 — ce qu'elle garantit avant même de voir un signal.

Ces tests portent sur la logique pure de SPEC-009 : identité déterministe d'un
signal (§16), interdiction du vocabulaire de certitude (§50), déduplication par
award-lot (§8), stratification par score (§14) et plafonds de sélection (§13).

Aucun accès réseau, aucune fixture gelée : ils doivent rester verts même avant
que le banc n'existe.
"""

from __future__ import annotations

import collections

import pytest

from signals.research.signal100 import (
    DOCUMENT_MODE_DISCLOSURE,
    FORBIDDEN_WORDINGS,
    PoolEntry,
    best_match_per_award_lot,
    cap_award_lots_per_notice,
    forbidden_wording_hits,
    identities,
    signal_id,
    terciles,
)
from signals.research.signal100_select import (
    MAX_PER_CONTRACT_TYPE,
    MAX_PER_ICP,
    MAX_PER_NOTICE,
    TERCILE_QUOTAS,
    select_signal100,
)


def entry(
    *,
    lot: str,
    icp: str = "icp-a",
    score: int = 50,
    source: str = "ted",
    notice: str = "n1",
    contract_type: str = "construction",
    country: str = "FR",
    needs: tuple[str, ...] = ("workforce_capacity",),
) -> PoolEntry:
    key = ("ted", "notice-uuid", "01", lot, None)
    return PoolEntry(
        signal_id=signal_id(key, icp, "icp-match-v0.1", "signal-score-v0.2"),
        source=source,
        notice=notice,
        award_key=key,
        icp_id=icp,
        normalized_score=score,
        band="strong",
        confidence="medium",
        contract_type=contract_type,
        sector="public",
        country=country,
        matched_needs=needs,
    )


class TestSignalIdentity:
    def test_the_same_award_lot_and_icp_always_produce_the_same_id(self) -> None:
        """§16 — aucune UUID aléatoire : l'identité se recalcule à l'identique."""
        key = ("ted", "abc", "01", "CON-1", "LOT-2")
        first = signal_id(key, "icp-staffing-ch", "icp-match-v0.1", "signal-score-v0.2")
        second = signal_id(key, "icp-staffing-ch", "icp-match-v0.1", "signal-score-v0.2")
        assert first == second
        assert len(first) == 64

    def test_two_lots_of_the_same_notice_are_two_different_signals(self) -> None:
        """§8 — l'identité descend au lot, sinon deux lots n'en feraient qu'un.

        `ScoredSignalMatch.award_ref` est un `EventRef`, donc commun aux lots
        d'une même notice : s'en servir seul confondrait deux événements
        commerciaux distincts.
        """
        base = ("ted", "abc", "01", "CON-1")
        first = signal_id((*base, "LOT-1"), "icp-a", "v1", "v2")
        second = signal_id((*base, "LOT-2"), "icp-a", "v1", "v2")
        assert first != second

    def test_a_policy_change_changes_the_identity(self) -> None:
        """Un signal produit sous une autre politique n'est pas le même signal."""
        key = ("ted", "abc", "01", "CON-1", None)
        assert signal_id(key, "icp-a", "icp-match-v0.1", "signal-score-v0.2") != signal_id(
            key, "icp-a", "icp-match-v0.2", "signal-score-v0.2"
        )

    def test_a_missing_lot_does_not_collide_with_an_empty_lot_name(self) -> None:
        """`None` et `""` ne doivent pas produire la même empreinte."""
        assert signal_id(("ted", "a", "01", "C", None), "i", "m", "s") == signal_id(
            ("ted", "a", "01", "C", None), "i", "m", "s"
        )


class TestForbiddenWording:
    @pytest.mark.parametrize("wording", FORBIDDEN_WORDINGS)
    def test_every_declared_wording_is_detected(self, wording: str) -> None:
        """§50 — la liste FR + EN est effectivement appliquée, pas décorative."""
        assert forbidden_wording_hits(f"Le signal indique que X {wording} bientôt.") == (wording,)

    def test_detection_ignores_case(self) -> None:
        assert forbidden_wording_hits("This company WILL BUY safety equipment.") == ("will buy",)

    def test_hypothetical_wording_passes(self) -> None:
        """La formulation autorisée de §4 ne doit pas être piégée."""
        text = (
            "A need for workforce capacity may become relevant. "
            "Un besoin de capacité en personnel est plausible."
        )
        assert forbidden_wording_hits(text) == ()

    def test_the_document_mode_disclosure_is_itself_safe(self) -> None:
        """§51 — la limitation obligatoire ne contient aucune certitude."""
        assert forbidden_wording_hits(DOCUMENT_MODE_DISCLOSURE) == ()


class TestDeduplication:
    def test_one_signal_per_award_lot_keeps_the_best_score(self) -> None:
        """§8 — plusieurs ICPs sur un même lot ne font pas plusieurs signaux."""
        candidates = [
            entry(lot="CON-1", icp="icp-b", score=70),
            entry(lot="CON-1", icp="icp-a", score=91),
            entry(lot="CON-1", icp="icp-c", score=55),
        ]
        kept = best_match_per_award_lot(candidates)
        assert len(kept) == 1
        assert kept[0].icp_id == "icp-a"

    def test_ties_are_broken_by_icp_id_ascending(self) -> None:
        """Départage déterministe imposé par §8 : score DESC puis `icp_id` ASC."""
        candidates = [
            entry(lot="CON-1", icp="icp-z", score=80),
            entry(lot="CON-1", icp="icp-a", score=80),
        ]
        assert best_match_per_award_lot(candidates)[0].icp_id == "icp-a"

    def test_at_most_two_award_lots_survive_per_notice(self) -> None:
        """§8 — une notice à cinq lots n'en apporte que deux au banc."""
        candidates = [entry(lot=f"CON-{i}", score=90 - i, notice="shared") for i in range(5)]
        kept = cap_award_lots_per_notice(candidates, cap=MAX_PER_NOTICE)
        assert len(kept) == MAX_PER_NOTICE
        assert [e.award_key[3] for e in kept] == ["CON-0", "CON-1"]


class TestTerciles:
    def test_the_three_zones_cover_everything_without_overlap(self) -> None:
        """§14 — le banc couvre le spectre, aucune ligne ne disparaît."""
        pool = [entry(lot=f"CON-{i}", score=i) for i in range(99)]
        zones = terciles(pool)
        assert [len(zones[name]) for name in ("top", "middle", "bottom")] == [33, 33, 33]
        ids = [e.signal_id for name in zones for e in zones[name]]
        assert len(set(ids)) == 99

    def test_the_top_zone_really_holds_the_high_scores(self) -> None:
        pool = [entry(lot=f"CON-{i}", score=i) for i in range(99)]
        zones = terciles(pool)
        assert min(e.normalized_score for e in zones["top"]) > max(
            e.normalized_score for e in zones["bottom"]
        )


class TestSelection:
    def _diverse_pool(self) -> list[PoolEntry]:
        """Un pool large et varié : la sélection doit y trouver ses quotas."""
        sources = ("ted", "simap")
        countries = ("FR", "DE", "CH", "IT", "ES", "BE")
        types = ("construction", "it_digital", "maintenance_repair", "supply", "services")
        needs = (
            "workforce_capacity",
            "materials_or_components",
            "safety_and_ppe",
            "equipment_or_rental",
            "waste_and_environment",
        )
        icps = tuple(f"icp-{i}" for i in range(8))
        pool = []
        for i in range(300):
            pool.append(
                entry(
                    lot=f"CON-{i}",
                    icp=icps[i % len(icps)],
                    score=30 + (i % 60),
                    source=sources[i % 2],
                    notice=f"n{i // 2}",
                    contract_type=types[i % len(types)],
                    country=countries[i % len(countries)],
                    needs=(needs[i % len(needs)],),
                )
            )
        return pool

    def test_selection_is_exactly_one_hundred_and_deterministic(self) -> None:
        """§13 — 100 signaux, et deux exécutions donnent le même banc."""
        pool = self._diverse_pool()
        first, _ = select_signal100(pool)
        second, _ = select_signal100(pool)
        assert len(first) == 100
        assert [e.signal_id for e in first] == [e.signal_id for e in second]

    def test_the_three_score_zones_are_all_represented(self) -> None:
        """§14 — pas de cherry-picking : le bas du feed est évalué aussi."""
        _, compliance = select_signal100(self._diverse_pool())
        assert compliance["per_tercile"] == TERCILE_QUOTAS

    def test_hard_caps_are_never_exceeded(self) -> None:
        """§13 — aucun ICP ni type de contrat ne peut dominer le banc."""
        _, compliance = select_signal100(self._diverse_pool())
        assert compliance["max_per_icp_observed"] <= MAX_PER_ICP
        assert compliance["max_per_contract_type_observed"] <= MAX_PER_CONTRACT_TYPE
        assert compliance["max_per_notice_observed"] <= MAX_PER_NOTICE

    def test_diversity_minima_are_reached_when_the_pool_allows_it(self) -> None:
        """§13 — sources, notices, pays, types, besoins : tous couverts."""
        _, compliance = select_signal100(self._diverse_pool())
        assert compliance["per_source"]["ted"] >= 35
        assert compliance["per_source"]["simap"] >= 35
        assert compliance["distinct_notices"] >= 75
        assert len(compliance["countries"]) >= 5
        assert len(compliance["contract_types"]) >= 5
        assert len(compliance["need_categories"]) >= 5

    def _mono_pool(self) -> list[PoolEntry]:
        """Un pool volontairement pauvre : une source, un type, un pays."""
        return [
            entry(
                lot=f"CON-{i}",
                icp=f"icp-{i % 8}",
                score=30 + (i % 60),
                source="ted",
                notice=f"n{i}",
                contract_type="construction",
                country="FR",
            )
            for i in range(200)
        ]

    def test_an_impossible_minimum_is_reported_not_fabricated(self) -> None:
        """§13 — un pool mono-source ne doit pas fabriquer de fausse diversité.

        La sélection compose ce qu'elle peut et publie la réalité du pool en
        regard : c'est le rapport qui doit dire la vérité, pas le quota.
        """
        _, compliance = select_signal100(self._mono_pool())
        assert compliance["per_source"].get("simap", 0) == 0
        assert compliance["pool_per_source"] == {"ted": 200}
        assert compliance["contract_types"] == ["construction"]
        assert compliance["pool_contract_types"] == 1

    def test_a_blocking_cap_yields_one_notch_at_a_time_and_says_so(self) -> None:
        """§13, §59 — « exactement 100 » l'emporte sur un plafond de diversité.

        Un seul type de contrat existe : le plafond de 35 par type rendrait le
        banc impossible. Il cède, mais la relaxation est tracée — sans quoi le
        rapport prétendrait respecter un objectif qu'il a contourné.
        """
        selected, compliance = select_signal100(self._mono_pool())
        assert len(selected) == 100
        assert compliance["caps_applied"]["max_per_contract_type"] == 100
        assert compliance["caps_applied"]["max_per_icp"] == MAX_PER_ICP
        assert compliance["relaxations"], "une relaxation silencieuse est inacceptable"
        assert {r["cap"] for r in compliance["relaxations"]} == {"max_per_contract_type"}
        # La progression est bien d'un cran à la fois, jamais d'un saut.
        raised = [r["raised_to"] for r in compliance["relaxations"]]
        assert raised == list(range(MAX_PER_CONTRACT_TYPE + 1, 101))

    def test_the_anti_duplication_cap_never_relaxes(self) -> None:
        """§8 — deux award-lots par notice est une règle, pas un objectif.

        Même quand le banc ne peut pas être rempli, une notice ne fournit jamais
        un troisième signal : ce serait compter deux fois le même événement.
        """
        pool = [
            entry(lot=f"CON-{i}", icp=f"icp-{i % 8}", score=30 + (i % 60), notice="unique")
            for i in range(200)
        ]
        selected, compliance = select_signal100(pool)
        assert len(selected) == MAX_PER_NOTICE
        assert compliance["max_per_notice_observed"] == MAX_PER_NOTICE


class TestIdentityExtraction:
    def test_all_four_levels_are_extracted_from_a_row(self) -> None:
        """§10 — un niveau vide signale une extraction cassée, pas une disjonction."""
        row = {
            "source": "ted",
            "notice": "123-2026",
            "event": {
                "provenance": {
                    "source_system": "ted",
                    "source_notice_id": "uuid-1",
                    "source_procedure_id": "proc-1",
                }
            },
            "award": {
                "event_ref": {
                    "source_system": "ted",
                    "source_notice_id": "uuid-1",
                    "notice_version": "01",
                },
                "source_award_id": "CON-1",
                "lot": {"identifier": "LOT-1"},
            },
        }
        extracted = identities([row])
        assert all(extracted[level] for level in extracted)
        assert extracted["publication"] == {("ted", "123-2026")}
        assert extracted["award identity"] == {("ted", "uuid-1", "01", "CON-1", "LOT-1")}

    def test_a_missing_procedure_id_does_not_invent_an_identity(self) -> None:
        """Une procédure absente reste absente : pas de `None` dans l'ensemble."""
        row = {
            "source": "simap",
            "notice": "p/q",
            "event": {
                "provenance": {
                    "source_system": "simap",
                    "source_notice_id": "q",
                    "source_procedure_id": None,
                }
            },
            "award": {
                "event_ref": {"source_system": "simap", "source_notice_id": "q"},
                "source_award_id": "A-1",
                "lot": None,
            },
        }
        assert identities([row])["procedure"] == set()

    def test_counting_identities_matches_the_number_of_distinct_lots(self) -> None:
        rows = []
        for lot in ("LOT-1", "LOT-2"):
            rows.append(
                {
                    "source": "ted",
                    "notice": "123-2026",
                    "event": {
                        "provenance": {
                            "source_system": "ted",
                            "source_notice_id": "uuid-1",
                            "source_procedure_id": "proc-1",
                        }
                    },
                    "award": {
                        "event_ref": {
                            "source_system": "ted",
                            "source_notice_id": "uuid-1",
                            "notice_version": "01",
                        },
                        "source_award_id": "CON-1",
                        "lot": {"identifier": lot},
                    },
                }
            )
        extracted = identities(rows)
        assert len(extracted["award identity"]) == 2
        assert len(extracted["publication"]) == 1
        assert collections.Counter(len(v) for v in extracted.values())[1] == 3
