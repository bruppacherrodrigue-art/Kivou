# Backlog — durcissement de la facturation (post-MVP)

Éléments constatés en conditions réelles pendant SPEC-016, **délibérément non
corrigés** dans cette unité de travail. Chacun est borné et documenté ici pour
être instruit séparément, plutôt que réglé au passage par un ajustement discret.

---

## BILL-H1 — Une tentative de paiement reste réservée après un échec définitif

**Statut :** constaté, reproduit, non corrigé. Décision du superviseur, 19 août
2026 : ne pas modifier dans SPEC-016, le parcours de staging contrôlé n'étant
pas bloqué.

### Symptôme

Un appel de création de session Stripe qui échoue pour une raison
**définitivement non rejouable** remonte en `500`. Le compte ne peut alors plus
ouvrir de paiement : chaque nouvel essai rend `409 checkout_in_progress`, et si
l'appelant force le passage, Stripe rejette la requête.

Observé le 19 août 2026 sur `staging.kivou.eu`, en deux temps :

```text
1er appel   stripe._error.InvalidRequestError
            Tax ID collection requires updating business name on the customer.
            → 500 ; la tentative locale reste ouverte

après correctif et redéploiement

2e appel    stripe._error.IdempotencyError
            Keys for idempotent requests can only be used with the same
            parameters they were first used with.
            → 500 ; le compte reste bloqué
```

Le second message est le plus instructif : la clé d'idempotence avait été
enregistrée chez Stripe avec les **anciens** paramètres. Le correctif ayant
changé ces paramètres, tout rejeu de la même clé est refusé — quelle que soit la
qualité du correctif.

### État affecté

Une ligne de `billing_checkout_attempt` pour le compte, non terminale et non
expirée.

```text
src/signals/billing/attempts.py     StoredAttempt.idempotency_key
                                    = f"kivou-checkout:{attempt_id}"
src/signals/billing/schema.py:209   CHECKOUT_ATTEMPT_TTL_MINUTES = 30
src/signals/billing/checkout.py     open_checkout_session()  ← aucun rattrapage
```

La clé d'idempotence est dérivée de l'identifiant de la tentative, persisté
**avant** le premier appel. C'est voulu, et c'est ce qui empêche qu'une reprise
après plantage ouvre une seconde session de paiement. Tant que la tentative
vit, la clé est figée.

Portée : un compte à la fois. Aucune donnée financière n'est en jeu — aucune
session n'a été créée chez Stripe, aucun débit n'existe.

### Rétablissement actuel

**Expiration naturelle : 30 minutes.** Aucune action d'exploitation n'est
nécessaire, et aucune ne raccourcit le délai sans intervention en base. Passé ce
délai, une nouvelle tentative reçoit un nouvel identifiant, donc une nouvelle
clé, et le paiement repart normalement.

### Corollaire d'exploitation

Livrer un changement des **paramètres** de la session de paiement peut immobiliser,
jusqu'à 30 minutes, les comptes qui détenaient une tentative ouverte créée par le
code précédent. Ce n'est pas une régression du correctif : c'est le
fonctionnement attendu de l'idempotence Stripe. À anticiper lors d'un déploiement
touchant `create_checkout_session`.

### Distinction proposée

Classer l'erreur du fournisseur, et n'agir que sur la moitié définitive.

**Terminales — clore la tentative, rendre un code applicatif, autoriser un
nouvel essai immédiat :**

```text
InvalidRequestError     paramètres refusés ; rejouer échouera à l'identique
IdempotencyError        la clé est liée à d'autres paramètres ; rejouer est vain
AuthenticationError     clé absente ou révoquée
PermissionError         la clé n'a pas le droit demandé
```

**Rejouables — garder la tentative ouverte, rejouer la MÊME clé :**

```text
APIConnectionError      la session a peut-être été créée avant la coupure
RateLimitError          simple attente
APIError (5xx)          panne côté fournisseur
```

**Le point à ne pas manquer.** Clore la tentative sur une erreur de la seconde
famille serait un défaut plus grave que celui décrit ici : le réseau peut couper
**après** que Stripe a créé la session. Repartir sur une nouvelle clé
ouvrirait alors un second paiement pour un même abonnement — exactement ce que
tout le module cherche à empêcher. La règle reste donc : on ne libère la
tentative que lorsqu'on sait avec certitude qu'aucune session n'existe.

Un `500` nu est également à remplacer : le client mérite un code lisible
(`billing_provider_rejected`) plutôt qu'une erreur interne.

### Ce qu'il faudra couvrir

* une erreur terminale clôt la tentative et un nouvel essai réussit aussitôt ;
* une erreur rejouable **ne** clôt **pas** la tentative et rejoue la même clé ;
* aucun code d'erreur ne divulgue le message brut du fournisseur ;
* le garde-fou d'unicité reste intact — jamais deux sessions ouvertes pour un
  même compte.
