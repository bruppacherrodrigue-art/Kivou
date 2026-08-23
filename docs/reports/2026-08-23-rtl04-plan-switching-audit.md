# RTL-04 — vérité des plans et changement d'abonnement

**Date :** 2026-08-23 · **Issues :** #27, #29 · **Branche :** `feat/truthful-plan-upgrade-switching`

Ce rapport sépare ce qui est **livré et testé** (#27) de ce qui est **arrêté avant
écriture externe** (#29), et dit précisément pourquoi.

---

## 1. Livré — `upgrade_to` exact (#27)

`locked_detail().access.upgrade_to` rendait la liste fixe `essential / pro / scale`
pour **tout** signal verrouillé. C'était faux : l'accès payant n'est pas « tout ou
rien », chaque plan porte une fenêtre d'historique, et un signal de 400 jours reste
verrouillé après un paiement Essential.

L'éligibilité est désormais calculée en **rejouant la vraie décision d'accès**
(`FeedAccess.is_unlocked`) avec les droits de chaque plan candidat :

```python
def eligible_upgrade_plans(item, *, access):
    if access.is_unlocked(item):
        return ()
    return tuple(p for p in PURCHASABLE_PLANS if access.as_plan(p).is_unlocked(item))
```

Aucune règle de date n'est réécrite — ni dans un second module serveur, ni dans React.
Trier les plans par `history_days` aurait produit une **seconde implémentation** de la
règle d'accès, fausse le jour où l'accès dépendrait d'autre chose que de l'âge.

`paywall.locked_detail()` **reçoit** la liste : la couche d'affichage ne décide plus
d'un droit.

### Comportement vérifié

| Situation | `upgrade_to` |
| --- | --- |
| signal de 0 j / 30 j | `essential, pro, scale` |
| **31 j** (frontière Essential) | `pro, scale` |
| **365 j** (frontière Pro) | `pro, scale` |
| **366 j** | `scale` |
| aucune date exploitable | `scale` — seul `all_available` ouvre un signal non datable |
| compte **Pro**, signal de 400 j | `scale` seul |
| compte **Essential**, signal de 100 j | `pro, scale` |
| compte **Scale** | rien n'est verrouillé |
| signal **déjà offert par Discovery** | **aucune recommandation** — un cadeau ne se refacture pas |
| signal d'un autre compte | `404`, jamais un argumentaire de vente |

La carte verrouillée ne révèle toujours ni entreprise, ni titre, ni montant, ni preuve,
ni source : un test l'affirme en cherchant le nom réel de l'attributaire dans la
réponse sérialisée entière.

---

## 2. Audit Stripe (lecture seule)

### Catalogue TEST (`acct_1TMqChC34k5bO7Y3`)

| Plan | Product | Prices actifs |
| --- | --- | --- |
| Essential | `prod_V63PPw5P5jVpiB` | CHF 49 · EUR 49 |
| Pro | `prod_V63QnoKMxzCE3f` | CHF 99 · EUR 99 |
| Scale | `prod_V63QiyboWkoAOR` | CHF 199 · EUR 199 |

6 prix actifs, tous Kivou, `lookup_key` conformes à `catalogue.LOOKUP_KEYS`.
**Aucun produit Turiya actif** : les 6 produits Turiya présents sont tous `active: false`.

### Catalogue LIVE (`acct_1TMqCOFx3uZwOQKx`) — lecture seule

Structure **identique** : 3 produits Kivou actifs, un par plan, mêmes `kivou_plan_code`.
Aucun produit Turiya actif. **Aucune écriture LIVE n'a été effectuée.**

### Configuration de portail

| | TEST | LIVE |
| --- | --- | --- |
| Configurations | **1 seule** | **1 seule** |
| `is_default` | **`true`** | **`true`** |
| `subscription_update.enabled` | `false` | `false` |
| `subscription_cancel.mode` | `at_period_end` ✅ | `at_period_end` ✅ |

**Le partage avec Turiya est déjà résolu.** La configuration TEST porte
« Gérer votre abonnement **Kivou** », un retour vers `staging.kivou.eu/app/billing` et les
CGU `kivou.eu` — plus aucune chaîne Turiya. Elle a été convertie au Dashboard le
2026-08-21, et `STRIPE_PORTAL_CONFIGURATION_ID` a été posée sur le VPS staging le même
jour. `.env.example` la déclare vide, ce qui est correct pour un gabarit : aucune valeur
d'environnement n'a sa place dans le dépôt.

Reste que la configuration est `is_default: true` — Kivou l'utilise donc à la fois
explicitement et comme défaut de compte. Sans objet Turiya actif, c'est sans conséquence
aujourd'hui ; cela le redeviendrait si un second projet réutilisait ce compte.

---

## 3. Arrêté avant écriture externe — le changement de formule (#29)

### 3.1 Le portail ne peut pas programmer les downgrades Kivou

Documentation Stripe, *Configure the customer portal* → **Manage downgrades** :

> « You can only downgrade at the end of a billing period **between prices that have the
> same product**. »

Kivou utilise **un Product distinct par plan**, en TEST comme en LIVE. Le portail ne peut
donc pas programmer un downgrade Essential ↔ Pro ↔ Scale en fin de période.

Activer `subscription_update` dans le portail donnerait des downgrades **immédiats** :
le client perdrait la période déjà payée. C'est l'inverse de la politique cible
(« downgrade : programmé à la fin de la période déjà payée »).

Deux issues, et **les deux demandent une décision qui n'est pas la mienne** :

1. **Restructurer le catalogue Stripe** en un Product unique à trois Prices — le mandat
   l'interdit explicitement sans décision séparée (« ne restructure pas silencieusement
   le catalogue »), et cela affecte LIVE ;
2. **Construire un flux serveur** de `SubscriptionSchedule` pour programmer la
   transition — techniquement la bonne réponse, mais **non validable ici** (§3.2).

### 3.2 Deux blocages d'environnement, précis et vérifiés

Le connecteur Stripe disponible dans cette session est **partiellement en lecture seule** :

| Opération nécessaire | Disponible ? |
| --- | --- |
| `POST /v1/billing_portal/configurations` | ❌ **absent** — seuls les `GET` sont exposés |
| `POST /v1/subscription_schedules` | ❌ **absent** — seuls les `GET` sont exposés |
| `POST /v1/subscriptions` (créer / modifier) | ✅ disponible |

Ni la CLI `stripe` ni aucune clé secrète Stripe ne sont présentes sur cette machine
(vérifié sans jamais afficher de valeur).

Conséquences :

- la **configuration de portail Kivou dédiée** ne peut pas être créée ici ;
- le **downgrade programmé** ne peut être validé de bout en bout en Stripe TEST —
  or c'est exactement la moitié de la politique cible.

Livrer un chemin d'écriture Stripe non validé, qui touche à de l'argent réel, aurait
contredit la règle même que cette issue défend : ne rien affirmer qu'on n'a pas vu
s'exécuter. La partie externe est donc **arrêtée**, pas bâclée.

### 3.3 Ce que #29 exige encore, et dans quel ordre

1. **Décision produit** — catalogue à Product unique (le portail suffit alors) **ou**
   flux serveur `SubscriptionSchedule` (le catalogue reste tel quel). Recommandation :
   le flux serveur, car restructurer le catalogue touche LIVE et invalide les
   abonnements existants.
2. **Implémenter et valider** les transitions en Stripe TEST avec des comptes
   synthétiques, puis sortir cette PR du mode draft.

La configuration de portail Kivou dédiée, elle, **n'est plus un reste** : elle existe en
TEST comme en LIVE, `subscription_update` désactivé (décision P0-03 inchangée), et elle
est référencée explicitement. Ce point de #29 est **fermé**.

Aucun `price_id` piloté par le navigateur, aucun second abonnement, aucun élargissement
d'entitlements n'a été introduit : `POST /billing/checkout` continue de refuser tout
`price_id` (`extra="forbid"`), et `billing_action` reste la seule autorité frontend.

---

## 4. Garanties

- ❌ aucune modification Stripe **LIVE** — lectures seules ;
- ❌ aucune écriture Stripe **TEST** — l'audit n'a produit aucun objet ;
- ❌ aucun déploiement, aucune fusion ;
- ❌ aucun fichier moteur touché (Hermes, Campaign Factory, Acquisition Engine, Apollo,
  Instantly, Supplier/Contact Discovery, Company Research, scoring/matching) ;
- ❌ `checkoutIntent.ts` **non modifié** — aucun défaut de sécurité ne l'exigeait ;
- ❌ aucun `any` TypeScript, aucun commentaire ESLint de contournement, aucun test désactivé.
