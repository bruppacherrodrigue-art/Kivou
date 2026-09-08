# SPEC-013 — Facturation Stripe, droits et mur payant Discovery

**Date** : 2026-08-18
**Portée** : `DISCOVERY → 3 SIGNAUX RÉELS → FEED VERROUILLÉ → CHECKOUT → ABONNEMENT → WEBHOOK VÉRIFIÉ → DROITS → FEED OUVERT`
**Statut** : livré, audité, catalogue créé en TEST **et** en LIVE, **non committé**
**Verdict** : **SPEC-013 READY TO COMMIT** (après R1 §26–§31 et le closeout final §32–§42)

---

## 1. Porte d'entrée — SPEC-012 est committée

```
$ git log -4 --oneline
3757678 feat(saas): add customer signal feed
1d894eb feat(saas): add account auth and ICP onboarding
30d431c feat(saas): add signal persistence foundation
05ecfd7 feat(signals): add multi-clock recency and France ingestion
```

**SPEC-012 : `3757678e37c119e62ec92788e9d46f79ce3292cb`**, après `1d894eb` et
`30d431c`. Les fichiers hors périmètre (`*.docx`, `*:Zone.Identifier`,
SPEC-009C, `spec006-postmortem`) sont restés non suivis et non modifiés.

## 2. Audit Stripe MCP

L'audit lecture seule a d'abord été **bloqué** : le serveur MCP n'était pas
authentifié, et §2 interdit toute écriture avant l'audit. Le titulaire du compte
a complété OAuth au closeout R1 ; l'audit complet et les écritures TEST figurent
au **§27**. Aucune écriture n'a été tentée avant cet audit.

## 3. Ce qui a été construit malgré le blocage

Toute la couche applicative — schéma, droits, checkout, webhooks, mur payant —
ne dépend pas de l'audit. Elle est livrée, testée hors-ligne, et prête à être
branchée sur un catalogue Stripe conforme à §6.

### SDK

`stripe>=11.0` (installé : **15.5.0**, version d'API par défaut du SDK
`2026-07-29.dahlia`). Il n'est appelé que derrière la passerelle : la suite de
tests ne touche jamais le réseau.

### Séparation faisant autorité

```
STRIPE  →  faits de paiement       (gateway.py)
KIVOU   →  règles d'accès produit  (catalogue.py)
```

Un `price_...` ne devient jamais une règle d'autorisation. La correspondance va
dans un seul sens : `Price → lookup_key → plan Kivou → droits`. Un prix inconnu
rend **aucun** droit payant, jamais un repli sur Pro.

## 4. Catalogue Kivou

| Plan | Prix mensuel | ICP actifs | Historique | Territoires | Filtres |
|---|---|---|---|---|---|
| `discovery` | — (droit interne) | 1 | aucun général, 3 signaux offerts | 1 | minimum |
| `essential` | 49 CHF **ou** 49 EUR | 1 | 30 jours | 1 | basique |
| `pro` *(recommandé)* | 99 CHF **ou** 99 EUR | 3 | 365 jours | non plafonné | avancé |
| `scale` | 199 CHF **ou** 199 EUR | 10 | tout l'historique persisté | non plafonné | avancé |

Mensuel uniquement, aucun annuel. **Aucune conversion de change** : 49 CHF ou
49 EUR est une décision commerciale, pas un taux.

Discovery n'est **pas** un abonnement Stripe à 0 : ce serait une facture pour
rien et un objet de plus à réconcilier.

§24 — aucun plafond de territoires n'est inventé pour Pro ou Scale. Discovery et
Essential sont limités à un territoire actif par ICP ; au-delà, Kivou n'a pas de
couverture à vendre que ses sources ne fournissent pas.

§27 — `export_level` et `alert_cadence` sont **descriptifs**. Aucun export,
aucune alerte n'existe ; ils décrivent le catalogue, ils ne promettent aucun
fonctionnement.

### Clés de recherche attendues côté Stripe

```
kivou_essential_monthly_chf   4900    kivou_essential_monthly_eur   4900
kivou_pro_monthly_chf         9900    kivou_pro_monthly_eur         9900
kivou_scale_monthly_chf      19900    kivou_scale_monthly_eur      19900
```

Le code ne connaît **que** ces clés. C'est ce qui permettra à §36 de créer les
objets Stripe sans toucher une ligne, et à une future hausse de prix de
transférer la clé au nouveau `Price`.

## 5. Base de données — migration `0003_billing`

Quatre tables, **strictement additives** : quatre `create_table`, cinq
`create_index`, aucun `drop_table`, aucun `alter_column`, aucune table
antérieure nommée.

| Table | Rôle | Garantie portée par le schéma |
|---|---|---|
| `billing_customer` | un client Stripe par compte | `account_id` **clé primaire** : deux clients Stripe pour un compte sont structurellement impossibles |
| `billing_subscription` | l'abonnement synchronisé | `stripe_subscription_id` unique ; `last_stripe_event_created_at` porte l'antériorité (§17) |
| `stripe_webhook_event` | les événements traités | `stripe_event_id` **clé primaire** : la seconde livraison ne peut pas s'insérer (§18) |
| `discovery_signal_grant` | les trois signaux offerts | `(account_id, signal_key)` clé primaire : un déblocage ne se duplique pas |

**Rien de sensible n'est stocké** : ni carte, ni moyen de paiement, ni clé, ni
secret de webhook, ni charge brute d'événement — seulement une empreinte
SHA-256 du corps, assez pour tracer, rien à divulguer. Deux tests le vérifient
sur les noms de colonnes.

Pas de clé étrangère de `discovery_signal_grant.signal_key` vers
`materialized_signal` : un déblocage doit survivre à une rematérialisation, et
la contrainte forcerait une reconstruction destructive sous SQLite — même
déviation que SPEC-011 §9, pour la même raison.

## 6. Points d'entrée

| Méthode | Chemin | Authentification |
|---|---|---|
| GET | `/billing/plans` | publique |
| GET | `/billing/status` | session |
| POST | `/billing/checkout` | session + CSRF d'origine |
| POST | `/billing/portal` | session + CSRF d'origine |
| POST | `/webhooks/stripe` | **signature Stripe**, ni session ni CSRF |

`/webhooks/stripe` est le seul point d'entrée `async` du dépôt : il doit lire le
corps **brut**, que Starlette n'expose qu'en asynchrone. Le traitement qui suit
reste synchrone.

## 7. Webhooks — les trois pièges, et comment chacun est fermé

### Événements écoutés (§16)

```
checkout.session.completed        customer.subscription.created
customer.subscription.updated     customer.subscription.deleted
invoice.paid                      invoice.payment_failed
```

Plus `invoice.payment_action_required`, **reconnu et journalisé sans accorder
d'accès** : une action de paiement requise est l'inverse d'un paiement. Tout
autre type est enregistré `unhandled` et n'a aucun effet.

### Idempotence (§18)

`stripe_event_id` est la clé primaire. L'enregistrement de l'événement et la
transition partagent **une seule transaction** : une transition à moitié
appliquée n'est jamais confirmée, et Stripe pourra relivrer. Une seconde
livraison rend `duplicate` sans rien rejouer.

