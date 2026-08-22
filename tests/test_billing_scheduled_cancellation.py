"""P0-03G — une résiliation programmée doit être VISIBLE, quelle que soit la forme.

Le défaut que ce fichier ferme
──────────────────────────────
Un client résilie depuis le portail Kivou. Stripe l'enregistre et l'affiche
(« Your service will end on September 22, 2026 »). Kivou reçoit
`customer.subscription.updated`, l'applique — et continue de répondre
`cancel_at_period_end: false`. Le bandeau « Résiliation programmée » ne
s'affiche jamais ; le client croit rester abonné.

Observé en vrai sur staging, deux fois, sur deux abonnements distincts : sur un
abonnement `billing_mode: flexible`, Stripe n'exprime PAS la résiliation via
`cancel_at_period_end` — il écrit `cancel_at`, et laisse le booléen à `false`.

La correction lit donc une DATE, pas un booléen :

    cancel_at renseigné            → c'est la date, telle quelle
    sinon cancel_at_period_end     → c'est la fin de période
    sinon                          → aucune résiliation programmée

`canceled_at` n'entre jamais dans ce calcul : il est renseigné aussi sur une
résiliation IMMÉDIATE, et le prendre pour un indicateur ferait annoncer une
échéance à des comptes qui n'en ont pas.

Le booléen `cancel_at_period_end` survit, mais avec une sémantique honnête :
vrai seulement quand l'échéance TOMBE sur la fin de période. Une date distincte
existe — Stripe permet de planifier une résiliation à une autre date — et la
présenter comme une « fin de période » serait un mensonge daté.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.billing.gateway import subscription_state

PERIOD_END = dt.datetime(2026, 9, 22, 1, 42, 3, tzinfo=dt.UTC)
OTHER_DATE = dt.datetime(2026, 11, 30, 12, 0, 0, tzinfo=dt.UTC)
CANCELED_AT = dt.datetime(2026, 8, 22, 1, 43, 12, tzinfo=dt.UTC)


def epoch(moment: dt.datetime) -> int:
    return int(moment.timestamp())


def stripe_subscription(
    *,
    cancel_at: dt.datetime | None = None,
    cancel_at_period_end: bool = False,
    canceled_at: dt.datetime | None = None,
    current_period_end: dt.datetime | None = PERIOD_END,
) -> dict:
    """Un abonnement Stripe, dans la forme que rend l'API."""
    return {
        "id": "sub_test_1",
        "customer": "cus_test_1",
        "status": "active",
        "currency": "chf",
        "livemode": False,
        "current_period_start": epoch(dt.datetime(2026, 8, 22, 1, 42, 3, tzinfo=dt.UTC)),
        "current_period_end": None if current_period_end is None else epoch(current_period_end),
        "cancel_at": None if cancel_at is None else epoch(cancel_at),
        "cancel_at_period_end": cancel_at_period_end,
        "canceled_at": None if canceled_at is None else epoch(canceled_at),
        "items": {"data": [{"price": {"id": "price_1", "lookup_key": "kivou_pro_monthly_chf"}}]},
    }


# ─── 1. les quatre formes que Stripe peut prendre ────────────────────────────


def test_classique_le_booleen_seul_designe_la_fin_de_periode():
    """La forme historique : `cancel_at_period_end` vrai, aucune date."""
    state = subscription_state(
        stripe_subscription(cancel_at_period_end=True, current_period_end=PERIOD_END)
    )

    assert state.scheduled_cancellation_at == PERIOD_END
    assert state.cancel_at_period_end is True


def test_flexible_la_date_seule_designe_la_meme_fin_de_periode():
    """Le cas RÉEL qui a produit le défaut, relevé deux fois sur staging.

    Stripe écrit `cancel_at`, égal à la fin de période, et laisse le booléen à
    `false`. Kivou doit conclure la même chose que dans le cas classique.
    """
    state = subscription_state(
        stripe_subscription(
            cancel_at=PERIOD_END,
            cancel_at_period_end=False,
            canceled_at=CANCELED_AT,
            current_period_end=PERIOD_END,
        )
    )

    assert state.scheduled_cancellation_at == PERIOD_END
    assert state.cancel_at_period_end is True


def test_une_date_distincte_n_est_pas_une_fin_de_periode():
    """Stripe permet de planifier une résiliation à une AUTRE date.

    L'annoncer comme une « fin de période » donnerait au client une échéance
    fausse — et c'est précisément le genre de mensonge daté qu'on ferme ici.
    """
    state = subscription_state(
        stripe_subscription(
            cancel_at=OTHER_DATE,
            cancel_at_period_end=False,
            current_period_end=PERIOD_END,
        )
    )

    assert state.scheduled_cancellation_at == OTHER_DATE
    assert state.cancel_at_period_end is False


def test_aucune_resiliation_ne_produit_aucune_echeance():
    state = subscription_state(stripe_subscription())

    assert state.scheduled_cancellation_at is None
    assert state.cancel_at_period_end is False


def test_canceled_at_seul_n_annonce_aucune_echeance():
    """§2 — `canceled_at` est renseigné aussi sur une résiliation IMMÉDIATE.

    S'en servir comme indicateur ferait annoncer une échéance à des comptes qui
    n'en ont aucune.
    """
    state = subscription_state(
        stripe_subscription(canceled_at=CANCELED_AT, cancel_at=None, cancel_at_period_end=False)
    )

    assert state.scheduled_cancellation_at is None
    assert state.cancel_at_period_end is False
    assert state.canceled_at == CANCELED_AT


# ─── 2. les bords ────────────────────────────────────────────────────────────


def test_la_date_prime_sur_le_booleen_quand_les_deux_sont_presents():
    """Stripe peut renseigner les deux ; la DATE est ce qui se dit au client."""
    state = subscription_state(
        stripe_subscription(
            cancel_at=OTHER_DATE, cancel_at_period_end=True, current_period_end=PERIOD_END
        )
    )

    assert state.scheduled_cancellation_at == OTHER_DATE
    # Le booléen brut de Stripe reste vrai : on ne le contredit pas.
    assert state.cancel_at_period_end is True


def test_le_booleen_survit_meme_sans_fin_de_periode_connue():
    """Stripe dit « en fin de période » sans donner la période : on le répète."""
    state = subscription_state(
        stripe_subscription(cancel_at_period_end=True, current_period_end=None)
    )

    assert state.scheduled_cancellation_at is None
    assert state.cancel_at_period_end is True


def test_une_seconde_d_ecart_n_est_pas_une_fin_de_periode():
    """L'égalité est exacte. Deux instants proches restent deux instants."""
    presque = PERIOD_END + dt.timedelta(seconds=1)
    state = subscription_state(
        stripe_subscription(cancel_at=presque, current_period_end=PERIOD_END)
    )

    assert state.scheduled_cancellation_at == presque
    assert state.cancel_at_period_end is False


@pytest.mark.parametrize("statut", ["active", "past_due", "trialing"])
def test_l_echeance_est_lue_quel_que_soit_le_statut(statut: str):
    """Une résiliation programmée n'est pas réservée aux abonnements sains."""
    raw = stripe_subscription(cancel_at=PERIOD_END, current_period_end=PERIOD_END)
    raw["status"] = statut

    state = subscription_state(raw)

    assert state.scheduled_cancellation_at == PERIOD_END
    assert state.status == statut
