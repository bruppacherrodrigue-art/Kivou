"""Validation Stripe TEST du changement de formule (#29), par Test Clock.

    Ce N'EST PAS un test de la suite : il exige le réseau et des identifiants.

Pourquoi il existe malgré tout
──────────────────────────────
Les tests hors ligne prouvent ce que Kivou DEMANDE à Stripe. Seule une Test
Clock prouve ce que Stripe EN FAIT — et elle a trouvé deux défauts qu'aucun
double n'aurait pu voir : `phases[iterations]`, paramètre qui n'existe plus dans
l'API, et une phase déjà jouée annoncée comme « à venir » longtemps après la
bascule.

Rien n'est réimplémenté ici : les transitions passent par les méthodes de
PRODUCTION de `StripeApiGateway`. Un script qui referait les appels à la main
validerait le script, pas le produit.

Usage
─────
    stripe login                       # une fois, compte Kivou - Staging
    uv run python ops/validation/plan_change_testclock.py

La clé est lue dans la configuration de la CLI et n'est jamais affichée. Le
script refuse de démarrer si elle n'est pas une clé TEST. Tous les objets créés
portent le préfixe `kivou-testclock-` et sont supprimés en fin de course, y
compris après un échec.
"""

import pathlib
import sys
import time
import tomllib

import stripe as stripe_sdk

from signals.billing.gateway import PlanChangePaymentFailed, StripeApiGateway

# ── clé : lue, jamais affichée ───────────────────────────────────────────────
cfg = tomllib.loads(pathlib.Path.home().joinpath(".config/stripe/config.toml").read_text())
key = next(
    (
        v
        for s in cfg.values()
        if isinstance(s, dict)
        for k, v in s.items()
        if k == "test_mode_api_key" and isinstance(v, str)
    ),
    None,
)
assert key, "aucune test_mode_api_key dans la config CLI"
assert key.startswith(("sk_test_", "rk_test_")), "GARDE: la clé n'est pas une clé TEST"
stripe_sdk.api_key = key
gw = StripeApiGateway(key)


def price(lookup):
    p = gw.price_for_lookup_key(lookup)
    assert p and not p.livemode, f"prix introuvable ou LIVE: {lookup}"
    return p


ESS, PRO, SCALE = (
    price("kivou_essential_monthly_chf"),
    price("kivou_pro_monthly_chf"),
    price("kivou_scale_monthly_chf"),
)
print(f"catalogue: essential={ESS.price_id} pro={PRO.price_id} scale={SCALE.price_id}")


def wait_clock(cid):
    for _ in range(120):
        c = stripe_sdk.test_helpers.TestClock.retrieve(cid)
        if c.status == "ready":
            return c
        time.sleep(2)
    raise AssertionError("test clock bloquée")


def setup(label, pm="pm_card_visa", start_price=None):
    clock = stripe_sdk.test_helpers.TestClock.create(frozen_time=int(time.time()), name=label)
    cust = stripe_sdk.Customer.create(name=f"kivou-testclock-{label}", test_clock=clock.id)
    # Enregistré AVANT tout ce qui peut échouer : sinon un plantage laisse des
    # objets orphelins dans le compte TEST.
    created.append((clock.id, cust.id))
    # `pm_card_visa` est un raccourci : `attach` fabrique un VRAI moyen de
    # paiement dont l'identifiant est celui qu'il rend, pas le raccourci.
    attached = stripe_sdk.PaymentMethod.attach(pm, customer=cust.id)
    stripe_sdk.Customer.modify(cust.id, invoice_settings={"default_payment_method": attached.id})
    sub = stripe_sdk.Subscription.create(
        customer=cust.id,
        items=[{"price": (start_price or ESS).price_id}],
        expand=["items.data.price"],
    )
    return clock, cust, sub


def plan_of(sub_id):
    s = stripe_sdk.Subscription.retrieve(sub_id, expand=["items.data.price"])
    return s["items"]["data"][0]["price"]["lookup_key"], s.status


created = []

# Balayage préalable : un essai précédent a pu laisser des objets derrière lui.
swept = 0
for c in stripe_sdk.Customer.list(limit=100).auto_paging_iter():
    if (c.name or "").startswith("kivou-testclock-"):
        tc = c.to_dict().get("test_clock")
        try:
            stripe_sdk.Customer.delete(c.id)
        except Exception as exc:  # noqa: BLE001 - un résidu ne doit pas bloquer la course
            print(f"  residu client {c.id}: {type(exc).__name__}")
        if tc:
            try:
                stripe_sdk.test_helpers.TestClock.delete(tc if isinstance(tc, str) else tc.id)
            except Exception as exc:  # noqa: BLE001
                print(f"  residu horloge: {type(exc).__name__}")
        swept += 1
print(f"balayage prealable : {swept} objet(s) residuel(s) supprime(s)")

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))


