"""SPEC-009D — l'audit de fraîcheur et d'observabilité du canal d'achat.

Ces tests portent sur les invariants de mesure, pas sur les valeurs mesurées :
un audit dont le compteur est faux ne mesure rien. §41 fixe les invariants
temporels, §42 ceux de l'observabilité — dont le plus important, qui est de
refuser qu'un verdict commercial ou le nom du gagnant redeviennent des
variables d'entrée.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.research.spec009d import (
    CANONICAL_PRE_MATCH_FACTS,
    FORBIDDEN_FEATURES,
    MATCHING_FAILURE_STUDY,
    RecencyRecord,
    admit_feature,
    award_age_bucket,
    channel_verdict,
    contingency,
    control_sample,
    decision_matrix,
    distribution,
    field_coverage,
    just_won,
    observability_rate,
    publication_delay_bucket,
    quality_breakdown,
    recency_verdict,
    sample_label,
    stale_but_recently_published,
)

AS_OF = dt.date(2026, 8, 18)


def record(
    signal_id: str = "s1",
    *,
    award: str | None = None,
    published: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> RecencyRecord:
    return RecencyRecord(
        signal_id=signal_id,
        source="simap",
        as_of=AS_OF,
        award_date=dt.date.fromisoformat(award) if award else None,
        publication_date=dt.date.fromisoformat(published) if published else None,
        contract_start_date=dt.date.fromisoformat(start) if start else None,
        contract_end_date=dt.date.fromisoformat(end) if end else None,
    )


# ─── §41 — invariants temporels ─────────────────────────────────────────────────


def test_award_five_days_ago_falls_in_the_zero_to_seven_bucket():
    assert record(award="2026-08-13").award_age_days == 5
    assert award_age_bucket(5) == "0-7"


def test_award_twenty_days_ago_falls_in_the_fifteen_to_thirty_bucket():
    assert record(award="2026-07-29").award_age_days == 20
    assert award_age_bucket(20) == "15-30"


def test_award_ninety_days_ago_falls_in_the_sixty_one_to_ninety_bucket():
    assert record(award="2026-05-20").award_age_days == 90
    assert award_age_bucket(90) == "61-90"


def test_missing_award_date_is_reported_unknown_and_never_computed():
    r = record(published="2026-08-18")
    assert r.award_date_status == "unknown"
    assert r.award_age_days is None
    assert award_age_bucket(None) == "unknown"


def test_publication_date_is_never_substituted_for_a_missing_award_date():
    """§6 — la substitution transformerait un marché vieux en marché frais."""
    r = record(published="2026-08-18")
    assert r.publication_age_days == 0
    assert r.award_age_days is None
    assert r.publication_delay_days is None
    assert r.award_date_status == "unknown"


def test_publication_delay_is_the_distance_from_award_to_publication():
    r = record(award="2026-06-11", published="2026-08-04")
    assert r.publication_delay_days == 54
    assert publication_delay_bucket(54) == "31-60"
    assert publication_delay_bucket(0) == "same_day"
    assert publication_delay_bucket(1) == "1-7"
    assert publication_delay_bucket(None) == "unknown"


def test_a_recent_publication_over_an_old_award_is_flagged_stale():
    fresh = record("fresh", award="2026-08-11", published="2026-08-14")
    stale = record("stale", award="2026-05-11", published="2026-08-07")
    flagged = stale_but_recently_published([fresh, stale])
    assert [r.signal_id for r in flagged] == ["stale"]


def test_a_contract_ending_within_thirty_days_is_detected():
    r = record(published="2026-08-18", end="2026-09-16")
    assert r.days_until_contract_end == 29
    assert r.is_ending_soon(horizon_days=30)
    assert not record(published="2026-08-18", end="2027-02-05").is_ending_soon(horizon_days=30)


def test_a_contract_already_started_reports_a_negative_distance_to_start():
    r = record(published="2026-08-18", start="2026-07-27")
    assert r.days_to_contract_start == -22
    assert r.has_started


# ─── mesures dérivées ───────────────────────────────────────────────────────────


def test_distribution_uses_nearest_rank_percentiles_on_the_sorted_values():
    assert distribution([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == {
        "n": 10,
        "median": 5,
        "p25": 3,
        "p75": 8,
        "p90": 9,
        "p95": 10,
        "max": 10,
    }


def test_distribution_of_an_empty_series_reports_no_percentile():
    assert distribution([]) == {"n": 0}


def test_quality_breakdown_counts_each_verdict_and_derives_the_four_rates():
    got = quality_breakdown(["A", "A", "B", "C", "D"])
    assert got["n"] == 5
    assert (got["A"], got["B"], got["C"], got["D"]) == (2, 1, 1, 1)
    assert got["useful_precision"] == 60.0
    assert got["actionable_rate"] == 40.0
    assert got["weak_rate"] == 20.0
    assert got["false_rate"] == 20.0
    assert got["sample"] == "reportable"


def test_quality_breakdown_refuses_to_publish_rates_below_five_observations():
    """§11 — sous cinq signaux la précision d'un bucket n'est pas une mesure."""
    got = quality_breakdown(["A", "C"])
    assert got["sample"] == "sample too small"
    assert "useful_precision" not in got


def test_just_won_selects_on_the_award_date_and_ignores_unknown_awards():
    records = [
        record("a", award="2026-08-13"),
        record("b", award="2026-08-01"),
        record("c", published="2026-08-18"),
    ]
    assert [r.signal_id for r in just_won(records, max_age_days=7)] == ["a"]
    assert [r.signal_id for r in just_won(records, max_age_days=30)] == ["a", "b"]


def test_sample_label_marks_the_three_confidence_regimes():
    assert sample_label(9) == "insufficient sample"
    assert sample_label(10) == "indicative only"
    assert sample_label(19) == "indicative only"
    assert sample_label(20) == "reportable"


def test_recency_verdict_is_weak_when_the_award_date_is_often_missing():
    assert (
        recency_verdict(award_date_coverage=45.0, just_won_30_share=10.0, quality_gradient=0.0)
        == "RECENCY NOT RELIABLY OBSERVABLE"
    )


def test_recency_verdict_is_strong_only_with_coverage_freshness_and_a_gradient():
    assert (
        recency_verdict(award_date_coverage=95.0, just_won_30_share=80.0, quality_gradient=12.0)
        == "RECENCY STRONG"
    )


# ─── §42 — invariants d'observabilité ───────────────────────────────────────────


def test_only_canonical_pre_match_facts_are_accepted_as_features():
    assert admit_feature("bkp_codes") == CANONICAL_PRE_MATCH_FACTS["bkp_codes"]
    with pytest.raises(ValueError, match="inconnu"):
        admit_feature("winner_is_a_manufacturer")


def test_the_winner_name_can_never_become_a_channel_feature():
    """§30 — le nom s'affiche, il ne décrit aucune activité."""
    with pytest.raises(ValueError, match="§30"):
        admit_feature("winner_legal_name")


