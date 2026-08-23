"""#29 — ce que Kivou envoie RÉELLEMENT à Stripe pour changer de formule.

Pourquoi ce fichier existe
──────────────────────────
Le premier paiement TEST réel avait échoué en 500 sur staging alors que 2712
tests étaient verts : tous passaient par un faux `StripeGateway` acceptant
`**kwargs`, qui prouvait la forme des arguments Kivou et jamais leur validité
Stripe. Le changement de formule touche à de l'argent et ne peut pas, pour
l'instant, être exercé en Stripe TEST — raison de plus pour vérifier ici le
dictionnaire EXACT remis au SDK.

Le transport du SDK est remplacé par un enregistreur : aucun appel réseau, mais
la construction des paramètres est celle de la production.

Ce que ces tests ne remplacent pas
──────────────────────────────────
Une validation **Test Clock** en Stripe TEST : eux vérifient ce qu'on demande,
elle vérifie ce que Stripe en fait. Elle reste due avant toute fusion.
"""

from __future__ import annotations

from typing import Any

import pytest

from signals.billing.gateway import (
    PlanChangePaymentFailed,
    StripeApiGateway,
    StripeGateway,
)

PERIOD_START = 1_785_000_000
PERIOD_END = 1_787_678_400


class _Recorder:
    """Enregistre chaque appel et rend l'objet qu'on lui a confié."""

    def __init__(self, results: dict[str, Any], error: Exception | None = None) -> None:
        self.results = results
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def _record(self, verb: str, args: tuple, params=None, options=None):
        self.calls.append({"verb": verb, "args": args, "params": params, "options": options})

    def retrieve(self, *args, params=None, options=None):
        self._record("retrieve", args, params, options)
        return self.results["retrieve"]

    def create(self, params=None, options=None):
        self._record("create", (), params, options)
        return self.results["create"]

    def update(self, *args, params=None, options=None):
        self._record("update", args, params, options)
        if self.error is not None:
            raise self.error
        return self.results["update"]

    def release(self, *args, params=None, options=None):
        self._record("release", args, params, options)
        return self.results.get("release")

    def cancel(self, *args, params=None, options=None):  # pragma: no cover - piège
        self._record("cancel", args, params, options)
        raise AssertionError("annuler le schedule annulerait l'abonnement avec lui")


SUBSCRIPTION = {
    "id": "sub_1",
    "customer": "cus_1",
    "status": "active",
    "schedule": None,
    "items": {"data": [{"id": "si_1", "price": {"id": "price_essential_chf"}}]},
    "livemode": False,
}

SCHEDULE_ONE_PHASE = {
    "id": "sub_sched_1",
    "livemode": False,
    "current_phase": {"start_date": PERIOD_START, "end_date": PERIOD_END},
    "phases": [
        {
            "start_date": PERIOD_START,
            "end_date": PERIOD_END,
            "items": [
                {"price": {"id": "price_scale_chf", "lookup_key": "kivou_scale_monthly_chf"}}
            ],
        }
    ],
}

SCHEDULE_TWO_PHASES = {
    "id": "sub_sched_1",
    "livemode": False,
    "current_phase": {"start_date": PERIOD_START, "end_date": PERIOD_END},
    "phases": [
        SCHEDULE_ONE_PHASE["phases"][0],
        {
            "start_date": PERIOD_END,
            "items": [
                {
                    "price": {
                        "id": "price_essential_chf",
                        "lookup_key": "kivou_essential_monthly_chf",
                        "currency": "chf",
                    }
                }
            ],
        },
    ],
}

#: Le MÊME schedule une fois la bascule faite : la phase Essential est devenue
#: la phase COURANTE. Plus rien n'est « à venir », et l'annoncer mentirait.
SCHEDULE_AFTER_SWITCH = {
    "id": "sub_sched_1",
    "livemode": False,
    "current_phase": {"start_date": PERIOD_END, "end_date": PERIOD_END + 2_678_400},
    "phases": SCHEDULE_TWO_PHASES["phases"],
}


def gateway_recording(*, subscription=None, error=None):
    """La passerelle de PRODUCTION, dont seul le transport est remplacé."""
    gateway = StripeApiGateway("sk_test_offline_double")
    subscriptions = _Recorder(
        {"retrieve": subscription or SUBSCRIPTION, "update": SUBSCRIPTION}, error
    )
    schedules = _Recorder(
        {
            "create": SCHEDULE_ONE_PHASE,
            "retrieve": SCHEDULE_ONE_PHASE,
            "update": SCHEDULE_TWO_PHASES,
        }
    )
    prices = _Recorder({"retrieve": {"id": "price_essential_chf", "recurring": {"interval": "month", "interval_count": 1}}})
    gateway._client = type(
        "_Client",
        (),
        {"subscriptions": subscriptions, "subscription_schedules": schedules, "prices": prices},
    )()
    return gateway, subscriptions, schedules


