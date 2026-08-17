"""La décomposition du feed par client et la sélection de wedge (SPEC-009B §50).

Ce que ces tests protègent :

* **Un feed client n'est pas amputé par un autre client.** SPEC-009 mettait les
  huit ICPs en concurrence sur chaque award-lot ; SPEC-009B défait cette
  concurrence, et c'est précisément ce qui a rendu visibles trois feeds
  spécialisés que le banc global effaçait entièrement.
* **L'échantillonnage est aveugle et déterministe.** Il n'utilise que l'ICP, la
  zone de score, la source et le `signal_id` — jamais le gold, jamais un verdict
  antérieur. Sans cela, la précision mesurée ne voudrait rien dire.
* **Le classement GREEN/AMBER/RED fait ce qu'il dit**, y compris ses refus.

Aucun accès réseau : tout part des fixtures gelées.
"""

from __future__ import annotations

import ast
import collections
import json
import pathlib
from typing import Final

import pytest

from signals.research.wedge import (
    AMBER,
    FULL_REVIEW_CEILING,
    GREEN,
    MIN_FOR_LOW_SAMPLE,
    MIN_FOR_RATE,
    STRATUM_QUOTAS,
    FeedEntry,
    cap_per_notice,
    classify,
    cross_icp_dedup_impact,
    sample_for_review,
    strata,
)

FIXTURES = pathlib.Path("tests/fixtures/signal100")
WEDGE_GOLD = FIXTURES / "wedge_gold.json"

REFERENCE_ICPS = (
    "icp-staffing-ch",
    "icp-plant-hire-ch",
    "icp-materials-eu",
    "icp-ppe-safety-ch",
    "icp-waste-ch",
    "icp-subcontracting-eu",
    "icp-national-supplier",
    "icp-remote-specialist",
)


def entry(
    *,
    lot: str = "CON-1",
    icp: str = "icp-a",
    score: int = 50,
    source: str = "ted",
    notice: str = "n1",
    decision: str = "show",
    contract_type: str = "construction",
    needs: tuple[str, ...] = ("materials_or_components",),
) -> FeedEntry:
    return FeedEntry(
        signal_id=f"{icp}-{lot}-{notice}",
        icp_id=icp,
        award_key=("ted", "uuid", "01", lot, None),
        source=source,
        notice=notice,
        decision=decision,
        normalized_score=score,
        band="strong",
        confidence="medium",
        contract_type=contract_type,
        sector="public",
        country="CH",
        matched_needs=needs,
        has_amount=True,
        has_operational_timing=True,
    )


class TestNoCrossIcpDedup:
    """§4 — un client garde son signal même si un autre client « gagne » le même marché."""

    def test_the_same_award_lot_appears_in_every_matching_feed(self) -> None:
        entries = [entry(icp=name, lot="CON-1") for name in ("icp-a", "icp-b", "icp-c")]
        feeds: dict[str, list[FeedEntry]] = collections.defaultdict(list)
        for item in entries:
            feeds[item.icp_id].append(item)
        assert len(feeds) == 3
        assert all(len(v) == 1 for v in feeds.values())
        assert len({tuple(e.award_key) for e in entries}) == 1

    def test_the_dedup_impact_measures_what_the_global_bench_destroyed(self) -> None:
        """§8 — la mesure qui dit si les ICPs larges écrasaient les spécialisés."""
        feeds = {
            "icp-broad": [entry(icp="icp-broad", lot=f"C{i}", notice=f"n{i}") for i in range(10)],
            "icp-narrow": [entry(icp="icp-narrow", lot=f"C{i}", notice=f"n{i}") for i in range(10)],
        }
        survivors = {e.signal_id for e in feeds["icp-broad"]}
        impact = cross_icp_dedup_impact(feeds, survivors)
        assert impact["icp-broad"]["survival_rate"] == 100.0
        assert impact["icp-narrow"]["raw_show_pairs"] == 10
        assert impact["icp-narrow"]["surviving_signal100"] == 0
        assert impact["icp-narrow"]["survival_rate"] == 0.0


