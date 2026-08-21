# P0-03 — EVAL visuelle

Dix-neuf vues du parcours de conversion payante et de récupération.

| | |
|---|---|
| Branche | `feat/p0-03-paid-conversion` |
| SHA des captures | `6b819b125cf1511c4176764f5ad4736eed408528` |
| Base | `c0f1595db89508c90cc7348e939d299b88d45b44` |
| Environnement | build de production local (`npm run build`), servi sur **une seule origine** |
| Navigateur | Chromium 151 (Playwright), `deviceScaleFactor: 1`, captures pleine page |

## Le contenu est vérifié, pas seulement la géométrie

La campagne P0-02 a montré qu'une capture parfaitement mesurée pouvait être
celle de la **mauvaise page** : débordement, coupure et nombre de `h1` étaient
tous corrects sur un écran qui n'était pas le bon.

Chaque scénario asserte donc, **avant** la photo :

- le `h1` attendu ;
- le texte d'état attendu ;
- le CTA attendu ;
- l'**absence** des CTA interdits.

Une assertion ratée fait échouer la campagne. Elle en a déjà attrapé une : la
vue « détail verrouillé » rendait un détail **ouvert**, parce que le serveur de
fixtures servait le même objet pour toute clé. Aucune mesure géométrique
n'aurait vu ce défaut.

## Ce que ces vues prouvent, et ce qu'elles ne prouvent pas

Le **frontend est le vrai** : le bundle de `frontend/dist` produit sur ce SHA,
servi sur la même origine que l'API — la condition de production.

Les **réponses de l'API sont des fixtures**, calquées sur les charges utiles
réelles. C'est la seule façon d'obtenir à la demande un compte `past_due`, un
`trialing`, une tentative expirée ou un délai de sondage dépassé. **Aucun
paiement Stripe n'a lieu dans cette campagne** — le gate transactionnel réel
(staging → Stripe TEST → webhook) reste à faire et n'est pas couvert ici.

Les fichiers vivent sous `docs/` : pièces de revue, hors `frontend/src`, hors
`frontend/public`, hors bundle.

## Vues

Légende : **DH** = débordement horizontal, **CT** = coupure de texte. Toutes
les vues : DH non, CT non, `h1` = 1.

### Paywall — les deux entrées

| Vue | Fichier | Dim. | Lang. | État | `h1` | CTA attendu | Interdits vérifiés |
|---|---|---|---|---|---|---|---|
| Feed verrouillé | `paywall-feed-verrouille-fr-1440x900.png` | 1440×900 | FR | teaser `locked` | Signaux récents | Déverrouiller Kivou | nom du gagnant absent |
| Billing atteint depuis le teaser | `paywall-vers-billing-fr-1440x900.png` | 1440×900 | FR | `choose_plan` | Facturation | Choisir Pro | portail, récupération |
| Détail verrouillé | `paywall-detail-verrouille-fr-1440x900.png` | 1440×900 | FR | détail `locked` | Un marché public vient d'être attribué. | Voir les offres | gagnant, source |

Seule la **clé** du signal traverse le paywall, dans l'état de navigation. Ni
entreprise, ni montant, ni besoin, ni preuve.

### `choose_plan` — la seule action qui autorise un paiement

| Vue | Fichier | Dim. | Lang. | État | CTA | Interdits |
|---|---|---|---|---|---|---|
| Grille | `billing-choose-plan-fr-1440x900.png` | 1440×900 | FR | Découverte, aucun abonnement | Choisir Pro | portail, export, filtres, territoires |
| Grille | `billing-choose-plan-fr-390x844.png` | 390×844 | FR | idem | Choisir Pro | idem |
| Grille | `billing-choose-plan-fr-320x800.png` | 320×800 | FR | reflow limite | Choisir Pro | idem |
| Devise CHF | `billing-devise-chf-fr-1440x900.png` | 1440×900 | FR | prix serveur | Choisir Pro | — |
| Devise EUR | `billing-devise-eur-fr-1440x900.png` | 1440×900 | FR | prix serveur | Choisir Pro | — |