# ─── La montée de formule ─────────────────────────────────────────────────────


def test_an_upgrade_refuses_itself_when_the_proration_cannot_be_charged():
    """`error_if_incomplete` est CE qui empêche d'ouvrir des droits impayés.

    Sans ce paramètre, Stripe accepterait la modification et laisserait une
    facture ouverte : le client aurait la formule supérieure sans l'avoir payée.
    """
    gateway, subscriptions, _ = gateway_recording()

    gateway.change_subscription_price(
        subscription_id="sub_1", price_id="price_scale_chf", idempotency_key="k1"
    )

    params = subscriptions.calls[-1]["params"]
    assert params["payment_behavior"] == "error_if_incomplete"


def test_an_upgrade_invoices_the_proration_immediately():
    gateway, subscriptions, _ = gateway_recording()

    gateway.change_subscription_price(
        subscription_id="sub_1", price_id="price_scale_chf", idempotency_key="k1"
    )

    params = subscriptions.calls[-1]["params"]
    assert params["proration_behavior"] == "always_invoice"


def test_an_upgrade_replaces_the_existing_line_rather_than_adding_one():
    """Ajouter une ligne facturerait les DEUX formules au même client."""
    gateway, subscriptions, _ = gateway_recording()

    gateway.change_subscription_price(
        subscription_id="sub_1", price_id="price_scale_chf", idempotency_key="k1"
    )

    params = subscriptions.calls[-1]["params"]
    assert params["items"] == [{"id": "si_1", "price": "price_scale_chf"}]


def test_an_upgrade_carries_the_idempotency_key():
    """Deux clics ne facturent qu'un prorata."""
    gateway, subscriptions, _ = gateway_recording()

    gateway.change_subscription_price(
        subscription_id="sub_1", price_id="price_scale_chf", idempotency_key="k-abc"
    )

    assert subscriptions.calls[-1]["options"] == {"idempotency_key": "k-abc"}


def test_a_declined_card_becomes_a_payment_failure_not_a_crash():
    """Le refus bancaire doit être NOMMÉ pour qu'aucun droit ne soit accordé."""
    import stripe

    declined = stripe.CardError("carte refusée", param=None, code="card_declined")
    gateway, _, _ = gateway_recording(error=declined)

    with pytest.raises(PlanChangePaymentFailed):
        gateway.change_subscription_price(
            subscription_id="sub_1", price_id="price_scale_chf", idempotency_key="k1"
        )


# ─── La descente de formule ───────────────────────────────────────────────────


def test_a_downgrade_creates_a_schedule_from_the_existing_subscription():
    """`from_subscription` reprend la période courante — on n'en invente aucune."""
    gateway, _, schedules = gateway_recording()

    gateway.schedule_subscription_price(
        subscription_id="sub_1", price_id="price_essential_chf", idempotency_key="k1"
    )

    created = next(c for c in schedules.calls if c["verb"] == "create")
    assert created["params"]["from_subscription"] == "sub_1"


def test_a_downgrade_keeps_the_paid_period_then_switches():
    """Deux phases : ce qui est payé reste, la nouvelle formule vient après."""
    gateway, _, schedules = gateway_recording()

    gateway.schedule_subscription_price(
        subscription_id="sub_1", price_id="price_essential_chf", idempotency_key="k1"
    )

    phases = next(c for c in schedules.calls if c["verb"] == "update")["params"]["phases"]
    assert len(phases) == 2
    assert phases[0]["start_date"] == PERIOD_START
    assert phases[0]["end_date"] == PERIOD_END
    assert phases[0]["items"][0]["price"] == "price_scale_chf", "la formule PAYÉE reste"
    assert phases[1]["items"] == [{"price": "price_essential_chf", "quantity": 1}]
    # `iterations` n'existe plus dans l'API : Stripe rejette la requête. Une
    # phase finale sans durée ne se termine jamais, donc `release` ne se
    # déclenche pas. Défaut trouvé en Test Clock, verrouillé ici.
    assert "iterations" not in phases[1]
    assert phases[1]["duration"] == {"interval": "month", "interval_count": 1}