class TestWithinFeedRules:
    def test_one_signal_per_award_lot_within_an_icp(self) -> None:
        """Un couple award-lot × ICP est unique par construction du pipeline."""
        assert len({e.signal_id for e in [entry(lot="CON-1"), entry(lot="CON-2")]}) == 2

    def test_at_most_two_award_lots_per_notice(self) -> None:
        """§4 — la règle anti-duplication de SPEC-009, appliquée par feed."""
        candidates = [entry(lot=f"CON-{i}", score=90 - i, notice="shared") for i in range(6)]
        kept = cap_per_notice(candidates)
        assert len(kept) == 2
        assert [e.award_key[3] for e in kept] == ["CON-0", "CON-1"]

    def test_the_notice_cap_is_deterministic_by_score_then_id(self) -> None:
        candidates = [entry(lot=f"CON-{i}", score=50, notice="shared") for i in range(5)]
        first = [e.signal_id for e in cap_per_notice(candidates)]
        second = [e.signal_id for e in cap_per_notice(list(reversed(candidates)))]
        assert first == second

    def test_different_notices_are_not_capped_against_each_other(self) -> None:
        candidates = [entry(lot=f"CON-{i}", notice=f"n{i}") for i in range(6)]
        assert len(cap_per_notice(candidates)) == 6


class TestSampling:
    def _feed(self, count: int) -> list[FeedEntry]:
        return [entry(lot=f"CON-{i}", notice=f"n{i}", score=30 + (i % 60)) for i in range(count)]

    def test_a_feed_under_ten_signals_yields_no_rate(self) -> None:
        """§11 — sous dix signaux, aucun taux de précision officiel."""
        sample, status = sample_for_review(self._feed(9))
        assert sample == []
        assert status == "INSUFFICIENT SAMPLE"

    def test_a_feed_between_ten_and_nineteen_is_reviewed_whole_but_flagged(self) -> None:
        sample, status = sample_for_review(self._feed(14))
        assert len(sample) == 14
        assert status == "LOW SAMPLE"

    def test_a_feed_between_twenty_and_forty_is_reviewed_whole(self) -> None:
        sample, status = sample_for_review(self._feed(28))
        assert len(sample) == 28
        assert status == "OK"

    def test_a_larger_feed_is_capped_at_forty_across_three_score_zones(self) -> None:
        """§11, §12 — 14 haut / 13 milieu / 13 bas, jamais les 40 meilleurs scores."""
        feed = self._feed(200)
        sample, status = sample_for_review(feed)
        assert len(sample) == FULL_REVIEW_CEILING
        assert status == "OK"
        zones = strata(cap_per_notice([e for e in feed if e.decision == "show"]))
        picked = {e.signal_id for e in sample}
        counts = {
            name: len(picked & {e.signal_id for e in entries}) for name, entries in zones.items()
        }
        assert counts == STRATUM_QUOTAS

    def test_sampling_is_deterministic(self) -> None:
        feed = self._feed(200)
        assert [e.signal_id for e in sample_for_review(feed)[0]] == [
            e.signal_id for e in sample_for_review(list(reversed(feed)))[0]
        ]

    def test_sampling_never_reads_a_verdict(self) -> None:
        """§12 — la sélection est aveugle : elle ne peut pas lire ce qui n'existe pas.

        `FeedEntry` ne porte aucun champ de qualité — ni gold, ni verdict LLM, ni
        commentaire. Le cherry-picking est interdit par la structure de données,
        pas seulement par la consigne.
        """
        fields = set(FeedEntry.__dataclass_fields__)
        for forbidden in ("gold", "verdict", "gold_verdict", "quality", "llm_verdict", "note"):
            assert forbidden not in fields

    def test_only_show_signals_are_sampled(self) -> None:
        feed = self._feed(30) + [
            entry(lot=f"BL-{i}", notice=f"b{i}", decision="borderline") for i in range(20)
        ]
        sample, _ = sample_for_review(feed)
        assert len(sample) == 30


