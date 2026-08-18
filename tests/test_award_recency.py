"""SPEC-009E §43 — la politique de fraîcheur d'attribution.

Le défaut que SPEC-009D a mis au jour est simple : le moteur filtrait sur la
date de **parution de l'avis** et le produit promettait « vient de gagner ».
Ces tests fixent la frontière entre les deux, et interdisent qu'elle
redevienne floue.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.recency import (
    AGING_AWARD_DAYS,
    IMPLAUSIBLE_AWARD_AGE_DAYS,
    RECENCY_POLICY_VERSION,
    RECENT_AWARD_DAYS,
    assess_recency,
)

AS_OF = dt.date(2026, 8, 18)


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def at(*, award: str | None = None, published: str | None = None, discovered: str | None = None):
    return assess_recency(
        award_date=D(award) if award else None,
        publication_date=D(published) if published else None,
        discovered_at=D(discovered) if discovered else None,
        as_of=AS_OF,
    )


# ─── §9, §10, §11 — les trois âges d'une attribution datée ──────────────────────


def test_an_award_five_days_old_is_a_recent_award():
    assert at(award="2026-08-13", published="2026-08-14").status == "recent_award"


def test_an_award_exactly_thirty_days_old_is_still_a_recent_award():
    """La borne est incluse : `RECENT_AWARD_DAYS` est un plafond, pas un seuil ouvert."""
    got = at(award="2026-07-19", published="2026-07-20")
    assert got.award_age_days == RECENT_AWARD_DAYS == 30
    assert got.status == "recent_award"


def test_an_award_thirty_one_days_old_is_an_aging_award():
    got = at(award="2026-07-18", published="2026-07-19")
    assert got.award_age_days == 31
    assert got.status == "aging_award"


def test_an_award_sixty_days_old_is_still_aging():
    got = at(award="2026-06-19", published="2026-06-20")
    assert got.award_age_days == AGING_AWARD_DAYS == 60
    assert got.status == "aging_award"


def test_an_award_sixty_one_days_old_is_stale():
    got = at(award="2026-06-18", published="2026-06-19")
    assert got.award_age_days == 61
    assert got.status == "stale_award"


# ─── §12 — attribution inconnue ─────────────────────────────────────────────────


def test_an_unknown_award_date_with_a_recent_publication_is_recently_published():
    got = at(published="2026-08-15")
    assert got.status == "recently_published_award"
    assert got.award_age_days is None


def test_an_unknown_award_date_with_an_old_publication_stays_unknown():
    """Une parution ancienne ne devient pas une découverte : elle n'est plus rien."""
    assert at(published="2026-04-01").status == "award_date_unknown"


def test_an_unknown_award_date_without_any_publication_is_unknown():
    assert at().status == "award_date_unknown"


# ─── §7 — l'interdiction absolue ────────────────────────────────────────────────


def test_a_recent_publication_over_a_ninety_day_old_award_is_never_recent():
    """§43 — publication du jour, attribution de 90 jours : le statut suit l'attribution."""
    got = at(award="2026-05-20", published="2026-08-18")
    assert got.award_age_days == 90
    assert got.publication_age_days == 0
    assert got.status == "stale_award"


def test_the_publication_date_is_never_substituted_for_a_missing_award_date():
    got = at(published="2026-08-18")
    assert got.award_date is None
    assert got.award_age_days is None
    assert got.publication_delay_days is None
    assert got.status != "recent_award"


def test_a_contract_signature_date_is_not_accepted_as_an_award_date():
    """§7 — la signature est un autre événement ; `assess_recency` ne la connaît pas."""
    with pytest.raises(TypeError):
        assess_recency(  # type: ignore[call-arg]
            contract_signature_date=D("2026-08-14"),
            publication_date=D("2026-08-18"),
            as_of=AS_OF,
        )


# ─── §13 — dates invalides, jamais corrigées ────────────────────────────────────


def test_an_award_dated_after_the_as_of_date_is_invalid():
    got = at(award="2026-09-01", published="2026-08-18")
    assert got.status == "invalid_award_date"
    assert got.award_date == D("2026-09-01"), "la valeur brute est conservée"


def test_an_award_dated_well_after_its_own_publication_is_invalid():
    got = at(award="2026-08-14", published="2026-08-01")
    assert got.status == "invalid_award_date"


def test_an_award_dated_one_day_after_publication_stays_tolerated():
    """Les fuseaux et les arrondis de source produisent un jour d'écart légitime."""
    assert at(award="2026-08-14", published="2026-08-13").status == "recent_award"


