# P0-03 — gate Stripe TEST de bout en bout sur staging

**Date :** 2026-08-21 · **Verdict : FAIL sur la dernière étape.**

Tout le parcours payant fonctionne — de la découverte au signal déverrouillé.
La résiliation programmée depuis le portail Kivou est en revanche **invisible
dans le produit**, pour une raison que seul un vrai appel Stripe pouvait
révéler. Le détail est en fin de document.

## Contexte

| | |
|---|---|
| HEAD déployé | `954219e694e2ed48105f1e6092f3d8bc3652d32e` (PR #26, rebasée sur `main` = `305a96d`) |
| SHA précédent | `d6f9bbc75d8eddd13dde6eb38e8fca396a84f2da` |
| Révision DB | `0013_personalization` → `0014_compliance` |
| Mode Stripe | TEST exclusivement (`sk_test_`, tous les événements `livemode=false`) |
| Compte | `acc_91OBZ3GuC1mgZCIw2XprbA` — créé pour ce gate, aucun abonnement préalable |

Aucun secret, aucune donnée de carte, aucun identifiant Stripe complet ne figure
dans ce dossier. La capture du formulaire de paiement rempli a été **exclue**
volontairement.

## État avant paiement

- `plan_code: discovery`, `billing_action: choose_plan`, aucun abonnement ;
- ICP réel « Intrants de chantier — France » (matériaux × bâtiment/génie civil) ;
- feed **réel du moteur** : 11 signaux, **3 accordés** (limite Découverte
  atteinte, `remaining_slots: 0`), **8 verrouillés**. Aucune fixture ;
- signal choisi `d390eb11…` : `locked: true`, `unlock_required: "paid_plan"`,
  et le serveur lui-même annonce `access.upgrade_to: [essential, pro, scale]` ;
- attribution datée du 2026-08-07, soit 14 jours — largement dans la fenêtre de
  365 jours de Pro. **Pro le déverrouillera donc réellement** : ce n'est pas une
  supposition, c'est la réponse du serveur ;
- le détail verrouillé ne contient **ni `company`, ni `contract`, ni `source`**.

## Le parcours

| Étape | Résultat |
|---|---|
| `POST /billing/checkout` (pro/chf) | **HTTP 200** — c'est l'appel qui répondait 500 avant P0-03F |
| Session Stripe | `cs_test_a1ZqM7S3…`, `tax_id_collection: true`, `billing_address_collection: required`, Customer existant, 9900 CHF |
| Paiement | carte de test Stripe, mode Sandbox, redirection vers `/checkout/success` |
| Webhooks reçus | `invoice.paid` · `customer.subscription.created` · `checkout.session.completed` — tous `applied`, tous `livemode=false` |
| Tentative locale | `completed` |
| `plan_code` | `discovery` → **`pro`** |
| `subscription_status` | **`active`** |
| `billing_action` | `choose_plan` → **`manage_subscription`** |
| `current_period_end` | 2026-09-21T21:15:56Z |
| Droits | `history_days` 0 → **365**, `max_active_icps` 1 → **3** |
| Signal `d390eb11…` | `locked: true` → **`locked: false`**, données complètes visibles |
| Feed entier | 11 signaux, **0 verrouillé** |

**Le navigateur n'accorde jamais de droit.** La capture `02` le montre
littéralement : le navigateur qui revient de Stripe n'avait pas de session
Kivou, et `/checkout/success` lui présente l'écran de connexion. Le droit est
venu du webhook, pas de l'URL de retour.

## Portail de facturation

Portail **Kivou** (`bpc_1TR9sk…`) : en-tête « Gérer votre abonnement Kivou »,
retour « Return to Kivou - Staging », aucune chaîne Turiya.
**ACTIVE TURIYA OBJECTS = 0** (3 produits actifs, 6 prix actifs, 1 portail —
tous Kivou).

Aucun bouton de changement de plan n'y figure : `subscription_update: false`,
conforme à la consigne, et confirmation visuelle du gap documenté en #29.

## ⛔ Ce qui échoue — la résiliation programmée est invisible

Depuis le portail Kivou, la résiliation a bien été demandée et Stripe l'affiche :
« **Cancels Sep 21** — Your service will end on September 21, 2026 » (capture
`06`). L'écran de revue annonçait « it will still be available until the end of
your billing period on September 21, 2026 ».

Kivou a reçu le webhook `customer.subscription.updated` et l'a **appliqué**
(21:23:26). Et pourtant :

    cancel_at_period_end : False        ← Kivou
    plan_code            : pro
    subscription_status  : active

Parce que Stripe, sur cet abonnement en `billing_mode: flexible`, n'exprime
**pas** la résiliation via `cancel_at_period_end` :

    cancel_at            : 2026-09-21T21:15:56Z   ← identique à current_period_end
    canceled_at          : 2026-08-21T21:23:24Z
    cancellation_details : reason = cancellation_requested
    cancel_at_period_end : false                  ← reste faux

`StripeApiGateway.subscription_state()` ne lit que `cancel_at_period_end`
(`gateway.py:265`) ; `cancel_at` n'apparaît **nulle part** dans `src/`.

**Conséquence produit :** le client résilie, Stripe le sait, mais Kivou l'ignore.
Le bandeau « Résiliation programmée » ne s'affichera jamais, et rien dans le
produit ne dit que l'accès s'arrête le 21 septembre. Le client croit rester
abonné.

**Ce qui fonctionne malgré tout :** l'accès reste actif — `plan_code: pro`,
feed à 0 verrouillé, signal toujours ouvert. C'est le comportement attendu ;
seule la *communication* de l'échéance manque.

**Pourquoi les tests ne le voyaient pas :** même cause que P0-03F. Le faux
`StripeGateway` renvoie ce qu'on lui a appris à renvoyer, jamais ce que Stripe
décide réellement. Un correctif demande une issue dédiée — il n'est pas dans le
périmètre de ce gate.

## Captures

| Fichier | Contenu |
|---|---|
| `01-checkout-stripe-test.png` | Checkout Stripe TEST — « Subscribe to Kivou Pro », CHF 99.00/mois |
| `02-retour-checkout-success.png` | Retour sur `/checkout/success` sans session : aucun droit accordé par le navigateur |
| `03-portail-kivou.png` | Portail Kivou — abonnement Pro, aucun changement de plan proposé |
| `04-motif-resiliation.png` | Modale de motif de résiliation |
| `05-revue-avant-resiliation.png` | « available until the end of your billing period on September 21, 2026 » |
| `06-resiliation-programmee.png` | « Cancels Sep 21 » côté Stripe — que Kivou n'affiche pas |


---

# Seconde exécution — 2026-08-22, HEAD `954219e`

`main` avait avancé de `117fc96` à `305a96d` — **un seul commit, purement
documentaire** (SPEC-026, aucun code). La PR a été rebasée dessus et le gate
rejoué **intégralement sur un compte neuf**, pour que la preuve soit autonome et
porte sur le SHA réellement déployé.

Compte : `acc_H8hbMYUPlSzwSDj4Tf2epg`, créé pour cette exécution.

| Étape | Résultat |
|---|---|
| État initial | `discovery`, `billing_action: choose_plan` |
| Feed réel | 5 signaux — 3 accordés (`remaining_slots: 0`), 2 verrouillés |
| Signal `fd553883…` | `locked: true`, `unlock_required: paid_plan`, `upgrade_to: [essential, pro, scale]`, attribution 2026-08-07 ; **aucune fuite** `company`/`contract`/`source` |
| `POST /billing/checkout` | **HTTP 200** — session `cs_test_a1QdlgNd…` |
| Paiement | carte de test, redirection `/checkout/success` |
| Webhooks | `invoice.paid` · `customer.subscription.created` · `checkout.session.completed` — `applied`, `livemode=false`, 01:42:07 |
| Tentative | `completed` |
| Après paiement | `plan_code: pro` · `subscription_status: active` · `billing_action: manage_subscription` · `history_days: 365` · `max_active_icps: 3` |
| Signal `fd553883…` | **`locked: false`**, société et acheteur visibles |
| Feed | 5 signaux, **0 verrouillé** |
| Portail | Kivou, aucun changement de plan proposé |
| Résiliation | Stripe : « **Cancels Sep 22** — Your service will end on September 22, 2026 » |
| Webhook de résiliation | `customer.subscription.updated` **appliqué** à 01:43:12 |
| Kivou | `cancel_at_period_end` : **`False`** ⛔ |
| Accès après résiliation | conservé — `pro`, feed à 0 verrouillé |

## Le défaut est déterministe

Sur la première exécution, `cancel_at_period_end` était encore `False`
**plus de six heures** après la demande — ce n'était donc déjà pas un retard de
webhook. La seconde exécution le confirme sur un compte neuf, un abonnement
neuf et un SHA neuf : le webhook est reçu et appliqué en une seconde, et le
champ reste faux.

Cause inchangée : sur `billing_mode: flexible`, Stripe écrit `cancel_at` et
laisse `cancel_at_period_end` à `false`. La passerelle ne lit que le second.
Issue **#38**.

| Fichier | Contenu |
|---|---|
| `07-run2-portail-kivou.png` | Portail Kivou, seconde exécution |
| `08-run2-revue-avant-resiliation.png` | « available until … September 22, 2026 » |
| `09-run2-resiliation-programmee.png` | « Cancels Sep 22 » côté Stripe — que Kivou n'affiche pas |


---

# Exécution finale — 2026-08-22, HEAD `0d0d725`, DB `0015`

Le gate complet, rejoué après la fusion de #38 (`main` = `d6de1f8`) et
l'intégration du contrat `scheduled_cancellation_at` côté frontend.

**Verdict : PASS.** Le point qui faisait échouer le gate précédent — la
résiliation programmée invisible — est fermé, et vérifié de bout en bout contre
le vrai Stripe TEST.

| | |
|---|---|
| SHA déployé | `0d0d72554e2a53baeac12250dc8358b6057e0230` |
| SHA précédent | `954219e694e2ed48105f1e6092f3d8bc3652d32e` |
| DB | `0014_compliance` → **`0015_scheduled_cancellation`** |
| Compte | anonymisé — `acc_pgiU…LA6g`, créé pour cette exécution |
| Signal | `f2d1ee3cd154…` |
| Mode Stripe | TEST exclusivement, tous les événements `livemode=false` |

## Continuité de session — le gate ajouté cette fois

Un **seul contexte navigateur** de l'inscription au retour de Stripe. Aucune URL
de retour ouverte à la main, aucune reconnexion.

| Moment | Cookie | `/me` | Compte |
|---|---|---|---|
| avant Stripe | `kivou_session` présent | **200** | `acc_pgiU…LA6g` |
| après retour automatique de Stripe | `kivou_session` présent | **200** | `acc_pgiU…LA6g` — le même |

La session survit à l'aller-retour. Aucun `POST-STRIPE SESSION CONTINUITY GAP`.

## Le parcours

| Étape | Résultat |
|---|---|
| État initial | `discovery` · `choose_plan` · `scheduled_cancellation_at: null` |
| Feed réel | 5 signaux — 3 accordés, 2 verrouillés |
| Signal choisi | `locked: true`, `unlock_required: paid_plan`, `upgrade_to: [essential, pro, scale]` |
| Checkout | redirection **automatique** vers `checkout.stripe.com`, Pro CHF 99 |
| Paiement | carte de test, redirection **automatique** vers `/checkout/success` |
| Webhooks | `invoice.paid` · `customer.subscription.created` · `checkout.session.completed` — `applied`, `livemode=false`, 06:51:03 |
| Tentative | `completed` |
| UI | « Paid access active » après sondage de `/billing/status` |
| Après paiement | `pro` · `active` · `manage_subscription` |
| Signal | `locked: true` → **`false`**, société visible |
| Feed | 5 signaux, **0 verrouillé** |

## Portail et résiliation programmée

Portail **Kivou** : branding Kivou, **zéro chaîne Turiya**, **aucun changement de
plan proposé** (`subscription_update: false`), annulation disponible.

Résiliation demandée en fin de période. Stripe affiche « Cancels Sep 22 ».
Webhook `customer.subscription.updated` **appliqué** à 06:52:17.

Ce que Kivou en dit désormais :

```
plan_code                 : pro
subscription_status       : active
billing_action            : manage_subscription
scheduled_cancellation_at : 2026-09-22T06:50:59+00:00
cancel_at_period_end      : true
current_period_end        : 2026-09-22T06:50:59+00:00
```

Persisté en base, colonne `0015` comprise — vérifié directement.

**L'écran affiche :** « Cancellation scheduled — Your subscription will end at
the end of the current period, on 22 September 2026. » La date vient de
`scheduled_cancellation_at`, jamais d'un calcul local.

**L'accès reste actif :** signal toujours `locked: false`, feed à 0 verrouillé.
Une échéance annoncée ne coupe rien — Stripe reste l'autorité sur le moment où
l'accès cesse.

## Ce qui a changé depuis l'exécution précédente

Le gate d'hier échouait ici même : Stripe annonçait « Cancels Sep 21 » et Kivou
répondait `cancel_at_period_end: false`, sans aucune notice. Sur un abonnement
`billing_mode: flexible`, Stripe exprime la résiliation par `cancel_at` et laisse
le booléen à `false`. P0-03G lit désormais la date ; le frontend l'affiche sans
jamais l'emprunter à `current_period_end`.

| Fichier | Contenu |
|---|---|
| `final-02-signal-verrouille.png` | Le signal verrouillé, avant paiement |
| `final-03-billing-discovery.png` | Grille des offres, compte Découverte |
| `final-04-stripe-checkout.png` | Checkout Stripe TEST — Kivou Pro, CHF 99 |
| `final-05-retour-checkout-success.png` | Retour automatique, session conservée |
| `final-06-acces-payant-actif.png` | « Paid access active » |
| `final-07-signal-deverrouille.png` | Le même signal, ouvert |
| `final-08-billing-pro.png` | Facturation Pro, aucune notice de résiliation |
| `final-09-portail-kivou.png` | Portail Kivou, sans changement de plan |
| `final-10-resiliation-programmee-stripe.png` | « Cancels Sep 22 » côté Stripe |
| `final-11-notice-resiliation-kivou.png` | La notice Kivou et sa date |
| `final-12-signal-toujours-ouvert.png` | L'accès survit à l'échéance annoncée |
