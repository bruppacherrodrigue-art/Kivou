# P0-03 — EVAL visuelle

Vingt vues du parcours de conversion payante et de récupération.

| | |
|---|---|
| Branche | `feat/p0-03-paid-conversion` |
| SHA des captures | `576a26d16779e455bb1e8477bca698e1d4cd97d7` |
| Base | `f7ee297` (`origin/main` après synchronisation) |
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

Une assertion ratée fait échouer la campagne. Elle a servi trois fois.

**1 — la vue « détail verrouillé » rendait un détail OUVERT**, parce que le
serveur de fixtures servait le même objet pour toute clé.

**2 — `cancelAtEnd` fuyait d'un scénario à l'autre.** La vue « résiliation
programmée » le laissait à 1, et la vue `recover_payment` suivante affichait
donc « Cancellation scheduled at the end of the current period » sur un compte
`past_due` dont l'accès était **suspendu** — deux affirmations contradictoires
dans une capture destinée à faire foi devant la supervision. Le défaut a
révélé un vrai défaut produit : la notice de résiliation n'était gatée sur
aucune action. Elle l'est maintenant sur `manage_subscription`.

**3 — `statusReads` vivait hors de l'état réinitialisé.** Ce compteur pilote la
bascule de sondage ; laissé à sa valeur, il aurait fait confirmer un accès dès
la première lecture de la vue suivante.

Aucune mesure géométrique n'aurait vu l'un de ces trois défauts.

## Isolation des scénarios

Les knobs mutables vivent dans un objet `DEFAULTS` unique. Chaque appel à
`__scenario` fait un **reset complet** — `Object.assign(state, DEFAULTS)` plus
`statusReads = 0` — **avant** d'appliquer les overrides. Aucun état du scénario
précédent ne survit.

Un contrôle automatisé tourne **avant toute capture** et interrompt la
campagne s'il échoue. Il salit délibérément les knobs, puis lance un scénario
qui n'en mentionne aucun, et vérifie la remise à zéro de :

```text
cancelAtEnd · currentPeriodEnd · plan · billing_action · locale · statusReads
```

Sortie de la campagne :

```text
isolation des scénarios : ok (cancelAtEnd, currentPeriodEnd, plan, locale, statusReads)
```

Les contradictions d'état de facturation sont désormais **assertées**, pas
relues à l'œil : « Résiliation programmée » et « Prochain renouvellement »
figurent dans la liste des interdits de toutes les vues `choose_plan`,
`recover_payment` et `contact_support`, en FR comme en EN.

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
| Feed verrouillé | `paywall-feed-verrouille-fr-1440x900.png` | 1440×900 | FR | teaser `locked` | Signaux récents | Gérer mon accès | nom du gagnant, « réservés aux offres payantes » |
| Billing atteint depuis le teaser | `paywall-vers-billing-fr-1440x900.png` | 1440×900 | FR | `choose_plan` | Facturation | Choisir Pro | portail, récupération |
| Détail verrouillé | `paywall-detail-verrouille-fr-1440x900.png` | 1440×900 | FR | détail `locked` | Un marché public vient d'être attribué. | Gérer mon accès | gagnant, source, « offres payantes », « Comparez les offres » |

Seule la **clé** du signal traverse le paywall, dans l'état de navigation. Ni
entreprise, ni montant, ni besoin, ni preuve.

**Copy vraie pour TOUS les plans.** Le teaser disait « réservés aux offres
payantes » — faux dès qu'un compte payant rencontre un signal verrouillé par la
fenêtre d'historique de son plan, ce qui est un cas normal. Il lisait alors
qu'il devait acheter ce qu'il paie déjà. La copy est désormais neutre — « Ces
informations ne sont pas incluses dans votre accès actuel. » — et le CTA
universel, « Gérer mon accès », parce que `/app/billing` peut légitimement
n'ouvrir qu'un portail et aucune grille.

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
| Statut inconnu | `billing-statut-inconnu-fr-1440x900.png` | 1440×900 | FR | statut hors dictionnaire | contact@kivou.eu | Choisir, portail, **la chaîne Stripe brute** |
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
| Retour depuis le paiement | `checkout-annulation-fr-1440x900.png` | 1440×900 | FR | retour, état inconnu | Retour depuis le parcours de paiement | Voir ma facturation | échec, refusé, « débité », « n'a pas changé » |

La vue « délai dépassé » est obtenue par une attente **réelle** de 48 secondes,
sans horloge simulée : c'est le comportement du sondage borné qui est photographié.

La vue « retour au signal » suit le parcours complet — teaser verrouillé →
facturation → paiement ouvert → retour — parce que c'est le seul chemin qui
écrit réellement l'intention.

**La page de retour ne sait presque rien, et sa copy s'arrête là.** C'est une
URL que n'importe qui peut ouvrir, y compris un client payant depuis des mois.
Elle ne reçoit rien de Stripe et n'interroge rien : elle ne pouvait donc
affirmer ni qu'un paiement avait été interrompu, ni qu'aucun débit n'avait eu
lieu, ni que l'offre n'avait pas changé — trois assertions qu'elle portait.
Elle dit maintenant ce qu'elle sait, et renvoie à la facturation, seule surface
qui interroge réellement l'état de l'abonnement.

## Mesures

```text
20 vues, toutes vérifiées en contenu ET en géométrie

isolation des scénarios ................... ok (contrôle automatisé)
débordement horizontal .................... 0 / 20
coupure de texte .......................... 0 / 20
titres h1 par vue ......................... 1 / 1 partout
assertions de contenu ..................... 20 / 20 satisfaites
CTA interdits détectés .................... 0
contradictions d'état de facturation ...... 0
```

Le contrôle de coupure ignore les libellés `.kivou-visually-hidden`, rognés par
conception, et les éléments en `overflow: visible`, où rien ne peut être rogné.

## Accessibilité relevée

- un seul `h1` par écran ;
- les quatre états de facturation portent un titre de callout explicite, jamais
  la seule couleur ;
- une **région live persistante** (`role="status" aria-live="polite"`) porte le
  texte d'état ; elle n'est jamais démontée, y compris au passage
  « vérification » → « accès actif », car un lecteur d'écran n'annonce pas le
  contenu d'une région qui vient de naître ;
- le bouton de réessai est focusable et n'est actif qu'une fois le délai atteint ;
- le contact support est un lien `mailto:`, pas un bouton — ce qui navigue est
  un `a` ;
- reflow vérifié à 320 px sur les deux écrans les plus denses.
