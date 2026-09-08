"""SPEC-009E §26–§28 — les invariants de l'étude France.

Les chiffres eux-mêmes vivent dans `spec009e_france.json`. Ces tests portent sur
l'instrument : un dénominateur faux transformerait une couverture de 27 % en
promesse produit.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.research.spec009e import (
    MINIMUM_FRANCE_SAMPLE,
    NOTIFICATION_AGE_BUCKETS,
    TARGET_FRANCE_SAMPLE,
    AwardFacts,
    fact_coverage,
    notification_breakdown,
    payload_form_counts,
    publication_delay_summary,
    recency_breakdown,
    sample_verdict,
)

AS_OF = dt.date(2026, 8, 18)


def facts(**overrides) -> AwardFacts:
    base = {
        "signal_key": "boamp:26-1:CON-0001",
        "source": "boamp",
        "notice": "26-1",
        "award_date": None,
        "publication_date": AS_OF,
        "contract_signature_date": None,
        "contract_notification_date": None,
        "winner_name": "Entreprise",
        "winner_siret": None,
        "buyer_name": "Acheteur",
        "buyer_siret": None,
        "amount": None,
        "currency": None,
        "cpv": "45000000",
        "lot": "LOT-0001",
        "procedure_id": "PROC-1",
        "contract_id": "CON-0001",
        "place_known": False,
    }
    base.update(overrides)
    return AwardFacts(**base)


# ─── §28 — la couverture factuelle ──────────────────────────────────────────────


def test_coverage_is_reported_over_the_whole_sample_not_over_the_present_values():
    sample = [facts(winner_siret="1" * 14), facts(signal_key="b", winner_siret=None)]
    coverage = fact_coverage(sample)
    assert coverage["winner_siret"]["known"] == 1
    assert coverage["winner_siret"]["n"] == 2
    assert coverage["winner_siret"]["known_pct"] == 50.0


def test_every_declared_fact_appears_in_the_coverage_even_when_never_present():
    coverage = fact_coverage([facts()])
    for field in (
        "winner_name",
        "winner_siret",
        "buyer_name",
        "buyer_siret",
        "amount",
        "currency",
        "cpv",
        "award_date",
        "publication_date",
        "contract_signature_date",
        "lot",
        "procedure_id",
        "contract_id",
        "place_known",
    ):
        assert field in coverage, f"{field} absent de l'inventaire"
    assert coverage["winner_siret"]["known"] == 0


def test_an_empty_sample_reports_no_percentage_rather_than_a_division_by_zero():
    coverage = fact_coverage([])
    assert coverage["winner_siret"] == {"n": 0, "known": 0, "known_pct": None}


# ─── §26 — la fraîcheur ─────────────────────────────────────────────────────────


def test_the_recency_breakdown_counts_every_award_exactly_once():
    sample = [
        facts(signal_key="a", award_date=dt.date(2026, 8, 13)),
        facts(signal_key="b", award_date=dt.date(2026, 7, 1)),
        facts(signal_key="c", award_date=dt.date(2026, 4, 1)),
        facts(signal_key="d", award_date=None),
    ]
    breakdown = recency_breakdown(sample, as_of=AS_OF)
    assert breakdown["n"] == 4
    assert sum(breakdown["statuses"].values()) == 4
    assert breakdown["statuses"]["recent_award"] == 1
    assert breakdown["statuses"]["aging_award"] == 1
    assert breakdown["statuses"]["stale_award"] == 1
    assert breakdown["statuses"]["recently_published_award"] == 1


def test_the_recent_award_share_is_the_headline_product_characteristic():
    sample = [facts(signal_key=str(i), award_date=dt.date(2026, 8, 13)) for i in range(3)]
    sample += [facts(signal_key=f"x{i}", award_date=None) for i in range(7)]
    breakdown = recency_breakdown(sample, as_of=AS_OF)
    assert breakdown["recent_award_pct"] == 30.0


def test_an_invalid_award_date_never_counts_as_recent():
    sample = [facts(signal_key="sentinel", award_date=dt.date(2000, 1, 1))]
    breakdown = recency_breakdown(sample, as_of=AS_OF)
    assert breakdown["statuses"]["invalid_award_date"] == 1
    assert breakdown["recent_award_pct"] == 0.0


def test_the_publication_delay_summary_only_uses_awards_that_carry_both_dates():
    sample = [
        facts(signal_key="a", award_date=dt.date(2026, 7, 1), publication_date=AS_OF),
        facts(signal_key="b", award_date=None, publication_date=AS_OF),
    ]
    summary = publication_delay_summary(sample)
    assert summary["n"] == 1
    assert summary["median"] == 48


def test_a_delay_summary_without_any_pair_reports_nothing_rather_than_zero():
    assert publication_delay_summary([facts()]) == {"n": 0}


# ─── §27 — la taille de l'échantillon ───────────────────────────────────────────


def test_the_sample_verdict_follows_the_two_declared_thresholds():
    assert TARGET_FRANCE_SAMPLE == 100
    assert MINIMUM_FRANCE_SAMPLE == 50
    assert sample_verdict(923) == "target reached"
    assert sample_verdict(100) == "target reached"
    assert sample_verdict(60) == "minimum reached, documented shortfall"
    assert sample_verdict(49) == "insufficient sample"


# ─── §21 — ce qui est écarté est compté ─────────────────────────────────────────


def test_the_discarded_payload_forms_are_counted_not_hidden():
    records = [
        {"donnees": json.dumps({"EFORMS": {"ContractAwardNotice": {}}})},
        {"donnees": json.dumps({"FNSimple": {}})},
        {"donnees": json.dumps({"MAPA": {}})},
    ]
    counts = payload_form_counts(records)
    assert counts["EFORMS"] == 1
    assert counts["FNSimple"] == 1
    assert counts["MAPA"] == 1
    assert sum(counts.values()) == 3


# ─── l'artefact gelé, quand il est présent ──────────────────────────────────────

ARTEFACT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "france"
    / "spec009e_france.json"
)

needs_artefact = pytest.mark.skipif(
    not ARTEFACT.exists(),
    reason="mesure France non produite (lancer signals.research.spec009e_run)",
)


@needs_artefact
def test_the_frozen_france_measurement_is_internally_consistent():
    payload = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    recency = payload["recency"]
    assert sum(recency["statuses"].values()) == recency["n"]
    assert recency["n"] == payload["sample"]["award_lots"]
    for field, row in payload["fact_coverage"].items():
        assert row["known"] <= row["n"], field
        assert row["n"] == payload["sample"]["award_lots"], field


@needs_artefact
def test_the_frozen_france_sample_meets_the_declared_minimum():
    payload = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    assert payload["sample"]["award_lots"] >= MINIMUM_FRANCE_SAMPLE
    assert payload["sample"]["verdict"] in {
        "target reached",
        "minimum reached, documented shortfall",
    }


# ─── R1 §4 — la fraîcheur de notification, mesurée à part de la décision ───────


def test_the_notification_buckets_are_the_ones_r1_asks_for():
    assert NOTIFICATION_AGE_BUCKETS == (7, 30, 60, 90)


def test_notification_ages_are_counted_cumulatively_per_bucket():
    sample = [
        facts(signal_key="a", contract_notification_date=dt.date(2026, 8, 15)),  # 3 j
        facts(signal_key="b", contract_notification_date=dt.date(2026, 8, 1)),  # 17 j
        facts(signal_key="c", contract_notification_date=dt.date(2026, 7, 1)),  # 48 j
        facts(signal_key="d", contract_notification_date=dt.date(2026, 6, 1)),  # 78 j
        facts(signal_key="e", contract_notification_date=None),
    ]
    got = notification_breakdown(sample, as_of=AS_OF)
    assert got["n"] == 5
    assert got["known"] == 4
    assert got["within"]["7"] == 1
    assert got["within"]["30"] == 2
    assert got["within"]["60"] == 3
    assert got["within"]["90"] == 4


def test_an_absent_notification_date_never_counts_in_any_bucket():
    got = notification_breakdown([facts()], as_of=AS_OF)
    assert got["known"] == 0
    assert set(got["within"].values()) == {0}


def test_a_notification_date_produces_the_notified_status_when_the_award_is_unknown():
    sample = [facts(signal_key="a", contract_notification_date=dt.date(2026, 8, 15))]
    got = recency_breakdown(sample, as_of=AS_OF)
    assert got["statuses"]["recently_notified_contract"] == 1
    assert got["recent_award_pct"] == 0.0


def test_a_known_award_date_still_wins_over_a_notification_date():
    """R1 §3 — RECENT_AWARD n'est pas affaibli par la nouvelle mesure."""
    sample = [
        facts(
            signal_key="a",
            award_date=dt.date(2026, 8, 13),
            contract_notification_date=dt.date(2026, 8, 15),
        )
    ]
    got = recency_breakdown(sample, as_of=AS_OF)
    assert got["statuses"]["recent_award"] == 1
    assert got["recent_award_pct"] == 100.0