BASE_METRICS: Final[dict] = {
    "reviewed": 40,
    "useful_precision": 90.0,
    "false_rate": 2.0,
    "critical_false": 0,
    "factual_integrity": 100.0,
    "proof_coverage": 100.0,
    "top10_useful_precision": 95.0,
    "natural_show_volume": 50,
}


class TestClassification:
    def test_a_clean_wedge_is_green(self) -> None:
        assert classify(dict(BASE_METRICS))[0] == "GREEN"

    def test_a_single_critical_false_signal_forces_red(self) -> None:
        """§37 — un faux critique disqualifie, quel que soit le reste."""
        verdict, reasons = classify({**BASE_METRICS, "critical_false": 1})
        assert verdict == "RED"
        assert any("critique" in r for r in reasons)

    def test_precision_under_seventy_five_is_red(self) -> None:
        assert classify({**BASE_METRICS, "useful_precision": 74.99})[0] == "RED"

    def test_the_amber_band_is_seventy_five_to_eighty_five(self) -> None:
        """§36 — la bande intermédiaire, bornes comprises."""
        assert classify({**BASE_METRICS, "useful_precision": 75.0})[0] == "AMBER"
        assert classify({**BASE_METRICS, "useful_precision": 84.99})[0] == "AMBER"
        assert classify({**BASE_METRICS, "useful_precision": 85.0})[0] == "GREEN"

    def test_green_quality_with_thin_volume_is_amber_not_green(self) -> None:
        """§36 — la qualité ne suffit pas : un wedge sans volume n'est pas lançable."""
        verdict, reasons = classify({**BASE_METRICS, "natural_show_volume": 5})
        assert verdict == "AMBER"
        assert any("volume naturel" in r for r in reasons)

    def test_a_false_rate_above_ten_percent_is_red(self) -> None:
        assert classify({**BASE_METRICS, "useful_precision": 80.0, "false_rate": 11.0})[0] == "RED"

    def test_under_ten_reviewed_is_insufficient_not_red(self) -> None:
        """Ne pas savoir n'est pas la même chose que savoir que c'est mauvais."""
        verdict, _ = classify({**BASE_METRICS, "reviewed": 9, "useful_precision": 0.0})
        assert verdict == "INSUFFICIENT SAMPLE"

    def test_the_gates_match_the_spec_numbers(self) -> None:
        assert GREEN["useful_precision"] == 85.0
        assert GREEN["false_rate"] == 5.0
        assert GREEN["top10_useful_precision"] == 90.0
        assert GREEN["natural_show_volume"] == 15
        assert GREEN["reviewed"] == 20
        assert AMBER["useful_precision_min"] == 75.0
        assert AMBER["false_rate"] == 7.5
        assert AMBER["reviewed"] == 15
        assert MIN_FOR_RATE == 20
        assert MIN_FOR_LOW_SAMPLE == 10