try:
    # ── 1. UPGRADE immédiat ──────────────────────────────────────────────────
    print("\n=== 1. upgrade Essential → Scale ===")
    clock, cust, sub = setup("upgrade")
    before, _ = plan_of(sub.id)
    gw.change_subscription_price(
        subscription_id=sub.id, price_id=SCALE.price_id, idempotency_key=f"tc-up-{sub.id}"
    )
    after, status = plan_of(sub.id)
    check(
        "la formule bascule immédiatement",
        after == "kivou_scale_monthly_chf",
        f"{before} → {after}",
    )
    check("l'abonnement reste actif", status == "active", f"status={status}")
    invs = stripe_sdk.Invoice.list(customer=cust.id, limit=10).data

    def is_proration(line):
        # `StripeObject` intercepte `.get` via `__getattr__` : `to_dict()` est la
        # seule conversion sûre — le piège que documente déjà `gateway.py`.
        d = line.to_dict()
        desc = d.get("description") or ""
        return bool(d.get("proration")) or "Remaining time" in desc or "Unused time" in desc

    prorated = [i for i in invs if any(is_proration(l) for l in i.lines.data)]
    check(
        "un prorata a été facturé",
        bool(prorated),
        f"{len(prorated)}/{len(invs)} facture(s) portent une ligne de prorata",
    )

    # ── 2. DOWNGRADE programmé ───────────────────────────────────────────────
    print("\n=== 2. downgrade Scale → Essential, programmé ===")
    sched = gw.schedule_subscription_price(
        subscription_id=sub.id, price_id=ESS.price_id, idempotency_key=f"tc-dn-{sub.id}"
    )
    now_plan, _ = plan_of(sub.id)
    check(
        "les droits COURANTS ne bougent pas",
        now_plan == "kivou_scale_monthly_chf",
        f"toujours {now_plan}",
    )
    check(
        "le changement est lu comme programmé",
        sched is not None and sched.lookup_key == "kivou_essential_monthly_chf",
        f"lookup={getattr(sched, 'lookup_key', None)} au {getattr(sched, 'effective_at', None)}",
    )
    pend = gw.pending_plan_change(subscription_id=sub.id)
    check(
        "pending_plan_change le retrouve",
        pend is not None and pend.lookup_key == "kivou_essential_monthly_chf",
    )

    # ── 3. AVANCE d'horloge au-delà de la période ────────────────────────────
    print("\n=== 3. avance de l'horloge au-delà de la période payée ===")
    target = int(sched.effective_at.timestamp()) + 3600
    stripe_sdk.test_helpers.TestClock.advance(clock.id, frozen_time=target)
    wait_clock(clock.id)
    flipped, status = plan_of(sub.id)
    check("la formule a basculé au terme", flipped == "kivou_essential_monthly_chf", f"→ {flipped}")
    check(
        "aucun second abonnement",
        len(stripe_sdk.Subscription.list(customer=cust.id, status="all").data) == 1,
    )
    check(
        "plus aucun changement en attente", gw.pending_plan_change(subscription_id=sub.id) is None
    )

    # ── 4. ANNULATION d'un downgrade programmé ───────────────────────────────
    print("\n=== 4. annulation d'un downgrade programmé ===")
    clock2, cust2, sub2 = setup("cancel", start_price=PRO)
    gw.schedule_subscription_price(
        subscription_id=sub2.id, price_id=ESS.price_id, idempotency_key=f"tc-dn2-{sub2.id}"
    )
    check(
        "un changement est bien programmé",
        gw.pending_plan_change(subscription_id=sub2.id) is not None,
    )
    gw.release_pending_plan_change(subscription_id=sub2.id)
    kept, status2 = plan_of(sub2.id)
    check(
        "plus aucun changement en attente", gw.pending_plan_change(subscription_id=sub2.id) is None
    )
    check("l'abonnement SURVIT (release, pas cancel)", status2 == "active", f"status={status2}")
    check("la formule reste celle payée", kept == "kivou_pro_monthly_chf", f"={kept}")

    # ── 5. PRORATA REFUSÉ ────────────────────────────────────────────────────
    print("\n=== 5. prorata refusé par la banque ===")
    # L'abonnement doit d'abord être ACTIF : créé d'emblée avec une carte qui
    # refuse, il reste `incomplete`, et Kivou refuserait le changement bien
    # avant Stripe (billing_action != manage_subscription). Le vrai cas est
    # celui d'un client en règle dont le PRORATA est refusé.
    clock3, cust3, sub3 = setup("declined")
    before3, status3 = plan_of(sub3.id)
    assert status3 == "active", f"préalable non tenu: {status3}"
    failing = stripe_sdk.PaymentMethod.attach("pm_card_chargeCustomerFail", customer=cust3.id)
    stripe_sdk.Customer.modify(cust3.id, invoice_settings={"default_payment_method": failing.id})
    refused = False
    try:
        gw.change_subscription_price(
            subscription_id=sub3.id, price_id=SCALE.price_id, idempotency_key=f"tc-fail-{sub3.id}"
        )
    except PlanChangePaymentFailed as e:
        refused = True
        print(f"     (refus attendu: {type(e).__name__})")
    except Exception as exc:  # noqa: BLE001 - on VEUT voir une erreur mal classée
        print(f"     (exception NON classée: {type(exc).__name__}: {str(exc)[:160]})")
    after3, _ = plan_of(sub3.id)
    check("le changement est refusé", refused)
    check("AUCUN droit supérieur accordé", after3 == before3, f"reste {after3}")

finally:
    print("\n=== nettoyage ===")
    for clock_id, cust_id in created:
        try:
            stripe_sdk.Customer.delete(cust_id)
        except Exception as exc:  # noqa: BLE001
            print("  client:", type(exc).__name__)
        try:
            stripe_sdk.test_helpers.TestClock.delete(clock_id)
        except Exception as exc:  # noqa: BLE001
            print("  horloge:", type(exc).__name__)
    print(f"  {len(created)} jeu(x) supprimé(s)")

ko = [n for n, ok, _ in results if not ok]
print("\n" + "=" * 60)
print(f"RÉSULTAT : {len(results) - len(ko)}/{len(results)} vérifications passées")
if ko:
    print("ÉCHECS :")
    [print("  -", n) for n in ko]
sys.exit(1 if ko else 0)
