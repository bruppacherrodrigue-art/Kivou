"""SPEC-009E R2 §3–§6 — compter des opportunités, pas des enregistrements.

R1 avait annoncé « 45 + 383 = 428 événements exploitables par semaine ». C'était
une addition de deux comptages d'événements **bruts** issus de deux registres
qui décrivent parfois le même contrat. Un marché a une décision, une
notification et une publication ; il ne fait pas trois opportunités client.

Ces tests portent sur l'arithmétique qui remplace cette addition : des bornes
honnêtes quand le rapprochement est incomplet, et jamais de milieu inventé.
"""

from __future__ import annotations

import pytest

from signals.france.capacity import (
    IdentityBreakdown,
    LinkageAggregate,
    UniqueContractCount,
    customer_ready_breakdown,
    unique_contract_count,
)


def aggregate(**overrides) -> LinkageAggregate:
    base = {
        "boamp_candidates_tested": 45,
        "boamp_linkable": 30,
        "decp_candidates_returned": 20,
        "strong": 8,
        "probable": 2,
        "unresolved": 20,
        "conflicts": 3,
        "decoys_rejected": 12,
    }
    base.update(overrides)
    return LinkageAggregate(**base)


# ─── §4 — l'agrégat de rapprochement se referme sur lui-même ───────────────────


def test_the_linkage_aggregate_accounts_for_every_candidate_tested():
    got = aggregate()
    assert got.strong + got.probable + got.unresolved == got.boamp_linkable
    assert got.boamp_not_linkable == 15


def test_an_aggregate_whose_outcomes_do_not_sum_is_refused():
    """Un agrégat qui ne se referme pas ne mesure rien."""
    with pytest.raises(ValueError, match="somme"):
        aggregate(strong=9)


def test_the_strong_link_rate_is_reported_over_the_testable_population():
    got = aggregate()
    assert got.strong_rate_over_linkable == 26.7
    assert got.strong_rate_over_tested == 17.8


def test_a_linkage_with_nothing_testable_reports_no_rate_rather_than_zero():
    got = aggregate(boamp_linkable=0, strong=0, probable=0, unresolved=0)
    assert got.strong_rate_over_linkable is None


# ─── §3, §6 — les bornes du comptage unique ────────────────────────────────────


def test_only_proven_duplicates_are_removed_from_the_upper_bound():
    got = unique_contract_count(raw_boamp=45, raw_decp=383, linkage=aggregate())
    assert got.strong_overlap == 8
    assert got.upper_bound == 45 + 383 - 8


def test_every_untestable_event_is_assumed_duplicate_in_the_lower_bound():
    """Borne basse : tout ce qui n'a pas pu être testé est supposé faire doublon."""
    got = unique_contract_count(raw_boamp=45, raw_decp=383, linkage=aggregate())
    assert got.max_possible_overlap == 8 + 2 + 15
    assert got.lower_bound == 45 + 383 - 25


def test_no_midpoint_is_ever_produced():
    got = unique_contract_count(raw_boamp=45, raw_decp=383, linkage=aggregate())
    assert got.exact is None
    assert not hasattr(got, "estimate")
    assert got.lower_bound < got.upper_bound


def test_a_complete_linkage_yields_an_exact_count():
    complete = aggregate(
        boamp_candidates_tested=45, boamp_linkable=45, strong=8, probable=0, unresolved=37
    )
    got = unique_contract_count(raw_boamp=45, raw_decp=383, linkage=complete)
    assert got.exact == 45 + 383 - 8
    assert got.lower_bound == got.upper_bound == got.exact


def test_the_possible_overlap_can_never_exceed_the_smaller_population():
    huge = aggregate(
        boamp_candidates_tested=45, boamp_linkable=45, strong=45, probable=0, unresolved=0
    )
    got = unique_contract_count(raw_boamp=45, raw_decp=10, linkage=huge)
    assert got.strong_overlap == 10
    assert got.lower_bound >= 0


def test_the_count_records_that_the_two_raw_totals_are_not_additive():
    got = unique_contract_count(raw_boamp=45, raw_decp=383, linkage=aggregate())
    assert got.raw_sum == 428
    assert got.upper_bound < got.raw_sum


# ─── §5 — identité affichable, distincte d'un identifiant stable ───────────────


def test_a_siret_alone_is_never_a_customer_ready_identity():
    """§5 — un SIRET se résout ; il ne s'affiche pas devant un commercial."""
    got = customer_ready_breakdown(
        named=0, identified=1000, named_and_identified=0, name_recovered_via_link=0, total=1000
    )
    assert got.stable_identifier_available == 1000
    assert got.legal_name_available == 0
    assert got.customer_ready == 0
    assert got.internally_resolvable_only == 1000


def test_a_name_recovered_through_a_strong_link_counts_as_customer_ready():
    got = customer_ready_breakdown(
        named=0, identified=1000, named_and_identified=0, name_recovered_via_link=8, total=1000
    )
    assert got.name_recovered_via_link == 8
    assert got.customer_ready == 8
    assert got.internally_resolvable_only == 992


def test_a_published_name_is_customer_ready_even_without_an_identifier():
    got = customer_ready_breakdown(
        named=1350, identified=567, named_and_identified=567, name_recovered_via_link=0, total=1482
    )
    assert got.customer_ready == 1350
    assert got.name_and_identifier_available == 567
    assert got.customer_ready_pct == 91.1


def test_a_recovered_name_is_never_double_counted_with_a_published_one():
    got = customer_ready_breakdown(
        named=100, identified=200, named_and_identified=50, name_recovered_via_link=10, total=300
    )
    assert got.customer_ready == 110
    assert got.customer_ready <= got.n


def test_recovering_more_names_than_there_are_unnamed_events_is_refused():
    with pytest.raises(ValueError, match="récupérés"):
        customer_ready_breakdown(
            named=100,
            identified=200,
            named_and_identified=50,
            name_recovered_via_link=250,
            total=300,
        )


def test_the_breakdown_is_a_frozen_record():
    got = customer_ready_breakdown(
        named=1, identified=1, named_and_identified=1, name_recovered_via_link=0, total=1
    )
    assert isinstance(got, IdentityBreakdown)
    with pytest.raises(AttributeError):
        got.customer_ready = 99  # type: ignore[misc]


def test_a_unique_contract_count_is_a_frozen_record():
    got = unique_contract_count(
        raw_boamp=1,
        raw_decp=1,
        linkage=aggregate(
            boamp_candidates_tested=1, boamp_linkable=1, strong=1, probable=0, unresolved=0
        ),
    )
    assert isinstance(got, UniqueContractCount)
    with pytest.raises(AttributeError):
        got.lower_bound = 0  # type: ignore[misc]