def test_the_gold_verdict_can_never_become_a_feature():
    with pytest.raises(ValueError, match="§26"):
        admit_feature("final_verdict")


def test_a_post_hoc_reviewer_rationale_is_not_a_canonical_fact():
    with pytest.raises(ValueError, match="§26"):
        admit_feature("final_note")


def test_every_forbidden_feature_is_rejected_and_none_is_also_declared_canonical():
    assert set(FORBIDDEN_FEATURES) & set(CANONICAL_PRE_MATCH_FACTS) == set()
    for name in FORBIDDEN_FEATURES:
        with pytest.raises(ValueError):
            admit_feature(name)


def test_field_coverage_denominators_are_the_two_populations_not_the_total():
    signals = {
        "a": {"bkp_codes": ["272"]},
        "b": {"bkp_codes": []},
        "c": {"bkp_codes": ["285"]},
        "d": {"bkp_codes": ["221"]},
    }
    got = field_coverage(
        signals,
        lambda s: bool(s["bkp_codes"]),
        useful_ids={"a", "b"},
    )
    assert got["n"] == 4
    assert got["n_useful"] == 2
    assert got["n_non_useful"] == 2
    assert got["coverage"] == 75.0
    assert got["coverage_useful"] == 50.0
    assert got["coverage_non_useful"] == 100.0


def test_contingency_reports_one_row_per_value_with_its_useful_precision():
    values = {"a": "yes", "b": "yes", "c": "no", "d": "no"}
    got = contingency(values, useful_ids={"a", "c"})
    assert got["yes"] == {"n": 2, "useful": 1, "non_useful": 1, "useful_precision": 50.0}
    assert got["no"] == {"n": 2, "useful": 1, "non_useful": 1, "useful_precision": 50.0}