def test_the_simap_two_thousand_two_case_is_flagged_invalid():
    """Régression SPEC-009D — `award_date = 2002-08-17` publié le 2026-08-18.

    Le moteur d'alors ne lisait pas `award_date` : la valeur traversait tout le
    pipeline sans qu'aucun filtre ne la voie.
    """
    got = at(award="2002-08-17", published="2026-08-18")
    assert got.award_age_days == 8767
    assert got.award_age_days > IMPLAUSIBLE_AWARD_AGE_DAYS
    assert got.status == "invalid_award_date"
    assert "invraisemblable" in got.reason


def test_the_boamp_sentinel_dates_are_flagged_invalid():
    """Régression SPEC-009E — BOAMP publie `2000-01-01` et `1970-01-01` en remplissage."""
    for sentinel in ("2000-01-01", "1970-01-01"):
        assert at(award=sentinel, published="2026-08-18").status == "invalid_award_date"


# ─── §15 — les métriques temporelles dérivées ───────────────────────────────────


def test_every_derivable_delay_is_computed_and_the_rest_stays_none():
    got = at(award="2026-07-20", published="2026-07-27", discovered="2026-07-29")
    assert got.award_age_days == 29
    assert got.publication_age_days == 22
    assert got.publication_delay_days == 7
    assert got.discovery_delay_from_publication == 2
    assert got.discovery_delay_from_award == 9


def test_delays_that_depend_on_a_missing_date_are_not_invented():
    got = at(published="2026-08-15", discovered="2026-08-16")
    assert got.publication_delay_days is None
    assert got.discovery_delay_from_award is None
    assert got.discovery_delay_from_publication == 1


def test_the_policy_version_travels_with_every_assessment():
    """§9 — le seuil est un paramètre versionné, pas une constante cachée."""
    assert at(award="2026-08-13").policy_version == RECENCY_POLICY_VERSION


def test_the_recency_threshold_is_configurable_without_touching_the_engine():
    got = assess_recency(
        award_date=D("2026-07-01"),
        publication_date=D("2026-07-02"),
        as_of=AS_OF,
        recent_award_days=60,
    )
    assert got.award_age_days == 48
    assert got.status == "recent_award"
    assert at(award="2026-07-01", published="2026-07-02").status == "aging_award"


# ─── R1 §3 — la notification de contrat, distincte de la décision ───────────────


def notified(
    *, award: str | None = None, notification: str | None = None, published: str | None = None
):
    return assess_recency(
        award_date=D(award) if award else None,
        contract_notification_date=D(notification) if notification else None,
        publication_date=D(published) if published else None,
        as_of=AS_OF,
    )


def test_a_recent_notification_without_an_award_date_is_recently_notified():
    got = notified(notification="2026-08-14", published="2026-08-17")
    assert got.status == "recently_notified_contract"
    assert got.contract_notification_date == D("2026-08-14")
    assert got.notification_age_days == 4
    assert got.award_date is None


def test_a_recently_notified_contract_may_never_claim_a_win():
    """§3 — la notification n'est pas la décision. Jamais « vient de remporter »."""
    got = notified(notification="2026-08-14", published="2026-08-17")
    assert not got.may_claim_just_won


def test_a_known_award_date_always_outranks_the_notification_date():
    """Quand la décision est publiée, c'est elle qui date le signal."""
    got = notified(award="2026-08-13", notification="2026-08-17", published="2026-08-18")
    assert got.status == "recent_award"
    assert got.award_age_days == 5
    assert got.notification_age_days == 1


