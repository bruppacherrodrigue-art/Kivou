"""SPEC-009E §31 — la phrase que Kivou a le droit de dire.

Toute la valeur du produit tient dans une distinction d'une ligne : « cette
entreprise vient de remporter » n'est pas « une attribution vient d'être
publiée ». La première affirme un fait daté sur l'entreprise, la seconde un
fait daté sur un avis. Les confondre est le seul mensonge que le MVP puisse
commettre à grande échelle.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.recency import assess_recency
from signals.recency.claim import (
    CLAIM_COPY_VERSION,
    JUST_WON_MARKERS,
    claim_for,
    claim_for_status,
)

AS_OF = dt.date(2026, 8, 18)
COMPANY = "Entreprise Test SA"

ALL_STATUSES = (
    "recent_award",
    "aging_award",
    "stale_award",
    "recently_notified_contract",
    "recently_published_award",
    "award_date_unknown",
    "invalid_award_date",
)


# ─── les deux formulations autorisées ───────────────────────────────────────────


def test_a_recent_award_may_say_the_company_just_won_in_french():
    assert claim_for_status("recent_award", company=COMPANY, lang="fr") == (
        "Entreprise Test SA vient de remporter un marché public."
    )


def test_a_recent_award_may_say_the_company_just_won_in_english():
    assert claim_for_status("recent_award", company=COMPANY, lang="en") == (
        "Entreprise Test SA has recently won a public contract."
    )


def test_a_recently_published_award_speaks_of_the_notice_not_the_company():
    assert claim_for_status("recently_published_award", company=COMPANY, lang="fr") == (
        "Une attribution concernant Entreprise Test SA vient d'être publiée."
    )
    assert claim_for_status("recently_published_award", company=COMPANY, lang="en") == (
        "An award notice concerning Entreprise Test SA has recently been published."
    )


# ─── l'interdiction, vérifiée sur tous les états ────────────────────────────────


@pytest.mark.parametrize("status", [s for s in ALL_STATUSES if s != "recent_award"])
@pytest.mark.parametrize("lang", ["fr", "en"])
def test_no_status_other_than_recent_award_ever_claims_a_win(status: str, lang: str):
    text = claim_for_status(status, company=COMPANY, lang=lang).casefold()
    for marker in JUST_WON_MARKERS:
        assert marker not in text, f"{status}/{lang} affirme une victoire : {text!r}"


def test_a_stale_award_is_never_presented_as_a_win():
    recency = assess_recency(award_date=dt.date(2026, 5, 20), publication_date=AS_OF, as_of=AS_OF)
    assert recency.status == "stale_award"
    assert not recency.may_claim_just_won
    assert "vient de remporter" not in claim_for(recency, company=COMPANY, lang="fr")


def test_an_unknown_award_date_is_never_presented_as_a_win():
    recency = assess_recency(award_date=None, publication_date=dt.date(2026, 8, 15), as_of=AS_OF)
    assert recency.status == "recently_published_award"
    assert not recency.may_claim_just_won
    assert claim_for(recency, company=COMPANY, lang="fr").startswith("Une attribution concernant")


def test_an_invalid_award_date_never_produces_a_dated_claim():
    recency = assess_recency(award_date=dt.date(2002, 8, 17), publication_date=AS_OF, as_of=AS_OF)
    assert recency.status == "invalid_award_date"
    text = claim_for(recency, company=COMPANY, lang="fr")
    assert "2002" not in text
    assert "vient de remporter" not in text


def test_claim_for_reads_the_status_and_never_the_dates_directly():
    """La phrase découle du statut : aucune règle de date ne vit dans le texte."""
    fresh = assess_recency(
        award_date=dt.date(2026, 8, 13), publication_date=dt.date(2026, 8, 14), as_of=AS_OF
    )
    assert claim_for(fresh, company=COMPANY, lang="fr") == claim_for_status(
        "recent_award", company=COMPANY, lang="fr"
    )


# ─── invariants de la table ─────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("lang", ["fr", "en"])
def test_every_status_has_a_sentence_in_both_languages(status: str, lang: str):
    text = claim_for_status(status, company=COMPANY, lang=lang)
    assert text.startswith(COMPANY) or COMPANY in text
    assert text.endswith(".")


def test_an_unknown_status_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="statut"):
        claim_for_status("almost_won", company=COMPANY, lang="fr")


def test_an_unknown_language_is_refused_rather_than_falling_back():
    with pytest.raises(ValueError, match="langue"):
        claim_for_status("recent_award", company=COMPANY, lang="de")


def test_the_copy_version_is_declared():
    assert CLAIM_COPY_VERSION


# ─── §30 — les deux types d'événement du MVP ────────────────────────────────────


def test_the_mvp_event_types_are_exactly_those_the_supervisor_authorised():
    """Deux jusqu'à R1, trois depuis : §3 de R1 a autorisé l'état « notifié ».

    Le test reste une liste fermée : ajouter un quatrième type sans décision
    explicite doit faire échouer la suite.
    """
    from signals.recency.claim import MVP_EVENT_TYPES

    assert set(MVP_EVENT_TYPES) == {
        "RECENT_AWARD",
        "RECENTLY_NOTIFIED_CONTRACT",
        "RECENTLY_PUBLISHED_AWARD",
    }


def test_a_recent_award_maps_to_the_recent_award_event_type():
    from signals.recency.claim import mvp_event_type

    assert mvp_event_type("recent_award") == "RECENT_AWARD"


@pytest.mark.parametrize(
    "status", ["recently_published_award", "award_date_unknown", "invalid_award_date"]
)
def test_undated_statuses_map_to_the_recently_published_event_type(status: str):
    from signals.recency.claim import mvp_event_type

    assert mvp_event_type(status) == "RECENTLY_PUBLISHED_AWARD"


@pytest.mark.parametrize("status", ["aging_award", "stale_award"])
def test_dated_but_old_awards_carry_no_mvp_event_type(status: str):
    """§10, §11 — ils existent, mais pas dans le feed « nouvelles opportunités »."""
    from signals.recency.claim import mvp_event_type

    assert mvp_event_type(status) is None


def test_a_contract_signed_event_type_is_not_built_yet():
    """§30 — réservé pour plus tard, donc absent, pas déclaré vide."""
    from signals.recency.claim import MVP_EVENT_TYPES

    assert "CONTRACT_SIGNED" not in MVP_EVENT_TYPES
    assert "CONTRACT_STARTING" not in MVP_EVENT_TYPES


# ─── R1 §3 — la notification a sa propre phrase, et elle ne revendique rien ─────


def test_a_recently_notified_contract_speaks_of_the_contract_not_of_a_win():
    assert claim_for_status("recently_notified_contract", company=COMPANY, lang="fr") == (
        "Un marché attribué à Entreprise Test SA vient d'être notifié."
    )
    assert claim_for_status("recently_notified_contract", company=COMPANY, lang="en") == (
        "A public contract awarded to Entreprise Test SA has recently been notified."
    )


def test_the_notified_wording_is_distinct_from_the_won_wording():
    """§3 — les deux phrases ne doivent jamais pouvoir être confondues."""
    won = claim_for_status("recent_award", company=COMPANY, lang="fr")
    notified = claim_for_status("recently_notified_contract", company=COMPANY, lang="fr")
    assert won != notified
    assert "vient de remporter" in won
    assert "vient de remporter" not in notified
    assert "vient d'être notifié" in notified


def test_a_notified_contract_flows_to_its_own_sentence_from_the_assessment():
    recency = assess_recency(
        award_date=None,
        contract_notification_date=dt.date(2026, 8, 14),
        publication_date=dt.date(2026, 8, 17),
        as_of=AS_OF,
    )
    assert recency.status == "recently_notified_contract"
    assert not recency.may_claim_just_won
    assert claim_for(recency, company=COMPANY, lang="fr").startswith("Un marché attribué à")


def test_the_notified_event_type_is_distinct_from_the_two_original_ones():
    from signals.recency.claim import MVP_EVENT_TYPES, mvp_event_type

    assert mvp_event_type("recently_notified_contract") == "RECENTLY_NOTIFIED_CONTRACT"
    assert set(MVP_EVENT_TYPES) == {
        "RECENT_AWARD",
        "RECENTLY_NOTIFIED_CONTRACT",
        "RECENTLY_PUBLISHED_AWARD",
    }


# ─── R2 §2 — la formulation face à plusieurs horloges simultanées ──────────────


def multi(*, award=None, notification=None, published=None):
    return assess_recency(
        award_date=dt.date.fromisoformat(award) if award else None,
        contract_notification_date=dt.date.fromisoformat(notification) if notification else None,
        publication_date=dt.date.fromisoformat(published) if published else None,
        as_of=AS_OF,
    )


def test_a_stale_award_with_a_recent_notification_produces_notification_copy():
    """R2 §2 — le fait exploitable doit sortir, sans devenir une victoire."""
    recency = multi(award="2026-05-20", notification="2026-08-17", published="2026-08-18")
    assert recency.award_clock.status == "stale"
    assert claim_for(recency, company=COMPANY, lang="fr") == (
        "Un marché attribué à Entreprise Test SA vient d'être notifié."
    )
    assert claim_for(recency, company=COMPANY, lang="en") == (
        "A public contract awarded to Entreprise Test SA has recently been notified."
    )


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_a_notification_event_never_claims_a_win_whatever_the_award_clock(lang: str):
    for award in (None, "2026-05-20", "2026-07-10", "2002-08-17"):
        recency = multi(award=award, notification="2026-08-17", published="2026-08-18")
        assert recency.status == "recently_notified_contract"
        text = claim_for(recency, company=COMPANY, lang=lang).casefold()
        for marker in JUST_WON_MARKERS:
            assert marker not in text, f"award={award} lang={lang} : {text!r}"


def test_a_recent_award_stays_a_win_even_when_other_clocks_are_also_recent():
    recency = multi(award="2026-08-13", notification="2026-08-17", published="2026-08-18")
    assert recency.may_claim_just_won
    assert claim_for(recency, company=COMPANY, lang="fr") == (
        "Entreprise Test SA vient de remporter un marché public."
    )
    assert recency.notification_clock.is_recent, "l'autre horloge reste lisible"


def test_a_recent_publication_alone_speaks_only_of_the_publication():
    recency = multi(published="2026-08-16")
    assert recency.status == "recently_published_award"
    assert claim_for(recency, company=COMPANY, lang="fr").startswith("Une attribution concernant")


def test_the_three_mvp_events_map_to_three_distinct_sentences():
    sentences = {
        claim_for_status(status, company=COMPANY, lang="fr")
        for status in ("recent_award", "recently_notified_contract", "recently_published_award")
    }
    assert len(sentences) == 3