### Indépendance à l'ordre (§17)

Aucun enchaînement n'est supposé. Tout événement porteur d'un abonnement
déclenche une **relecture de l'objet courant** chez Stripe : l'état courant ne
dépend d'aucun ordre. Et un événement **plus ancien** que celui déjà appliqué
est refusé — un passé ne réécrit pas le présent.

Trois tests couvrent exactement les scénarios demandés : `subscription.updated`
avant `checkout.session.completed`, `invoice.paid` avant l'événement
d'abonnement, et une relivraison ancienne après une résiliation. Un quatrième
vérifie que la charge de l'événement ne l'emporte jamais sur l'objet courant :
l'événement dit `active`, Stripe dit `past_due`, Kivou enregistre `past_due`.

### Vérification (§15)

`stripe.Webhook.construct_event` sur le corps **brut**. Signature absente,
calculée avec un autre secret, ou corps altéré d'un seul octet : `400`, et rien
n'est écrit. Les tests calculent un en-tête `Stripe-Signature` **authentique**
(HMAC-SHA256 sur « horodatage.corps ») et exercent le vrai code de
vérification, hors-ligne — simuler cette vérification reviendrait à ne pas la
tester.

## 8. Statut Stripe → accès (§10)

| Statut Stripe | Accès Kivou |
|---|---|
| `active` sur un prix du catalogue | droits du plan |
| `active` + `cancel_at_period_end` | **droits conservés** jusqu'à ce que Stripe termine |
| `past_due`, `unpaid`, `incomplete`, `incomplete_expired`, `canceled`, `paused`, `trialing`, inconnu | Discovery |
| prix hors catalogue, quel que soit le statut | Discovery |
| aucun abonnement | Discovery |

Aucune période de grâce n'est inventée. Une résiliation programmée ne retire
rien : Stripe garde l'abonnement `active` jusqu'à la fin de la période payée, et
inventer une coupure côté Kivou reviendrait à retirer un accès déjà réglé.

**Le repli est toujours restrictif.** Un défaut permissif — « en cas de doute,
Pro » — est une faille qui attend son incident.

## 9. Checkout (§11 à §14)

Le client envoie **un plan et une devise**. Rien d'autre :

```json
{"plan": "pro", "currency": "chf"}
```

`extra="forbid"` : un `price_id`, un `success_url` ou un `founding` glissés dans
le corps font échouer la requête en **422**, ils ne sont pas ignorés en silence.
Le serveur résout le prix par clé de recherche, vérifie son mode
(`livemode`), sa devise et son activité.

- Un client Stripe est créé **une fois** par compte, avec une clé d'idempotence
  dérivée du compte : un double clic ne peut pas produire deux clients.
- La session porte `client_reference_id` **et** propage
  `subscription_data.metadata.kivou_account_id` — deux chemins de
  réconciliation, écrits par Kivou lui-même.
- Les URL de retour viennent de la configuration, jamais de la requête : une URL
  de succès fournie par le client serait une redirection ouverte.
- Un compte déjà abonné reçoit **409 `already_subscribed`** et est renvoyé vers
  le portail — pas une seconde facturation.

### §14 — la redirection de succès n'autorise rien

Test dédié : après un checkout, une visite de l'URL de succès et de toutes les
routes de lecture laisse `billing_subscription` **vide** et le compte en
Discovery. Aucun point d'entrée n'accepte un plan comme état à écrire.

## 10. Portail client (§19)

`POST /billing/portal` crée une session de portail Stripe pour le client du
compte, avec une URL de retour configurée. Sans client Stripe : **409
`no_billing_customer`** — il n'y a rien à gérer. Kivou ne reconstruit aucun
écran de moyen de paiement, de facture ni de résiliation.

Le changement de plan depuis le portail n'est **pas** activé dans cette SPEC :
il ferait franchir une frontière de devise et de droits que rien ne teste
encore. La configuration TEST correspondante fait partie de §36, non réalisée.

## 11. Discovery — trois signaux, donnés une fois (§20)

Ce n'est **pas** « les 3 signaux les plus récents » : ce serait un produit
gratuit permanent, renouvelé chaque matin. Ce sont **trois signaux nommés**,
débloqués une fois et conservés.

- La file d'attente est le **feed par défaut** de SPEC-012 — propriété du
  compte, profil actif, identité affichable, sémantique d'événement courante,
  ordre déterministe. Elle est **toujours** celle du feed par défaut, jamais
  celle que le client a demandée : faire dépendre les cadeaux d'un paramètre
  d'URL permettrait de les choisir.
- Moins de trois éligibles : on donne ce qu'il y a, et les places restantes se
  remplissent plus tard.
- Une fois les trois attribués, **ils ne tournent plus**.
- Un signal offert **reste ouvert quel que soit son âge** : il a été donné, pas
  prêté.

## 12. Mur payant (§21)

Le teaser est **construit champ par champ**, jamais obtenu en retirant des
champs de la carte complète — une liste noire oublierait le champ ajouté le mois
prochain.

**Ce qu'un signal verrouillé montre** : `locked`, statut et date de l'événement,
`why_now`, pays de la source et pays d'exécution, secteur, **ordre de grandeur**
du contrat, nombre d'hypothèses, et une phrase qui décrit l'événement sans
sujet nommé.

**Ce qu'il ne montre jamais** : nom de l'attributaire, identifiant d'entreprise,
acheteur, intitulé du marché, URL source, preuve, raisonnement des besoins,
détail d'adéquation. Quatre tests balaient la réponse à la recherche de ces
fuites.

Le montant exact est remplacé par un palier (`under_50k`, `50k_250k`,
`250k_1m`, `1m_5m`, `over_5m`) : rendu au centime, il identifie souvent le
marché à lui seul.

La phrase verrouillée a sa propre table de formulation. `recency.claim` reste
l'autorité pour un signal débloqué, mais ses gabarits parlent d'une entreprise
**nommée** : les rendre avec un nom vide produisait « vient de remporter un
marché public. », une phrase sans sujet. Le mur a donc ses propres phrases, qui
décrivent l'événement et n'affirment jamais plus que le statut n'autorise.

`GET /signals/{key}` sur un signal verrouillé rend **200** avec l'aperçu et
`access.granted = false`, pas 404 : le compte **possède** ce signal, il ne l'a
pas payé. Confondre « pas à vous » et « pas encore accessible » empêcherait de
dire au client ce que le paiement débloquerait.

## 13. L'ordre d'évaluation (§22)

```
propriété du compte → identité affichable → politique de signal
                    → droit du plan → accès
```

La facturation est la **dernière** condition. Deux tests le prouvent : un compte
Scale ne voit ni le signal d'un autre compte, ni un signal d'avant les comptes.
Le module d'accès reçoit une page **déjà** restreinte par SPEC-011 et SPEC-012 ;
il ne peut donc pas, même par erreur, élargir la propriété.

## 14. Limites d'ICP (§23)

