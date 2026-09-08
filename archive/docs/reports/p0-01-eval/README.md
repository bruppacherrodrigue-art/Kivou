# P0-01 — EVAL visuelle

Cinq vues de contrôle de la PR #15, produites sur le build de production de la
branche `feat/p0-01-public-product-proof`.

| Vue | Fichier |
|---|---|
| Page d'accueil — FR — 1440 × 900 | `homepage-fr-1440x900.png` |
| Page d'accueil — FR — 390 × 844 | `homepage-fr-390x844.png` |
| Démonstration de signal — FR — 1440 × 900 | `demo-fr-1440x900.png` |
| Démonstration de signal — EN — 390 × 844 | `demo-en-390x844.png` |
| Menu mobile ouvert — FR — 390 × 844 | `mobile-menu-fr-390x844.png` |

Elles vivent sous `docs/` et non dans `frontend/src/` ou `frontend/public/` :
ce sont des pièces de revue, elles n'entrent ni dans les assets de production
ni dans le bundle.

Les douze autres captures de la campagne — les quatre largeurs × deux langues ×
deux pages — restent hors dépôt, dans l'artefact de revue lié à la PR.

## Mesures relevées sur ces vues

```text
homepage FR 1440×900   débordement=non  coupures=0  header↓=77  h1↑=141
                       carte du signal 161→774, entièrement au-dessus du pli
homepage FR 390×844    débordement=non  coupures=0  header↓=77  h1↑=125
                       carte 1026→1685, sous le pli — composition empilée
demo FR 1440×900       débordement=non  coupures=0  header↓=77  h1↑=166
demo EN 390×844        débordement=non  coupures=0  header↓=77  h1↑=166  lang=en
menu mobile 390×844    débordement=non  5 liens visibles
```

Le pli n'est atteint par la carte que sur desktop : en 390 px la composition
s'empile, et le titre, la promesse et les deux appels à l'action précèdent le
signal. C'est la contrainte de la largeur, pas un choix de hiérarchie.

Aucune coupure de texte n'a été relevée. Les seuls éléments dont le contenu
dépasse la boîte sont les libellés `.kivou-visually-hidden` du bouton de menu —
1 × 1 px et `clip`, rognés par conception pour les lecteurs d'écran.