Les prix viennent exclusivement de `GET /billing/plans`. Aucune carte ne
mentionne export, filtres ni territoires — capacités retirées de la copy parce
qu'elles ne sont pas exerçables.

### Les trois autres actions

| Vue | Fichier | Dim. | Lang. | État | CTA | Interdits vérifiés |
|---|---|---|---|---|---|---|
| Récupération | `billing-recover-payment-fr-1440x900.png` | 1440×900 | FR | `past_due`, accès suspendu | Ouvrir le portail de facturation | **Choisir Pro**, Devise |
| Récupération | `billing-recover-payment-fr-320x800.png` | 320×800 | FR | reflow limite | idem | idem |
| Récupération | `billing-recover-payment-en-1440x900.png` | 1440×900 | EN | `past_due` | Open the billing portal | Choose Pro, Advanced filters |
| Vérification | `billing-contact-support-fr-1440x900.png` | 1440×900 | FR | `trialing` | contact@kivou.eu | Choisir, portail, `cus_`, `lookup` |
| Gestion | `billing-manage-pro-fr-1440x900.png` | 1440×900 | FR | Pro actif | Gérer ma facturation | **Choisir Pro**, Devise |
| Résiliation programmée | `billing-cancel-at-period-end-fr-1440x900.png` | 1440×900 | FR | Pro, fin de période | Gérer ma facturation | Choisir Pro |

Sur la vue de récupération, l'écran affiche simultanément **« Découverte »**
(les droits actuels) et **« Paiement en retard »** (le statut) — les deux sont
vrais, et c'est `billing_action` qui décide de l'action, pas eux.

### Retour de paiement

| Vue | Fichier | Dim. | Lang. | État | `h1` | CTA | Interdits |
|---|---|---|---|---|---|---|---|
| Vérification | `checkout-verification-fr-1440x900.png` | 1440×900 | FR | serveur encore Découverte | Vérification de votre accès | — | **Accès payant actif** |
| Délai dépassé | `checkout-timeout-fr-1440x900.png` | 1440×900 | FR | 45 s sans confirmation | Vérification de votre accès | Réessayer la vérification | Accès payant actif |
| Accès actif | `checkout-acces-actif-fr-1440x900.png` | 1440×900 | FR | plan payant confirmé | Accès payant actif | Accéder à mes signaux | **Paiement confirmé**, Revenir à ce signal |
| Retour au signal | `checkout-retour-au-signal-fr-1440x900.png` | 1440×900 | FR | intention mémorisée | Accès payant actif | Revenir à ce signal + Voir tous mes signaux | nom du gagnant |
| Annulation | `checkout-annulation-fr-1440x900.png` | 1440×900 | FR | paiement interrompu | Paiement interrompu | Revenir aux offres | échec, refusé |

La vue « délai dépassé » est obtenue par une attente **réelle** de 48 secondes,
sans horloge simulée : c'est le comportement du sondage borné qui est photographié.

La vue « retour au signal » suit le parcours complet — teaser verrouillé →
facturation → paiement ouvert → retour — parce que c'est le seul chemin qui
écrit réellement l'intention.

## Mesures

```text
19 vues, toutes vérifiées en contenu ET en géométrie

débordement horizontal .................... 0 / 19
coupure de texte .......................... 0 / 19
titres h1 par vue ......................... 1 / 1 partout
assertions de contenu ..................... 19 / 19 satisfaites
CTA interdits détectés .................... 0
```

Le contrôle de coupure ignore les libellés `.kivou-visually-hidden`, rognés par
conception, et les éléments en `overflow: visible`, où rien ne peut être rogné.

## Accessibilité relevée

- un seul `h1` par écran ;
- les quatre états de facturation portent un titre de callout explicite, jamais
  la seule couleur ;
- le passage « vérification » → « accès actif » est annoncé par `aria-live` ;
- le bouton de réessai est focusable et n'est actif qu'une fois le délai atteint ;
- le contact support est un lien `mailto:`, pas un bouton — ce qui navigue est
  un `a` ;
- reflow vérifié à 320 px sur les deux écrans les plus denses.