Discovery 1, Essential 1, Pro 3, Scale 10, Fondateur 3 (droits de Pro).

**Règle de sous-ensemble, la plus simple qui soit stable** : les profils actifs
les plus anciens d'abord, par `created_at` puis `target_icp_id`. Sur un
déclassement :

- **rien n'est supprimé**, rien n'est désactivé ;
- le sous-ensemble servi est déterministe et identique d'une lecture à l'autre ;
- `/billing/status` rend `target_icps_over_limit`, et le client tranche.

Un test vérifie qu'après un déclassement de Pro à Essential, les trois profils
existent toujours, tous `active`, et que deux sont nommés hors limite.

## 15. Historique (§25) et filtres (§26)

L'historique est mesuré sur la date de l'événement **courant** — celle que le
client lit. Essential ouvre 30 jours, Pro 365, Scale tout ce qui est persisté.

**Une fenêtre plus large n'autorise jamais une formulation de nouveauté sur un
signal ancien** : test dédié, un signal de mai lu par un compte Scale reste
`stale_award` et ne dit pas « vient de remporter ». La fenêtre décide de ce
qu'on montre, la politique de fraîcheur de ce qu'on en dit.

Les filtres sont ceux de SPEC-012, sans nouveau moteur :

| Filtre | Niveau exigé |
|---|---|
| `target_icp_id`, `freshness` | minimum |
| `country`, `primary_event` | basique |
| `winner` | avancé |

Un filtre hors du plan rend **403 `filter_not_entitled`** avec le filtre et le
niveau requis — jamais une page silencieusement non filtrée, qui ferait croire
au client que sa recherche ne trouve rien.

## 16. Offre fondateur (§7, §33)

`pro` + remise privée de 70 (CHF ou EUR) sur 12 mois → **29**, puis le prix Pro
normal reprend. Persistée comme `offer_code = "founding"`, `plan_code = "pro"`.

**Kivou compte lui-même les comptes fondateurs** : `max_redemptions` chez Stripe
compte des utilisations de coupon, pas des clients. `founding_accounts()`
compte des `account_id` **distincts**, plafonnés à 5, et un compte ne peut pas
prendre deux places.

L'éligibilité est une **liste serveur** (`app.state.founding_accounts`). Aucun
code promotionnel public, aucun paramètre d'URL : trois tests vérifient que
`?founding=true` et un champ `founding` dans le corps ne donnent rien.

**Le coupon Stripe correspondant n'a pas été créé** — il fait partie de §36,
bloquée par §2.

## 17. Configuration (§30)

```
KIVOU_STRIPE_MODE                 test | live, jamais déduit
STRIPE_SECRET_KEY                 jamais journalisée, jamais rendue
STRIPE_WEBHOOK_SECRET
STRIPE_SUCCESS_URL                https absolue obligatoire
STRIPE_CANCEL_URL                 https absolue obligatoire
STRIPE_PORTAL_RETURN_URL          https absolue obligatoire
STRIPE_AUTOMATIC_TAX_ENABLED      faux par défaut (§29)
STRIPE_FOUNDING_COUPON_ID
```

**Le contrôle le plus important** : une clé `sk_live_…` avec
`KIVOU_STRIPE_MODE=test` — ou l'inverse — fait **échouer le démarrage**. C'est
la panne la plus coûteuse d'une intégration Stripe : elle ne se voit qu'au
moment où un vrai client paie sur des objets de test. Le contrôle porte sur le
préfixe, seule information non secrète de la clé.

À l'exécution, `livemode` est vérifié sur chaque `Price`, `Customer`,
`Subscription` et événement synchronisé. Un objet du mauvais mode est refusé
(`stripe_mode_mismatch`), et un événement de production reçu par une application
de test est rejeté en `400` sans rien écrire.

Sans passerelle Stripe injectée, les points d'entrée de facturation rendent
**503** : mieux vaut un service annoncé indisponible qu'une application qui
démarre en croyant pouvoir encaisser.

## 18. Stripe Tax (§29)

`automatic_tax = false` par défaut, et **non modifié** : l'audit n'a pas eu lieu,
donc aucune décision fiscale n'est prise. Le drapeau est piloté par
configuration et testé dans les deux positions.

Le checkout collecte déjà de quoi facturer correctement plus tard —
`tax_id_collection` activé, adresse de facturation requise — **sans déduire
aucune obligation fiscale dans Kivou**. La configuration fiscale reste une porte
de lancement séparée.

**Résultat de l'audit fiscal : non disponible** (§2).

## 19. Secrets (§31)

Un test balaie `src/signals/billing`, `src/signals/api`, `tests`,
`docs/reports` et `pyproject.toml` à la recherche des préfixes `sk_test_`,
`sk_live_`, `rk_*`, `whsec_`, `pk_live_`. Trois tests l'accompagnent : le
balayage **peut** échouer (témoins assemblés à l'exécution pour ne pas se
signaler lui-même), les identifiants d'objets (`prod_`, `price_`, `coupon_`) ne
sont pas visés, et la couverture inclut bien le code de facturation, les tests
et les rapports.

En cas de détection, le message d'échec ne rend que le **chemin** : recopier la
clé la ferait entrer dans les journaux de CI.

## 20. Tests

**Total du dépôt : 2602 tests, 0 échec, 0 ignoré.** (Base SPEC-012 : 2380.)

| Fichier | Tests | Objet |
|---|---|---|
| `tests/test_billing_entitlements.py` | 38 | §10, §23, §28, §30, §34 — statuts, limites, migration |
| `tests/test_billing_catalogue.py` | 37 | §5, §6, §9, §32 — plans, prix, prix inconnu |
| `tests/test_billing_checkout.py` | 36 | §11 à §14, §19, §33 — checkout, portail, fondateur |
| `tests/test_billing_paywall.py` | 29 | §20 à §26 — Discovery, teaser, historique, filtres |
| `tests/test_billing_single_subscription.py` | 27 | **R1 §2 à §5** — unicité, conflit, concurrence |
| `tests/test_billing_webhooks.py` | 20 | §15 à §18 — signature, idempotence, ordre |
| `tests/test_billing_secrets.py` | 6 | §31 — aucun secret dans le dépôt |
| `tests/test_billing_checkout_lock.py` | 29 | **closeout final** — verrou avant Stripe Checkout |
| **Total SPEC-013** | **222** | |

`tests/billing_helpers.py` porte la fausse passerelle et les fabriques. **Aucun
test n'appelle Stripe par le réseau.**

### Tests SPEC-012 adaptés — et pourquoi

Cinq fichiers de tests SPEC-012 ont été modifiés : leurs comptes sont désormais
**abonnés**. Ces tests portent sur le contenu d'un signal débloqué — faits,
inférences, preuve, langue, fraîcheur — et un compte Discovery verrouille
désormais tout sauf trois signaux. Sans abonnement, ils cesseraient de porter
sur leur objet. **Aucune assertion n'a été affaiblie** ; seul le contexte de
compte a changé, et le mur payant a ses propres tests. Un test de SPEC-011 voit
sa révision de tête attendue passer à `0003_billing`.

