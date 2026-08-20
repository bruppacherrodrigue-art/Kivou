# P0-02 — EVAL visuelle

Vingt-trois vues de contrôle du parcours d'activation première valeur.

| | |
|---|---|
| Branche | `feat/p0-02-first-value-activation` |
| SHA des captures | `e32f4498a02180ed5fa109c7ceff874b9d0ef218` |
| Base | `25bc0ab22bd70819cbd71003c6222bd9ddedec87` |
| Environnement | build de production local (`npm run build`), servi sur **une seule origine** |
| Navigateur | Chromium 151 (Playwright), `deviceScaleFactor: 1`, captures pleine page |

## Ce que ces vues montrent, et ce qu'elles ne prouvent pas

Le **frontend est le vrai** : c'est le bundle de `frontend/dist`, celui que
`npm run build` produit sur ce SHA, servi sur la même origine que l'API — la
condition de production.

Les **réponses de l'API sont des fixtures**, calquées champ pour champ sur les
charges utiles réelles (`MeResponse`, `TargetIcp`, `FeedPage`, `BillingStatus`,
`SignalDetail`). Ce choix est délibéré et il est la seule façon d'obtenir ces
vues : montrer 0, 1 et 3 déblocages exige de contrôler ce que le serveur
attribue, et une base réelle ne le permet pas à la demande. La même remarque
vaut pour la vue de succès partiel, qui suppose un `GET /me` en échec juste
après un `POST /target-icps` réussi.

Ces captures valident donc la **composition, la copy, la hiérarchie et le
reflow**. Elles ne valident pas l'intégration serveur — c'est le rôle de la
validation staging.

Elles vivent sous `docs/` et non dans `frontend/src/` ou `frontend/public/` :
ce sont des pièces de revue, elles n'entrent ni dans les assets de production
ni dans le bundle.

## Vues

Légende : **DH** = débordement horizontal, **CT** = coupure de texte.

### Inscription

| Vue | Fichier | Dim. | Langue | État | DH | CT | h1 |
|---|---|---|---|---|---|---|---|
| Inscription | `signup-fr-1440x900.png` | 1440×900 | FR | compte à créer, jalon 1 actif | non | non | 1 |
| Inscription | `signup-fr-390x844.png` | 390×844 | FR | idem, colonne unique | non | non | 1 |
| Inscription | `signup-fr-320x800.png` | 320×800 | FR | reflow limite | non | non | 1 |
| Inscription | `signup-en-390x844.png` | 390×844 | EN | traduction fidèle | non | non | 1 |

Les deux phrases ajoutées — la suite du parcours, l'absence de carte bancaire —
suivent le bouton d'envoi. Le payload reste `email`, `password`,
`company_name`, `locale`.

### Onboarding

| Vue | Fichier | Dim. | Langue | État | DH | CT | h1 |
|---|---|---|---|---|---|---|---|
| Validation progressive | `onboarding-validation-fr-1440x900.png` | 1440×900 | FR | Suivant pressé sans réponse | non | non | 1 |
| A — ce que vous vendez | `onboarding-1-offre-fr-1440x900.png` | 1440×900 | FR | étape A | non | non | 1 |
| A — ce que vous vendez | `onboarding-1-offre-fr-390x844.png` | 390×844 | FR | étape A | non | non | 1 |
| B — à qui et où | `onboarding-2-clients-fr-1440x900.png` | 1440×900 | FR | étape B | non | non | 1 |
| B — à qui et où | `onboarding-2-clients-fr-390x844.png` | 390×844 | FR | étape B | non | non | 1 |
| C — à partir de quel montant | `onboarding-3-seuil-fr-1440x900.png` | 1440×900 | FR | étape C | non | non | 1 |
| C — à partir de quel montant | `onboarding-3-seuil-fr-390x844.png` | 390×844 | FR | étape C | non | non | 1 |
| Relecture | `onboarding-4-relecture-fr-1440x900.png` | 1440×900 | FR | prêt à enregistrer | non | non | 1 |
| Relecture | `onboarding-4-relecture-fr-390x844.png` | 390×844 | FR | prêt à enregistrer | non | non | 1 |
| Succès partiel | `onboarding-succes-partiel-fr-1440x900.png` | 1440×900 | FR | ciblage enregistré, session non relue | non | non | 1 |