# ─── R1 §6 puis R2 §6 — le volume hebdomadaire vient du recensement ───────────
#
# R1 exposait ces nombres via `france_product_timing`, que R2 remplace par
# `france_capacity` — lequel encadre en plus le comptage unique. L'invariant
# protégé est inchangé : un échantillon plafonné ne s'extrapole jamais.


def capacity_payload(*, probe=None, linkage=None):
    from signals.research.spec009e_run import france_capacity

    return france_capacity(
        {
            "inputs": {"window": {"since": "2026-08-11", "until": "2026-08-18"}},
            "recency": {"statuses": {"recent_award": 45}},
            "decp_probe": probe,
        },
        linkage,
    )


LINKAGE = {
    "boamp_candidates_tested": 45,
    "boamp_linkable": 37,
    "decp_candidates_returned": 8,
    "strong": 4,
    "probable": 1,
    "unresolved": 32,
    "conflicts": 2,
    "decoys_rejected": 2,
    "strong_link_agreement": {"cpv": 3},
    "scope": "test",
    "entries": [{"winner_named": True} for _ in range(45)],
}


def test_the_weekly_notified_volume_comes_from_the_portal_census():
    """Le recensement portail compte tout ; l'échantillon gelé est plafonné."""
    got = capacity_payload(probe={"current": {"notified_within_7d": 383}}, linkage=LINKAGE)
    raw = got["A_raw_public_events_per_week"]
    assert raw["decp_recent_contract_notifications"] == 383
    assert raw["decp_basis"] == "recensement portail sur les 7 derniers jours"