## 21. Ce que les tests ont trouvé

1. **`StripeObject` n'est ni un `dict` ni un mapping.** `dict(objet)` le
   parcourt comme une séquence et `.items()` est intercepté par son
   `__getattr__` ; la conversion correcte est `to_dict()`. En production, cela
   aurait cassé au premier webhook.
2. **Deux abonnements « actifs » rendaient le plan non déterministe.** Corrigé
   d'abord par un ordre explicite, puis — au closeout R1 — par la seule bonne
   réponse : une contrainte d'unicité (§26).
3. **Le sous-ensemble d'ICP servi dépend de `created_at`**, et deux profils
   créés dans le même instant se départagent par identifiant. Stable d'une
   lecture à l'autre, mais imprévisible pour un test qui les crée d'un bloc ;
   les tests avancent donc l'horloge.

## 22. Non-régression (§38, R1 §13)

`git status --porcelain` ne rend **rien** sur
`src/signals/{understanding,needs,matching,documents,connectors,recency,france,domain,accounts}`,
ni sur `persistence/{schema,materialization,opportunity}.py`. Moteur de signaux,
fraîcheur, BOAMP/DECP/SIMAP/TED, preuve, propriété de compte, authentification,
sémantique TargetICP, identité d'opportunité, séparation faits/inférences,
bancs historiques : **inchangés**. Aucun nouveau banc commercial.

Deux fichiers antérieurs sont touchés, tous deux de façon additive :

- `src/signals/feed/query.py` (+8 lignes) : un paramètre facultatif
  `allowed_target_icp_ids`, appliqué **après** la restriction de propriété — il
  ne peut donc pas élargir ce que le compte possède ;
- `src/signals/api/routes_signals.py` : la décision d'accès et le rendu
  verrouillé, ajoutés au bout de la chaîne.

R1 §13 vérifié : déblocages Discovery, teaser verrouillé, catalogue de droits,
limites d'ICP, limites d'historique, propriété client, fraîcheur courante,
sémantique de signal, vérification de signature et de mode Stripe, moteur,
authentification et preuve sont **inchangés**.

---

# R1 — Closeout : unicité d'abonnement et configuration Stripe

## 26. Un compte, un abonnement (R1 §2 à §5)

### Le défaut

Le schéma autorisait plusieurs lignes `billing_subscription` pour un
`account_id`, et le service en choisissait une par tri. **Le tri est la
mauvaise réponse** : deux abonnements Stripe, ce sont deux factures et deux
prélèvements. Départager par plan, par prix ou par date reviendrait à décider
seul lequel le client paie — alors que dans les deux cas il paie déjà.

### Schéma d'unicité

`0003_billing` étant encore non committée, elle a été régénérée :

```text
account_id              String(64)   FK account  NOT NULL  UNIQUE   ← R1 §2
stripe_subscription_id  String(128)              NOT NULL  UNIQUE
```

La table décrit l'abonnement **courant**. Le MVP n'a pas besoin d'historique de
facturation ; une table dédiée pourra en tenir un le jour où il servira.
`current_subscription()` n'a plus aucun critère de départage — il n'y a plus rien
à départager.

### Accès ≠ existence (R1 §3)

C'est la distinction que le closeout a rendue explicite, et elle est écrite dans
`schema.is_open_subscription` :

| Statut Stripe | Accès Kivou | Abonnement existe | Nouveau checkout |
|---|---|---|---|
| `active` | plan payé | oui | **bloqué** |
| `incomplete`, `trialing`, `past_due`, `unpaid`, `paused` | **Discovery** | **oui** | **bloqué** |
| `canceled`, `incomplete_expired` | Discovery | non | **autorisé** |
| statut inconnu | Discovery | **oui** | **bloqué** |

**Le défaut est fermé par construction** : le test porte sur l'appartenance aux
états **terminaux**, pas aux états ouverts. Un statut que Stripe inventerait
demain bloque donc, au lieu de passer à travers — et un test le vérifie sur une
valeur inventée.

### Conflit explicite (R1 §5)

`BillingSubscriptionConflict` est levée quand un second abonnement non terminal
arrive pour un compte qui en porte déjà un d'ouvert. Alors :

- **aucun gagnant n'est choisi** — ni le plus cher, ni le plus récent ;
- l'abonnement courant **reste intact** ;
- le webhook enregistre `conflict` et rend 200 (relivrer produirait le même
  conflit) ;
- **aucun abonnement Stripe n'est résilié automatiquement** — un test analyse le
  source des trois modules de facturation pour l'interdire.

Si l'abonnement existant est **terminal**, la règle explicite s'applique : il est
remplacé par le nouveau. Testé sur les deux statuts terminaux.

### Concurrence et reprises (R1 §4)

Trois protections, de la plus forte à la plus faible :

1. **la contrainte d'unicité** — deux abonnements courants ne peuvent pas
   coexister en base, quel que soit le chemin qui y mène ;
2. **le contrôle avant checkout** — un abonnement ouvert bloque l'ouverture
   d'une session, et le test vérifie qu'aucune session Stripe n'est créée ;
3. **la clé d'idempotence** stable par (compte, plan, devise, offre) — deux
   requêtes identiques rendent la même session Stripe, pas deux paiements.

**Ce qui reste, et qui est assumé** : Kivou ne peut pas empêcher un client
déterminé de terminer deux sessions ouvertes dans le même instant, avant toute
synchronisation — Stripe créerait alors deux abonnements. Ce qui est garanti,
c'est qu'**aucun chemin silencieux n'existe** : la seconde synchronisation lève
un conflit explicite. Aucun marqueur de checkout en attente n'a été ajouté :
il n'apporterait rien de plus que la contrainte, et §4 demande le plus petit
dispositif robuste.

### Tests R1 (27)

Six statuts ouverts bloquent chacun un second checkout et n'ouvrent aucun droit ·
les deux statuts terminaux libèrent la place · un statut inconnu échoue fermé ·
la base **refuse** structurellement une seconde ligne (`IntegrityError`) · le
conflit est explicite, nomme les deux abonnements, et ne donne pas le plan le
plus cher · un abonnement terminal est remplacé par son successeur · le webhook
enregistre `conflict` sans toucher l'état · aucune résiliation automatique · deux
appels identiques partagent la clé d'idempotence · un client Stripe unique
survit aux tentatives répétées · deux complétions concurrentes ne peuvent pas
persister toutes les deux.

## 27. Audit Stripe MCP — TEST et LIVE

Deux comptes exposés :

| Rôle | `stripe_context` | `livemode` |
|---|---|---|
| TEST | `acct_1TMqChC34k5bO7Y3` — « Environnement de test Turiya » | `false` |
| LIVE | `acct_1TMqCOFx3uZwOQKx` — « Turiya » | `true` |

**Constat central : le compte Stripe est partagé avec un autre projet
(« Turiya »).** Aucun objet Kivou n'existait, et aucun objet Turiya n'entre en
conflit avec le catalogue Kivou — mais la configuration *de compte* (portail,
webhooks, fiscalité) est commune aux deux projets. C'est le point qui demande
le plus d'attention avant le lancement.