def test_observability_counts_sum_to_the_population_size():
    got = observability_rate(["YES", "YES", "PARTIAL", "NO"])
    assert got["n"] == 4
    assert got["YES"] + got["PARTIAL"] + got["NO"] == got["n"]
    assert got["yes_rate"] == 50.0
    assert got["partial_rate"] == 25.0
    assert got["not_observable_rate"] == 25.0


def test_observability_rate_refuses_a_value_outside_the_three_allowed():
    with pytest.raises(ValueError, match="MAYBE"):
        observability_rate(["YES", "MAYBE"])


def test_control_sample_is_deterministic_and_matches_the_failure_strata():
    candidates = {
        "u1": ("simap", "general_building"),
        "u2": ("simap", "general_building"),
        "u3": ("ted", "interior_finishing"),
        "u4": ("ted", "interior_finishing"),
    }
    failures = [("simap", "general_building"), ("ted", "interior_finishing")]
    first = control_sample(candidates, failures, size=2)
    assert first == control_sample(candidates, failures, size=2)
    assert first == ("u1", "u3")


def test_control_sample_falls_back_to_signal_id_order_when_a_stratum_is_empty():
    candidates = {"u2": ("ted", "roofing"), "u1": ("ted", "roofing")}
    got = control_sample(candidates, [("simap", "general_building")], size=2)
    assert got == ("u1", "u2")


def test_channel_verdict_is_not_observable_without_winner_activity_data():
    assert (
        channel_verdict(winner_activity_fields=0, fully_observable_rate=43.5)
        == "PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA"
    )


def test_channel_verdict_is_partial_when_most_failures_are_predictable():
    assert (
        channel_verdict(winner_activity_fields=0, fully_observable_rate=80.0)
        == "PURCHASE CHANNEL PARTIALLY OBSERVABLE"
    )


def test_decision_matrix_maps_each_pair_to_a_scenario_and_a_next_step():
    got = decision_matrix(
        "RECENCY WEAK",
        "PURCHASE CHANNEL NOT OBSERVABLE WITH CURRENT DATA",
    )
    assert got["scenario"] == "D"
    assert got["verdict"] == "RECENCY + CHANNEL NOT OBSERVABLE"
    assert got["next_step"] == "rethink MVP signal promise"
    assert (
        decision_matrix("RECENCY STRONG", "PURCHASE CHANNEL OBSERVABLE WITH CURRENT DATA")[
            "scenario"
        ]
        == "A"
    )


# ─── la table d'étude des 23 échecs, confrontée au gold gelé ────────────────────

#: Les artefacts SPEC-009C sont gelés mais **non suivis par git** — le
#: superviseur n'en a pas autorisé le commit. Les tests qui les relisent sont
#: donc conditionnés à leur présence : sur un clone frais ils sont ignorés
#: explicitement, jamais silencieusement verts.
SPEC009C_DIR = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "signal100"
SPEC009C_ARTEFACTS = {
    name: SPEC009C_DIR / name
    for name in ("spec009c_corpus.json", "spec009c_bench.json", "spec009c_gold.json")
}
needs_spec009c = pytest.mark.skipif(
    not all(path.exists() for path in SPEC009C_ARTEFACTS.values()),
    reason="artefacts gelés SPEC-009C absents (non suivis par git, cf. rapport SPEC-009E)",
)


def gold_records() -> list[dict]:
    return json.loads(SPEC009C_ARTEFACTS["spec009c_gold.json"].read_text(encoding="utf-8"))[
        "records"
    ]


@needs_spec009c
def test_the_failure_study_covers_exactly_the_matching_failures_of_the_gold():
    expected = {r["signal_id"] for r in gold_records() if r["primary_failure_layer"] == "matching"}
    assert {case.signal_id for case in MATCHING_FAILURE_STUDY} == expected
    assert len(MATCHING_FAILURE_STUDY) == 23


def test_every_failure_case_cites_only_admissible_canonical_facts():
    for case in MATCHING_FAILURE_STUDY:
        assert case.observability in {"YES", "PARTIAL", "NO"}
        for fact_id in case.fact_ids:
            assert admit_feature(fact_id)