def test_a_missing_census_never_becomes_an_extrapolated_volume():
    """Sans recensement, on refuse de mesurer plutôt que d'annoncer un faux chiffre."""
    got = capacity_payload(probe=None, linkage=LINKAGE)
    assert got["A_raw_public_events_per_week"]["decp_recent_contract_notifications"] is None
    assert "non mesurable" in got["B_unique_contract_opportunities_per_week"]["status"]


def test_the_weekly_won_volume_still_comes_from_the_boamp_window():
    got = capacity_payload(probe={"current": {"notified_within_7d": 383}}, linkage=LINKAGE)
    raw = got["A_raw_public_events_per_week"]
    assert raw["boamp_recent_award_decisions"] == 45
    assert "non plafonnée" in raw["boamp_basis"]


def test_the_naive_sum_is_published_only_with_its_warning():
    """R2 §3 — 45 + 383 doit rester lisible, et jamais présenté comme un résultat."""
    got = capacity_payload(probe={"current": {"notified_within_7d": 383}}, linkage=LINKAGE)
    raw = got["A_raw_public_events_per_week"]
    assert raw["naive_sum"] == 428
    assert "PAS un nombre d'opportunités" in raw["warning"]


def test_the_unique_count_is_bounded_and_never_equal_to_the_naive_sum():
    got = capacity_payload(probe={"current": {"notified_within_7d": 383}}, linkage=LINKAGE)
    unique = got["B_unique_contract_opportunities_per_week"]
    assert unique["exact"] is None
    assert unique["lower_bound"] < unique["upper_bound"] < unique["raw_sum"]


def test_customer_ready_never_counts_a_siret_only_event():
    got = capacity_payload(probe={"current": {"notified_within_7d": 383}}, linkage=LINKAGE)
    identity = got["C_customer_ready_opportunities_per_week"]
    assert identity["decp"]["customer_ready"] == 4
    assert identity["decp"]["internally_resolvable_only"] == 379
    assert identity["measured_lower_bound"] == 45