### TEST — avant écriture

| Élément | Constat |
|---|---|
| Produits | 6, tous Turiya (`Pilotage Turiya`, `Audit Turiya — …`). **Aucun Kivou.** |
| Prix | 7, tous Turiya, **aucune clé de recherche**, aucun récurrent CHF/EUR à 4900 / 9900 / 19900 |
| Devises | CHF uniquement |
| Coupons | **aucun** |
| Codes promotionnels | **aucun** |
| Portail client | 1 configuration, `is_default: true`, **marquée Turiya** |
| Webhooks | 1, `https://turiya-audit.ch/api/webhooks/stripe`, 5 types Turiya |
| Clients | 1, Turiya (aucune métadonnée Kivou) |
| Abonnements | **aucun** (`status=all`) |
| Version de spec API | `2026-06-24.preview` (SDK Python : `2026-07-29.dahlia`) |
| Stripe Tax | `status: pending`, champ manquant `head_office`, **0 immatriculation** |
| Objets 49 / 99 / 199 / 29 en conflit | **aucun** |
| Limitation à un abonnement par client | **aucune configuration Stripe native** — l'invariant est tenu par Kivou (§26) |

**Conclusion de l'audit : aucun conflit.** Les écritures TEST de §7 et §8 ont
donc été autorisées.

### TEST — objets créés

Tous vérifiés `livemode = false` par relecture après création.

| Type | Identifiant | Clé de recherche | Détail |
|---|---|---|---|
| Product | `prod_V63PPw5P5jVpiB` | — | Kivou Essential — **créé** |
| Product | `prod_V63QnoKMxzCE3f` | — | Kivou Pro — **créé** |
| Product | `prod_V63QiyboWkoAOR` | — | Kivou Scale — **créé** |
| Price | `price_1U5rJQC34k5bO7Y3sdIrZ39g` | `kivou_essential_monthly_chf` | 4900 CHF / mois — **créé** |
| Price | `price_1U5rJaC34k5bO7Y37weno2Fg` | `kivou_essential_monthly_eur` | 4900 EUR / mois — **créé** |
| Price | `price_1U5rJjC34k5bO7Y3SKDNBzzC` | `kivou_pro_monthly_chf` | 9900 CHF / mois — **créé** |
| Price | `price_1U5rJrC34k5bO7Y3opxjnXNy` | `kivou_pro_monthly_eur` | 9900 EUR / mois — **créé** |
| Price | `price_1U5rK0C34k5bO7Y3sreBxBlH` | `kivou_scale_monthly_chf` | 19900 CHF / mois — **créé** |
| Price | `price_1U5rK8C34k5bO7Y3ml9qvl1V` | `kivou_scale_monthly_eur` | 19900 EUR / mois — **créé** |
| Coupon | `kivou_founding_12m` | — | remise fondateur — **créé** |

Chaque Produit porte `kivou_plan_code` en métadonnée — **pour l'inventaire, pas
pour l'autorisation** : le code ne lit jamais une métadonnée Stripe pour
accorder un droit (§9). Aucun objet n'a été dupliqué ; aucun objet Turiya n'a été
modifié.

### LIVE — audit de sûreté avant écriture

Le superviseur a ensuite confirmé que le compte est **ancien et inutilisé**, et
autorisé les écritures LIVE après audit. Le contrôle exigé — aucun abonnement
réel actif, aucune obligation financière — a porté sur sept collections :

| Collection LIVE | Constat |
|---|---|
| Abonnements (`status=all`) | **0** |
| Échéanciers d'abonnement | **0** |
| Factures | **0** |
| Paiements (`payment_intents`) | **0** |
| Encaissements (`charges`) | **0** |
| Clients | **0** |
| Produits / Prix / Coupons / Webhooks | **0** |

**Aucun abonnement réel actif. Aucune facture impayée. Aucune obligation
financière.** Le seul objet LIVE préexistant est la configuration de portail par
défaut, marquée Turiya. Les écritures LIVE ont donc été autorisées.

Côté TEST, une facture **acquittée** de 690 CHF (Turiya, `status: paid`,
`amount_remaining: 0`) existe. C'est un enregistrement financier historique :
elle n'a **pas** été touchée.

### LIVE — objets créés

Tous vérifiés `livemode = true` par relecture après création.

| Type | Identifiant | Clé de recherche | Détail | Action |
|---|---|---|---|---|
| Product | `prod_V647ZPVb4BA1kk` | — | Kivou Essential | **créé** |
| Product | `prod_V648LiyPzSWGWe` | — | Kivou Pro | **créé** |
| Product | `prod_V648lzV53XYNng` | — | Kivou Scale | **créé** |
| Price | `price_1U5s06Fx3uZwOQKx9cMweWYK` | `kivou_essential_monthly_chf` | 4900 CHF / mois | **créé** |
| Price | `price_1U5s0FFx3uZwOQKxBxG4yNea` | `kivou_essential_monthly_eur` | 4900 EUR / mois | **créé** |
| Price | `price_1U5s0OFx3uZwOQKxxy4BooFh` | `kivou_pro_monthly_chf` | 9900 CHF / mois | **créé** |
| Price | `price_1U5s0XFx3uZwOQKxmsxrcqBo` | `kivou_pro_monthly_eur` | 9900 EUR / mois | **créé** |
| Price | `price_1U5s0gFx3uZwOQKxRLsF2YvC` | `kivou_scale_monthly_chf` | 19900 CHF / mois | **créé** |
| Price | `price_1U5s1BFx3uZwOQKxiGmeInQD` | `kivou_scale_monthly_eur` | 19900 EUR / mois | **créé** |
| Coupon | `kivou_founding_12m` | — | 7000 CHF / 7000 EUR, repeating 12 mois, max 5, restreint à `prod_V648LiyPzSWGWe` | **créé** |

**Aucun objet LIVE n'a été archivé, désactivé, supprimé ni modifié** — il n'y en
avait aucun à reprendre. Aucun enregistrement financier n'a été touché.

### Ce qui n'a PAS été archivé, et pourquoi

Les six Produits et sept Prix Turiya du mode TEST subsistent, **actifs**. Les
archiver n'était pas nécessaire à Kivou : le code résout ses prix par **clé de
recherche**, et aucun objet Turiya n'en porte — ils ne peuvent donc pas
interférer. Agir sur les données d'un autre projet sans nécessité serait le
mauvais réflexe, et l'un d'eux est référencé par la facture acquittée ci-dessus.

## 28. Mécanisme de l'offre fondateur (R1 §8)

Le mécanisme a été **vérifié avant création** sur l'API du compte
(`PostCoupons`, spec `2026-06-24.preview`) : `duration: repeating` +
`duration_in_months`, `max_redemptions`, `applies_to.products` et
`currency_options` sont tous présents et documentés — **aucune mention de
dépréciation**. Le mécanisme retenu est donc bien le coupon répétitif.

Objet créé en TEST, relu pour vérification :