Sur la vue de validation, le bouton n'était pas désactivé : il a répondu, et
l'avertissement nomme ce qui manque dans les mots du client.

Sur la relecture, le territoire est rendu **France** et non `FR` : la relecture
est en langage client, jamais en codes.

Sur le succès partiel, la formulation ne dit pas que la création a échoué —
elle a réussi. Le bouton « Finaliser et voir mes signaux » ne rejoue que la
relecture de session ; il n'émet aucun second `POST /target-icps`.

### Feed — moment d'activation

| Vue | Fichier | Dim. | Langue | État | DH | CT | h1 |
|---|---|---|---|---|---|---|---|
| Activation | `activation-3-grants-fr-1440x900.png` | 1440×900 | FR | 3 déblocages | non | non | 1 |
| Activation | `activation-3-grants-fr-390x844.png` | 390×844 | FR | 3 déblocages | non | non | 1 |
| Activation | `activation-3-grants-en-1440x900.png` | 1440×900 | EN | 3 déblocages | non | non | 1 |
| Activation | `activation-1-grant-fr-1440x900.png` | 1440×900 | FR | 1 déblocage (singulier) | non | non | 1 |
| Activation | `activation-0-grant-fr-1440x900.png` | 1440×900 | FR | 0 déblocage, aucun CTA | non | non | 1 |
| Activation | `activation-0-grant-fr-390x844.png` | 390×844 | FR | 0 déblocage, aucun CTA | non | non | 1 |

L'ordre est celui de la directive : le bandeau ponctuel d'abord, le panneau
Découverte ensuite. Le bandeau ne répète ni les places restantes, ni les
offres, ni le verrouillage — ce sont les mots du panneau, pas les siens.

À zéro déblocage, le titre reste « Votre ciblage est prêt » : le ciblage l'est
réellement. Aucun lien « Voir mon premier signal » n'est rendu.

### Premier signal

| Vue | Fichier | Dim. | Langue | État | DH | CT | h1 |
|---|---|---|---|---|---|---|---|
| Détail | `premier-signal-fr-1440x900.png` | 1440×900 | FR | ouvert depuis le CTA d'activation | non | non | 1 |
| Détail | `premier-signal-fr-390x844.png` | 390×844 | FR | ouvert depuis le CTA d'activation | non | non | 1 |

La fiche est celle qui existait ; P0-02 n'en produit aucune variante.

### Non-régression `/app/icps`

| Vue | Fichier | Dim. | Langue | État | DH | CT | h1 |
|---|---|---|---|---|---|---|---|
| Édition d'un profil | `icps-edition-fr-1440x900.png` | 1440×900 | FR | formulaire complet | non | non | 1 |

Les six groupes — nom, offres, corps de métier, territoires, seuil, résumé —
sont rendus **ensemble sur le même écran**, avec leurs valeurs existantes.
Aucun bouton « Suivant », aucun repère de progression : `/app/icps` n'est pas
devenu un assistant.

## Mesures

```text
23 captures + 3 vues mesurées sans capture (320 px)
débordement horizontal .................... 0 / 26
coupure de texte .......................... 0 / 26
titres h1 par vue ......................... 1 / 1 partout
```

Les trois vues mesurées sans capture sont les reflows à 320 × 800 de la
relecture d'onboarding et du feed d'activation, plus l'inscription en 320 —
cette dernière est conservée en image car c'est la plus dense.

Le contrôle de coupure ignore les libellés `.kivou-visually-hidden`, rognés
par conception pour les lecteurs d'écran.

## Accessibilité relevée sur ces vues

- un seul `h1` par écran ; les étapes d'onboarding sont des `h2` ;
- `ActivationProgress` est une `nav` nommée contenant une `ol` ; l'étape
  courante porte `aria-current="step"` et un mot lisible par un lecteur
  d'écran (`terminé` / `étape en cours` / `à venir`) — jamais la seule couleur ;
- aucun élément interactif dans le repère de progression ;
- le focus rejoint le titre de l'étape après Suivant et après Retour ;
- aucune boîte de dialogue, aucun piège de focus ;
- reflow à 320 px sans débordement.