@pytest.mark.skipif(not WEDGE_GOLD.exists(), reason="l'analyse SPEC-009B n'a pas été produite")
class TestFrozenWedgeAnalysis:
    @staticmethod
    def _load() -> dict:
        return json.loads(WEDGE_GOLD.read_text(encoding="utf-8"))

    def test_the_eight_reference_feeds_are_all_profiled(self) -> None:
        """§7 — huit feeds clients reconstruits séparément."""
        profiles = self._load()["feed_profiles"]
        assert set(profiles) == set(REFERENCE_ICPS)
        assert sum(p["pairs_total"] for p in profiles.values()) == 6400

    def test_the_frozen_decision_totals_match_spec009(self) -> None:
        """§5 — les entrées gelées se reproduisent exactement."""
        profiles = self._load()["feed_profiles"]
        assert sum(p["show"] for p in profiles.values()) == 553
        assert sum(p["borderline"] for p in profiles.values()) == 428
        assert sum(p["exclude"] for p in profiles.values()) == 4198
        assert sum(p["insufficient_data"] for p in profiles.values()) == 1221

    def test_three_specialised_feeds_were_entirely_erased_by_the_global_bench(self) -> None:
        """§8 — le résultat qui justifie à lui seul la doctrine du feed par client."""
        impact = self._load()["cross_icp_dedup_impact"]
        for icp in ("icp-staffing-ch", "icp-ppe-safety-ch", "icp-plant-hire-ch"):
            assert impact[icp]["raw_show_pairs"] > 0
            assert impact[icp]["surviving_signal100"] == 0
            assert impact[icp]["survival_rate"] == 0.0

    def test_existing_gold_is_reused_by_exact_pair_identity(self) -> None:
        """§16 — un couple déjà adjugé n'est jamais rejugé."""
        payload = self._load()
        assert payload["gold_origin"] == {"spec009": 44, "spec009b": 192}
        reused = [r for r in payload["records"] if r["gold_origin"] != "spec009b"]
        frozen = {
            r["signal_id"]: r["final_verdict"]
            for r in json.loads((FIXTURES / "signal100_gold.json").read_text(encoding="utf-8"))[
                "records"
            ]
        }
        for record in reused:
            assert record["gold_verdict"] == frozen[record["signal_id"]]

    def test_the_denominators_add_up(self) -> None:
        payload = self._load()
        assert payload["reviewed"] == len(payload["records"]) == 236
        assert sum(payload["composition"].values()) == 236
        assert sum(payload["gold_origin"].values()) == 236

    def test_the_commercial_doctrine_stayed_stable(self) -> None:
        """§17 — sans ce gate, un mauvais résultat pourrait n'être qu'un désaccord."""
        agreement = self._load()["agreement"]
        assert agreement["agreement_within_one_grade_rate"] >= 90.0
        assert agreement["new_signals"] == 192
        assert agreement["arbitrations"] == 35

    def test_no_feed_breaks_its_own_anti_duplication_rules(self) -> None:
        """§4 — un signal par award-lot, deux award-lots par notice, dans chaque feed."""
        records = self._load()["records"]
        per_icp: dict[str, list[dict]] = collections.defaultdict(list)
        for record in records:
            per_icp[record["icp_id"]].append(record)
        for icp, rows in per_icp.items():
            keys = [(tuple(r["award_key"]), r["icp_id"]) for r in rows]
            assert len(keys) == len(set(keys)), icp
            per_notice = collections.Counter((r["source"], r["notice"]) for r in rows)
            assert max(per_notice.values()) <= 2, icp

    def test_every_failing_signal_names_one_layer(self) -> None:
        for record in self._load()["records"]:
            failing = record["gold_verdict"] in ("C", "D")
            assert (record["primary_failure_layer"] is not None) == failing, record["signal_id"]

    def test_no_sampled_feed_exceeds_the_review_ceiling(self) -> None:
        counts = collections.Counter(r["icp_id"] for r in self._load()["records"])
        assert max(counts.values()) <= FULL_REVIEW_CEILING
        assert "icp-waste-ch" not in counts


class TestEnginesUntouched:
    """§6 — SPEC-009B mesure et segmente ; elle ne corrige rien."""

    def test_the_wedge_module_imports_no_engine_internals(self) -> None:
        tree = ast.parse(pathlib.Path("src/signals/research/wedge.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            for engine in ("signals.matching", "signals.needs", "signals.understanding"):
                assert engine not in module, f"wedge.py importe {engine}"

    def test_the_frozen_engine_versions_have_not_moved(self) -> None:
        from signals.matching import (
            MATCH_POLICY_VERSION,
            REFERENCE_ICP_LIBRARY_VERSION,
            SCORE_POLICY_VERSION,
        )
        from signals.needs import ENGINE_VERSION as NEED_VERSION

        assert NEED_VERSION == "need-graph-v0.1"
        assert MATCH_POLICY_VERSION == "icp-match-v0.1"
        assert SCORE_POLICY_VERSION == "signal-score-v0.2"
        assert REFERENCE_ICP_LIBRARY_VERSION == "reference-icps-v0.1"