```
id                  kivou_founding_12m
amount_off          7000 (CHF)
currency_options    chf 7000 · eur 7000
duration            repeating, duration_in_months = 12
max_redemptions     5
applies_to          prod_V63QnoKMxzCE3f  (Kivou Pro uniquement)
livemode            false
times_redeemed      0
```

Résultat commercial inchangé : **99 − 70 = 29**, dans les deux devises, sur
12 mois, puis le prix Pro normal reprend.

**Kivou continue de plafonner lui-même à 5 comptes distincts** :
`max_redemptions` compte des utilisations de coupon, pas des clients.

## 29. Portail client (R1 §9) — écriture impossible par MCP

La configuration TEST **existante** satisfait déjà exactement la cible :

| Attendu | Configuration `bpc_1TR9skC34k5bO7Y3mS1FxOh7` |
|---|---|
| gestion du moyen de paiement | **activée** ✓ |
| historique des factures | **activé** ✓ |
| résiliation | **activée**, `mode: at_period_end`, `proration_behavior: none` ✓ |
| changement de plan | **désactivé** ✓ |

La résiliation préserve donc bien la période déjà payée, sans coupure inventée
côté Kivou — exactement ce que R1 §9 demande.

**Deux réserves, dont une reste ouverte après l'autorisation d'écriture :**

1. **Le MCP n'expose aucune opération d'écriture sur les configurations de
   portail** — ni en TEST, ni en LIVE. Recherché explicitement après
   l'autorisation : seuls `GetBillingPortalConfigurations` et
   `GetBillingPortalConfigurationsConfiguration` existent. C'est une limite de
   l'**outil**, pas d'autorisation : même avec les droits d'écriture accordés,
   la configuration ne peut pas être posée par cette voie. Elle doit l'être
   depuis le tableau de bord Stripe.
2. **Les deux configurations, TEST et LIVE, sont marquées Turiya** : titre
   « Gérer votre abonnement Pilotage Turiya », CGU et URL de retour
   `turiya-audit.ch`, `is_default: true`. Un client Kivou y verrait la marque
   d'un autre projet.

Kivou passe déjà un `return_url` explicite, qui l'emporte sur le
`default_return_url` de Turiya. Et
`STRIPE_PORTAL_CONFIGURATION_ID` a été ajouté à la configuration : le jour où
une configuration Kivou existera, elle s'appliquera **sans changer une ligne de
code**.

## 30. Destination de webhook (R1 §10)

**Non créée.** Aucune URL Kivou de test ou de préproduction n'existe, et §10
interdit d'en inventer une. L'unique destination TEST du compte pointe vers
Turiya et n'a pas été touchée.

```
TEST webhook destination pending staging URL
```

L'implémentation backend reste vérifiée hors-ligne : les tests calculent une
signature Stripe authentique et exercent le vrai code de vérification.

**Point de sécurité à traiter avant les premiers paiements de test.** La
destination TEST existante (`we_1TPGpwC34k5bO7Y37W1YR4bp`,
`https://turiya-audit.ch/api/webhooks/stripe`) écoute exactement les événements
de Kivou :

```
checkout.session.completed        customer.subscription.created
customer.subscription.updated     customer.subscription.deleted
invoice.payment_failed
```

Le compte Stripe étant unique, **les événements de facturation Kivou en mode
TEST seraient livrés au serveur de Turiya** dès le premier checkout. Ce n'est
pas un problème d'accès Kivou — la signature protège l'entrée, pas la sortie —
mais une fuite d'événements vers un domaine tiers.

Le MCP n'expose **aucune opération d'écriture sur les destinations
d'événements** : cette destination doit être désactivée depuis le tableau de
bord. Elle n'a pas été touchée.

## 31. Stripe Tax (R1 §11) — audit seul

| | TEST | LIVE |
|---|---|---|
| Statut | `pending` (`head_office` manquant) | **`active`** |
| Siège | — | CH / Sion |
| Immatriculations | **0** | **0** |
| Comportement fiscal des prix Kivou | `unspecified` | — |
| Défauts du compte | `tax_behavior: null` | `inferred_by_currency`, `txcd_10000000` |

**Le point qui compte : Stripe Tax est `active` en LIVE sans aucune
immatriculation fiscale.** Activer `automatic_tax` dans cet état ne calculerait
aucune taxe là où il en faudrait peut-être, et donnerait l'illusion d'une
conformité. C'est une décision fiscale et juridique, pas un réglage.

Rien n'a été activé ni modifié, en TEST comme en LIVE. L'exécution reste
`automatic_tax = false`, et le checkout collecte déjà l'adresse de facturation
et le numéro fiscal pour le jour où la décision sera prise.

---

# Closeout final — verrou avant Stripe Checkout

## 32. Le défaut fermé

Deux requêtes de paiement quasi simultanées pour un même compte passaient toutes
deux le contrôle « ce compte a-t-il déjà un abonnement ? » — puisqu'aucun
n'existe encore — et ouvraient **deux sessions Stripe**. Un client qui terminait
les deux se retrouvait avec deux abonnements, donc deux factures.

La contrainte d'unicité de R1 rattrapait bien la seconde en conflit — mais
**après le débit**. Un conflit qui se déclenche une fois l'argent prélevé
documente le problème, il ne l'évite pas.

La correction inverse l'ordre des opérations, et c'est l'ordre lui-même qui est
la garantie.

## 33. `billing_checkout_attempt`

```text
account_id                  String(64)   FK account CASCADE   PRIMARY KEY
attempt_id                  String(64)   NOT NULL             UNIQUE
plan_code                   String(32)   NOT NULL
currency                    String(3)    NOT NULL
stripe_checkout_session_id  String(255)  nullable             UNIQUE
status                      String(16)   NOT NULL             INDEX
expires_at                  DateTime(tz) NOT NULL
created_at                  DateTime(tz) NOT NULL
updated_at                  DateTime(tz) NOT NULL
```

`account_id` est la **clé primaire** : la base garantit qu'un compte n'a qu'une
tentative courante, quel que soit le nombre de processus applicatifs. Un verrou
en mémoire ne tiendrait pas sur un second worker.

Statuts : `creating` → `open` → `completed` | `expired` | `failed`. Les trois
derniers sont **terminaux** et libèrent la place. La table ne garde **aucun
historique** : une tentative terminée est remplacée par la suivante.

Migration `0003_billing` régénérée (toujours non committée) : cinq
`create_table`, six `create_index`, aucun `drop`, aucun `alter`.

## 34. Algorithme de réservation atomique

```text
requête authentifiée
    ↓
marquer `expired` une tentative dont l'heure est passée
    ↓
l'abonnement courant est-il ouvert ?  → oui : 409 already_subscribed, STOP
    ↓ non
réserver la tentative  (INSERT, ou UPDATE d'une tentative terminale)
    ↓
COMMIT                        ← la réservation est validée AVANT Stripe
    ↓
appeler Stripe Checkout       ← hors transaction
    ↓
COMMIT   enregistrer la session, statut = open
```

La réservation traite trois cas, et un seul ouvre la porte :