def test_a_downgrade_releases_the_subscription_after_the_switch():
    """`end_behavior=release` : le schedule ne survit pas à sa raison d'être."""
    gateway, _, schedules = gateway_recording()

    gateway.schedule_subscription_price(
        subscription_id="sub_1", price_id="price_essential_chf", idempotency_key="k1"
    )

    params = next(c for c in schedules.calls if c["verb"] == "update")["params"]
    assert params["end_behavior"] == "release"


def test_a_downgrade_expands_the_price_so_the_plan_is_readable():
    """Sans expansion, Stripe ne rend qu'un `price_...` — intraduisible en formule."""
    gateway, _, schedules = gateway_recording()

    scheduled = gateway.schedule_subscription_price(
        subscription_id="sub_1", price_id="price_essential_chf", idempotency_key="k1"
    )

    params = next(c for c in schedules.calls if c["verb"] == "update")["params"]
    assert params["expand"] == ["phases.items.price"]
    assert scheduled.lookup_key == "kivou_essential_monthly_chf"


def test_a_second_downgrade_reuses_the_existing_schedule():
    """Deux schedules sur un même abonnement se contrediraient."""
    subscription = {**SUBSCRIPTION, "schedule": "sub_sched_1"}
    gateway, _, schedules = gateway_recording(subscription=subscription)

    gateway.schedule_subscription_price(
        subscription_id="sub_1", price_id="price_essential_chf", idempotency_key="k1"
    )

    assert not [c for c in schedules.calls if c["verb"] == "create"]
    assert [c for c in schedules.calls if c["verb"] == "retrieve"]


# ─── Se raviser ───────────────────────────────────────────────────────────────


def test_cancelling_a_scheduled_change_releases_and_never_cancels():
    """`release` garde l'abonnement ; `cancel` l'emporterait avec le schedule.

    Le double lève si `cancel` est appelé : confondre les deux transformerait
    « je me ravise » en « je résilie ».
    """
    subscription = {**SUBSCRIPTION, "schedule": "sub_sched_1"}
    gateway, _, schedules = gateway_recording(subscription=subscription)

    gateway.release_pending_plan_change(subscription_id="sub_1")

    assert [c["verb"] for c in schedules.calls if c["verb"] in {"release", "cancel"}] == ["release"]


def test_cancelling_without_a_schedule_touches_nothing():
    gateway, _, schedules = gateway_recording()

    gateway.release_pending_plan_change(subscription_id="sub_1")

    assert schedules.calls == []


# ─── Le défaut de câblage récurrent ───────────────────────────────────────────


def test_the_real_gateway_implements_every_verb_the_protocol_declares():
    """La fabrique accepte un adaptateur ; la production doit en fournir un.

    Ce dépôt a déjà connu ce défaut : un protocole enrichi, une implémentation
    réelle laissée derrière, et l'écart n'apparaît qu'en production — un
    `Protocol` n'est pas vérifié à l'exécution.
    """
    declared = {
        name
        for name in getattr(StripeGateway, "__protocol_attrs__", ())
        or {n for n in dir(StripeGateway) if not n.startswith("_")}
    }
    missing = sorted(name for name in declared if not hasattr(StripeApiGateway, name))

    assert declared, "le protocole doit déclarer au moins un verbe"
    assert missing == []


def test_a_schedule_whose_switch_already_happened_announces_nothing():
    """Après la bascule, la phase n'est plus « à venir » : elle est courante.

    Prendre `phases[1]` sans regarder `current_phase` annonçait encore « vous
    passerez à Essential le … » longtemps après que c'était fait. Défaut trouvé
    en Test Clock, verrouillé ici.
    """
    gateway, _, schedules = gateway_recording(
        subscription={**SUBSCRIPTION, "schedule": "sub_sched_1"}
    )
    schedules.results["retrieve"] = SCHEDULE_AFTER_SWITCH

    assert gateway.pending_plan_change(subscription_id="sub_1") is None


def test_a_schedule_with_a_future_phase_is_announced():
    """La garde ci-dessus ne doit pas rendre le cas normal muet."""
    gateway, _, schedules = gateway_recording(
        subscription={**SUBSCRIPTION, "schedule": "sub_sched_1"}
    )
    schedules.results["retrieve"] = SCHEDULE_TWO_PHASES

    pending = gateway.pending_plan_change(subscription_id="sub_1")

    assert pending is not None
    assert pending.lookup_key == "kivou_essential_monthly_chf"
    assert pending.effective_at is not None