@needs_spec009c
def test_no_failure_case_reclassifies_a_gold_verdict():
    """§3, §40 — l'audit relit le gold, il ne le rejuge pas."""
    verdicts = {r["signal_id"]: r["final_verdict"] for r in gold_records()}
    for case in MATCHING_FAILURE_STUDY:
        assert verdicts[case.signal_id] in {"C", "D"}


# ─── §20, §32, §33 — ce que Kivou sait de l'activité du gagnant, et ce qui manque ─


def test_every_company_activity_field_is_consistently_declared():
    """§20 — l'inventaire doit constater l'absence, pas la contourner."""
    from signals.research.spec009d import COMPANY_ACTIVITY_FIELDS

    assert COMPANY_ACTIVITY_FIELDS
    for field in COMPANY_ACTIVITY_FIELDS:
        assert field.available in {True, False}
        if field.available:
            assert field.source, f"{field.name} déclaré disponible sans source"
        else:
            assert field.coverage == 0.0


def test_missing_information_is_priced_and_sourced():
    """§32, §33 — une donnée manquante sans valeur ni source n'oriente rien."""
    from signals.research.spec009d import MISSING_INFORMATION

    assert MISSING_INFORMATION
    for gap in MISSING_INFORMATION:
        assert gap.value in {"HIGH VALUE", "MEDIUM VALUE", "LOW VALUE"}
        assert gap.availability in {
            "TED",
            "SIMAP",
            "canonical award data",
            "winner identifiers",
            "EXTERNAL COMPANY ENRICHMENT",
        }
        assert gap.failures_addressed <= len(MATCHING_FAILURE_STUDY)


def test_the_winner_identifier_schemes_observed_carry_no_industry_code():
    """§20 — SIMAP-VENDOR-ID et TED-BT-501 identifient, ils ne classifient pas."""
    from signals.research.spec009d import WINNER_IDENTIFIER_SCHEMES

    assert set(WINNER_IDENTIFIER_SCHEMES) == {"SIMAP-VENDOR-ID", "TED-BT-501", "eu"}
    assert all(
        not scheme.is_industry_classification for scheme in WINNER_IDENTIFIER_SCHEMES.values()
    )


def test_channel_relevant_facts_are_a_subset_of_the_canonical_catalog():
    """§21 — une variable ne peut informer le canal d'achat que si elle existe."""
    from signals.research.spec009d import PURCHASE_CHANNEL_RELEVANT_FACTS

    assert PURCHASE_CHANNEL_RELEVANT_FACTS
    assert set(PURCHASE_CHANNEL_RELEVANT_FACTS) <= set(CANONICAL_PRE_MATCH_FACTS)


def test_a_lot_size_proxy_is_never_a_purchase_channel_candidate():
    """Le montant sépare le banc sans rien dire de la filière d'achat."""
    from signals.research.spec009d import PURCHASE_CHANNEL_RELEVANT_FACTS, matchability_candidate

    assert "amount" not in PURCHASE_CHANNEL_RELEVANT_FACTS
    assert matchability_candidate("amount", spread_points=38.0) == "NO"
    assert matchability_candidate("bkp_codes", spread_points=38.0) == "YES"
    assert matchability_candidate("bkp_codes", spread_points=8.3) == "NO"
    assert matchability_candidate("bkp_codes", spread_points=None) == "UNKNOWN"


# ─── §2, §39 — l'audit repose sur les artefacts gelés, et le prouve ─────────────


@needs_spec009c
def test_the_replay_reproduces_the_frozen_bench_exactly():
    """Rejouer le pipeline gelé doit rendre les 110 SHOW et les mêmes dates.

    C'est la précondition de tout le reste : mesurer la fraîcheur sur un
    pipeline qui aurait bougé ne mesurerait rien.
    """
    import datetime as dt

    from signals.research.signal100 import load_rows, workdir
    from signals.research.spec009d_run import assert_precondition, natural_shows

    root = workdir()
    bench = json.loads((root / "spec009c_bench.json").read_text(encoding="utf-8"))
    records = natural_shows(
        load_rows(root / "spec009c_corpus.json"),
        as_of=dt.date.fromisoformat(bench["as_of"]),
    )

    assert len(records) == bench["natural_shows"] == 110
    assert_precondition(records, bench["signals"], bench["natural_shows"])