| Situation | Résultat |
|---|---|
| aucune tentative, ou tentative terminée / expirée | **réservation** |
| tentative `creating` sur le **même** plan et la même devise | **reprise** de la même tentative (§4) |
| tout le reste | `checkout_in_progress` |

**§9 — la base est l'arbitre.** L'insertion *est* l'arbitrage : deux requêtes
concurrentes ne peuvent pas insérer la même clé primaire, et la perdante lève
`CheckoutInProgress` sans jamais atteindre Stripe. Le remplacement d'une
tentative terminale porte l'`attempt_id` observé dans son `WHERE`, pour qu'une
réservation concurrente déjà passée ne soit pas écrasée.

Un test lit le source : `prepare_checkout` ne contient aucun
`create_checkout_session`, et `open_checkout_session` en contient un. L'appel
réseau ne peut donc pas se retrouver à l'intérieur de la transaction de
réservation — où un échec annulerait précisément la protection.

## 35. Cycle de vie de la clé d'idempotence

```text
kivou-checkout:<attempt_id>
```

`attempt_id` est persisté **avant** le premier appel Stripe, et n'est jamais
régénéré tant que la tentative n'est pas terminale. Une reprise rejoue donc
exactement la même clé.

C'est la différence avec R1, où la clé dérivait de `(compte, plan, devise,
offre)` : cette forme ne survivait pas à un changement de plan et ne distinguait
pas deux tentatives successives. Deux tests le verrouillent : la clé envoyée à
Stripe vaut bien `kivou-checkout:<attempt_id>`, et deux réservations successives
sur une tentative en cours rendent le même identifiant.

## 36. Reprise après plantage du processus

Scénario couvert (§10 B) : la tentative est persistée, Stripe crée la session,
**le processus meurt avant d'enregistrer l'identifiant de session**.

Le test le reproduit littéralement — la passerelle crée la session puis lève.
État observé : tentative `creating`, `stripe_checkout_session_id` à `None`. À la
reprise :

- la même tentative est **rejouée** (même `attempt_id`) ;
- donc la même clé d'idempotence ;
- Stripe rend **la même session** ;
- Kivou l'enregistre, statut `open`.

Résultat : **une seule tentative en base, une seule session Stripe**, une seule
clé d'idempotence sur l'ensemble des appels.

Un test complémentaire vérifie qu'une reprise **sur un autre plan** ne rejoue
pas la tentative — rejouer une clé d'idempotence avec d'autres paramètres serait
une erreur Stripe — et rend `checkout_in_progress`.

## 37. Expiration et `checkout.session.expired`

Durée de vie : **30 minutes**, la même localement et chez Stripe. La session est
créée avec `expires_at`, et la tentative locale porte la même échéance : sans
cela, une tentative locale pourrait survivre à la session qu'elle décrit et
bloquer le compte pour rien.

- Une tentative périmée est marquée `expired` **avant** tout contrôle, à chaque
  demande de paiement : un abandon ne bloque pas un compte indéfiniment.
- `checkout.session.expired` a été ajouté au jeu d'événements traités. Il ferme
  la tentative correspondante et **rend `ignored`** : une session expirée ne
  porte aucun abonnement, il n'y a rien à synchroniser et aucun droit à
  accorder.
- `checkout.session.completed` ferme la tentative en `completed`, **sans rien
  accorder** : la synchronisation de l'abonnement reste seule autorité, et la
  redirection de succès reste de la présentation.

Trois tests le vérifient de bout en bout, dont un qui confirme qu'après
l'événement d'expiration le compte peut relancer un paiement, éventuellement sur
un autre plan.

## 38. Concurrence — résultat des tests

| Cas (§10) | Résultat |
|---|---|
| **A** deux requêtes quasi simultanées | 200 + 409, **une** tentative, **un** appel Stripe |
| **B** reprise après plantage | même `attempt_id`, même clé, même session, une tentative |
| **C** autre plan pendant un paiement ouvert | 409 `checkout_in_progress`, aucun appel Stripe, tentative intacte |
| **D** expiration | tentative `expired`, aucun accès payant, nouveau paiement autorisé |
| **E** complétion | tentative `completed`, **aucun droit** accordé pour autant |
| **F** abonnement existant (6 statuts) | aucune tentative, aucun appel Stripe |
| **G** statut Stripe inconnu | échec fermé : aucune tentative, aucun appel |
| **H** double insertion directe | `IntegrityError` de la base |

Le perdant d'une course **n'atteint jamais Stripe** — testé en vidant le journal
d'appels de la passerelle avant la seconde requête. Deux comptes distincts
réservent chacun leur tentative sans se gêner.

### Un test R1 durci

`test_two_identical_checkout_calls_are_one_logical_operation` attendait deux
réponses `200` partageant une clé d'idempotence. La seconde requête ne rappelle
désormais plus Stripe du tout : elle se heurte à la tentative réservée et rend
**409 `checkout_in_progress`**. La propriété qui compte — une seule session de
paiement — est renforcée, pas affaiblie ; le test l'exprime maintenant ainsi.

## 39. État Stripe — inchangé

**Aucune écriture Stripe pendant ce closeout, ni en TEST ni en LIVE.** Vérifié
par relecture :

| | Constat |
|---|---|
| Produits Kivou LIVE | 3, `updated` identique à `created` — **non modifiés** |
| Produits Kivou TEST | 3, **non modifiés** |
| Prix, coupon fondateur | **non modifiés**, aucun doublon créé |
| Produits Turiya TEST | 6, horodatages `updated` identiques à ceux du premier audit — **intacts** |
| Facture Turiya acquittée | **intacte** |
| Écritures LIVE supplémentaires | **0** |

## 40. Portes de qualité finales

| Porte | Résultat |
|---|---|
| `uv run pytest -q` | **2602 passed**, 0 échec, **0 ignoré** |
| `uv run ruff check .` | **All checks passed!** |
| `git diff --check` | propre |

Répartition SPEC-013 (**222 tests**) :

| Fichier | Tests |
|---|---|
| `tests/test_billing_entitlements.py` | 38 |
| `tests/test_billing_catalogue.py` | 37 |
| `tests/test_billing_checkout.py` | 36 |
| `tests/test_billing_checkout_lock.py` | **29** |
| `tests/test_billing_paywall.py` | 29 |
| `tests/test_billing_single_subscription.py` | 27 |
| `tests/test_billing_webhooks.py` | 20 |
| `tests/test_billing_secrets.py` | 6 |

Base SPEC-012 : 2380.

### `git status --porcelain`

```
 M pyproject.toml
 M src/signals/api/app.py
 M src/signals/api/config.py
 M src/signals/api/errors.py
 M src/signals/api/routes_billing.py
 M src/signals/api/routes_signals.py
 M src/signals/feed/query.py
 M src/signals/persistence/migrations/env.py
 M tests/test_accounts_migration_and_ownership.py
 M tests/test_feed_event_copy.py
 M tests/test_feed_facts.py
 M tests/test_feed_identity.py
 M tests/test_feed_ownership.py
 M tests/test_feed_recency.py
 M uv.lock
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx
?? Plan_directeur_Award_Sales_Signals_CH_UE_v2.docx:Zone.Identifier
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx
?? Roadmap_execution_MVP_Marketing_Award_Sales_Signals_v2.docx:Zone.Identifier
?? docs/reports/2026-08-17-spec006-postmortem.md
?? docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md
?? docs/reports/2026-08-18-spec013-stripe-billing-paywall.md
?? src/signals/api/routes_billing.py
?? src/signals/api/routes_webhooks.py
?? src/signals/billing/
?? src/signals/persistence/migrations/versions/0003_billing_billing.py
?? src/signals/research/spec009c.py
?? src/signals/research/spec009c_run.py
?? tests/billing_helpers.py
?? tests/fixtures/documents/heldout3_gold.json:Zone.Identifier
?? tests/fixtures/documents/heldout3_gold.sha256.txt:Zone.Identifier
?? tests/fixtures/signal100/spec009c_blind.json
?? tests/test_billing_catalogue.py
?? tests/test_billing_checkout.py
?? tests/test_billing_checkout_lock.py
?? tests/test_billing_entitlements.py
?? tests/test_billing_paywall.py
?? tests/test_billing_secrets.py
?? tests/test_billing_single_subscription.py
?? tests/test_billing_webhooks.py
?? tests/test_spec009c_bench.py
```

Note : `src/signals/api/routes_billing.py` apparaît en modifié parce qu'il a été
créé puis retouché dans la même session non committée ; il fait partie des
fichiers **nouveaux** du commit.

### Fichiers du commit SPEC-013 envisagé

**Modifiés (14)** — fichiers déjà suivis par git :

```
pyproject.toml
uv.lock
src/signals/api/app.py
src/signals/api/config.py
src/signals/api/errors.py
src/signals/api/routes_signals.py
src/signals/feed/query.py
src/signals/persistence/migrations/env.py
tests/test_accounts_migration_and_ownership.py
tests/test_feed_event_copy.py
tests/test_feed_facts.py
tests/test_feed_identity.py
tests/test_feed_ownership.py
tests/test_feed_recency.py
```

**Nouveaux (23)**

```
src/signals/api/routes_billing.py
src/signals/api/routes_webhooks.py
src/signals/billing/__init__.py
src/signals/billing/access.py
src/signals/billing/attempts.py
src/signals/billing/catalogue.py
src/signals/billing/checkout.py
src/signals/billing/discovery.py
src/signals/billing/gateway.py
src/signals/billing/paywall.py
src/signals/billing/schema.py
src/signals/billing/service.py
src/signals/billing/webhooks.py
src/signals/persistence/migrations/versions/0003_billing_billing.py
tests/billing_helpers.py
tests/test_billing_catalogue.py
tests/test_billing_checkout.py
tests/test_billing_checkout_lock.py
tests/test_billing_entitlements.py
tests/test_billing_paywall.py
tests/test_billing_secrets.py
tests/test_billing_single_subscription.py
tests/test_billing_webhooks.py
docs/reports/2026-08-18-spec013-stripe-billing-paywall.md
```

**Explicitement exclus** — hors périmètre : `*.docx`, `*:Zone.Identifier`,
`docs/reports/2026-08-17-spec006-postmortem.md`,
`docs/reports/2026-08-18-spec009c-fresh-wedge-benchmark.md`,
`src/signals/research/spec009c*.py`,
`tests/fixtures/signal100/spec009c_blind.json`, `tests/test_spec009c_bench.py`.

## 41. Portes d'exploitation — avant le premier paiement réel

Aucune n'est un bloquant de commit ; toutes sont hors de portée du MCP, qui
n'expose pas ces écritures.

> **AVANT LE PREMIER CHECKOUT KIVOU EN MODE TEST :
> DÉSACTIVER OU ISOLER LE WEBHOOK TEST DE TURIYA DANS LE TABLEAU DE BORD STRIPE.**
>
> `we_1TPGpwC34k5bO7Y37W1YR4bp` → `https://turiya-audit.ch/api/webhooks/stripe`
> écoute `checkout.session.completed`, `customer.subscription.*` et
> `invoice.payment_failed` : les événements de facturation Kivou lui seraient
> livrés.