def test_an_old_award_date_is_never_rescued_into_award_recency():
    """R1 §3 puis R2 §1 — la notification ne devient jamais une fraîcheur d'attribution.

    R1 rendait `stale_award` et perdait la notification ; R2 §1 met la
    notification en avant. L'invariant protégé est le même dans les deux cas et
    c'est le seul qui compte : l'horloge d'attribution reste périmée, et rien
    n'autorise à dire que l'entreprise vient de gagner.
    """
    got = notified(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.status == "stale"
    assert got.award_age_days == 90
    assert not got.may_claim_just_won
    assert got.status == "recently_notified_contract"


def test_a_notification_older_than_the_threshold_falls_back_to_publication():
    got = notified(notification="2026-06-01", published="2026-08-17")
    assert got.status == "recently_published_award"


def test_a_notification_older_than_the_threshold_without_publication_stays_unknown():
    assert notified(notification="2026-06-01").status == "award_date_unknown"


def test_a_future_notification_date_never_produces_a_recent_notification():
    got = notified(notification="2026-09-01", published="2026-08-18")
    assert got.status != "recently_notified_contract"
    assert got.contract_notification_date == D("2026-09-01"), "valeur brute conservée"


def test_an_implausibly_old_notification_date_is_ignored_not_used():
    got = notified(notification="1970-01-01", published="2026-08-18")
    assert got.status != "recently_notified_contract"


def test_the_notification_threshold_is_versioned_and_configurable():
    from signals.recency import RECENT_NOTIFICATION_DAYS

    assert RECENT_NOTIFICATION_DAYS == 30
    late = assess_recency(
        award_date=None,
        contract_notification_date=D("2026-07-01"),
        publication_date=D("2026-08-18"),
        as_of=AS_OF,
        recent_notification_days=60,
    )
    assert late.status == "recently_notified_contract"
    assert notified(notification="2026-07-01", published="2026-08-18").status != (
        "recently_notified_contract"
    )


def test_the_notification_to_publication_delay_is_derived_when_both_exist():
    got = notified(notification="2026-08-10", published="2026-08-17")
    assert got.notification_delay_days == 7
    assert notified(notification="2026-08-10").notification_delay_days is None


def test_the_policy_version_records_the_extension():
    assert RECENCY_POLICY_VERSION == "award-recency-v0.3"


# ─── R2 §1 — trois horloges indépendantes, un événement dérivé ─────────────────


def clocks(*, award=None, notification=None, published=None):
    return assess_recency(
        award_date=D(award) if award else None,
        contract_notification_date=D(notification) if notification else None,
        publication_date=D(published) if published else None,
        as_of=AS_OF,
    )


def test_a_stale_award_and_a_fresh_notification_keep_their_own_statuses():
    """Le cas de R2 §1 : l'attribution est périmée, la notification est d'hier."""
    got = clocks(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.status == "stale"
    assert got.award_clock.age_days == 90
    assert got.notification_clock.status == "recent"
    assert got.notification_clock.age_days == 1
    assert got.publication_clock.status == "recent"


def test_a_stale_award_with_a_fresh_notification_surfaces_as_a_notification():
    got = clocks(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert got.status == "recently_notified_contract"
    assert not got.may_claim_just_won


def test_a_recent_award_wins_over_a_recent_notification_without_losing_it():
    got = clocks(award="2026-08-13", notification="2026-08-17", published="2026-08-18")
    assert got.status == "recent_award"
    assert got.may_claim_just_won
    assert got.award_clock.status == "recent"
    assert got.notification_clock.status == "recent", "le fait de notification survit"
    assert got.notification_clock.age_days == 1


def test_an_unknown_award_with_a_fresh_notification_is_a_notification_event():
    got = clocks(notification="2026-08-15", published="2026-08-18")
    assert got.award_clock.status == "unknown"
    assert got.status == "recently_notified_contract"


def test_everything_unknown_but_a_fresh_publication_is_a_publication_event():
    got = clocks(published="2026-08-16")
    assert got.award_clock.status == "unknown"
    assert got.notification_clock.status == "unknown"
    assert got.publication_clock.status == "recent"
    assert got.status == "recently_published_award"


def test_an_aging_award_with_a_fresh_notification_surfaces_the_notification():
    got = clocks(award="2026-07-10", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.status == "aging"
    assert got.status == "recently_notified_contract"
    assert not got.may_claim_just_won


def test_an_aging_award_without_a_fresh_notification_stays_an_aging_award():
    got = clocks(award="2026-07-10", published="2026-08-18")
    assert got.status == "aging_award"


def test_a_stale_notification_never_rescues_a_stale_award():
    got = clocks(award="2026-05-20", notification="2026-06-01", published="2026-08-18")
    assert got.notification_clock.status == "stale"
    assert got.status == "stale_award"


def test_an_invalid_award_date_with_a_fresh_notification_still_surfaces_the_notification():
    """Une date de décision cassée ne doit pas faire perdre un fait de notification vrai."""
    got = clocks(award="2002-08-17", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.status == "invalid"
    assert got.status == "recently_notified_contract"
    assert got.award_date == D("2002-08-17"), "la valeur brute reste inspectable"


def test_an_invalid_award_date_alone_remains_an_invalid_award():
    got = clocks(award="2002-08-17", published="2026-08-18")
    assert got.status == "invalid_award_date"


def test_every_raw_date_stays_independently_inspectable():
    """R2 §2 — aucune horloge n'efface les autres."""
    got = clocks(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.date == D("2026-05-20")
    assert got.notification_clock.date == D("2026-08-17")
    assert got.publication_clock.date == D("2026-08-18")
    assert (got.award_date, got.contract_notification_date, got.publication_date) == (
        D("2026-05-20"),
        D("2026-08-17"),
        D("2026-08-18"),
    )


def test_each_clock_names_itself_and_explains_its_status():
    got = clocks(award="2026-08-13", notification="2026-08-17", published="2026-08-18")
    assert got.award_clock.clock == "award"
    assert got.notification_clock.clock == "notification"
    assert got.publication_clock.clock == "publication"
    for clock in (got.award_clock, got.notification_clock, got.publication_clock):
        assert clock.reason


def test_the_clocks_are_reachable_as_a_mapping_for_reporting():
    got = clocks(award="2026-08-13", notification="2026-08-17")
    assert set(got.clocks) == {"award", "notification", "publication"}
    assert got.clocks["award"].status == "recent"