1. **Webhook TEST de Turiya** — ci-dessus.
2. **Portail client**, TEST et LIVE : les deux configurations portent la marque
   Turiya. `STRIPE_PORTAL_CONFIGURATION_ID` est en place pour qu'une
   configuration Kivou s'applique sans changement de code.
3. **Stripe Tax `active` en LIVE avec zéro immatriculation** — décision fiscale
   et juridique. L'exécution reste `automatic_tax = false`.
4. **Destination d'événements LIVE de Kivou** — à créer le jour où une URL
   publique existe.
5. **Limitation de débit** sur les points d'entrée d'authentification
   (SPEC-011 §15.6) et sur `/webhooks/stripe`.

## 42. Ce que SPEC-013 impose à la suite

1. **La facturation reste la dernière condition** : `propriété → identité →
   politique de signal → droit`.
2. **Un compte, un abonnement** — contrainte en base.
3. **Un compte, une tentative de paiement** — contrainte en base également, et
   **on réserve avant d'appeler Stripe**. Tout nouveau chemin de paiement doit
   passer par `prepare_checkout` puis `open_checkout_session`, dans cet ordre.
4. **La clé d'idempotence appartient à la tentative persistée.** En dériver une
   nouvelle à chaque appel recréerait le défaut que ce closeout ferme.
5. **Accès ≠ existence**, et le défaut est fermé : un statut Stripe inconnu
   bloque.
6. **Terminer un paiement n'est pas être abonné.** Ni la redirection de succès,
   ni `checkout.session.completed` n'accordent quoi que ce soit.
7. **Aucun droit ne se lit dans une métadonnée Stripe.**
8. **Un conflit de facturation se signale, il ne se résout pas tout seul**, et
   aucun abonnement Stripe n'est jamais résilié par le code.
9. **Le compte Stripe est partagé avec un autre projet.** Toute écriture de
   configuration de compte doit vérifier qu'elle ne dégrade pas Turiya.
10. **Interdits toujours en vigueur** : frontend, retour d'expérience, alertes,
    exports, recherche automatique d'entreprise, et toute acquisition.

---

## Verdict

**SPEC-013 READY TO COMMIT**

Deux sessions de paiement ne peuvent plus produire deux abonnements Stripe pour
un même compte. La tentative est **réservée en base et validée avant** tout
appel à Stripe, la clé d'idempotence appartient à cette tentative persistée —
donc une reprise après plantage rejoue la même session au lieu d'en créer une
seconde — et la clé primaire `account_id` fait de la base l'arbitre entre
processus, ce qu'un verrou en mémoire ne saurait être. Une tentative expire en
trente minutes, localement et chez Stripe, et ne bloque donc jamais un compte
au-delà de sa propre durée de vie.

Le catalogue Stripe Kivou est inchangé en TEST comme en LIVE, les données
Turiya sont intactes, et **les écritures LIVE supplémentaires sont nulles**.

2602 tests, dont 222 pour SPEC-013. Non committé, conformément à §17.
