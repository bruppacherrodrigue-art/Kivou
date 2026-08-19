# Contribuer à Kivou

Kivou est développé avec une forte assistance IA. Ces quelques règles existent
pour que cela reste sûr, pas pour créer de la procédure.

## Le flux

1. Partir de `main`, sur une branche : `git switch -c feat/mon-sujet`.
2. Écrire le code et les tests.
3. Faire passer les deux suites en local (voir ci-dessous).
4. Ouvrir une pull request. La CI doit être verte avant fusion.

`main` ne se modifie pas directement. Aucune réécriture d'historique, aucun
`push --force`.

## Avant d'ouvrir une PR

```bash
# Backend
uv run pytest -q
uv run ruff check .

# Frontend
cd frontend && npm test -- --run && npm run build && npx tsc -b && npm run lint
```

## Ce qui ne doit jamais être committé

Aucun secret. Ni clé Stripe, ni secret de webhook, ni mot de passe SMTP, ni URL
de base de données avec identifiants, ni jeton d'API.

La configuration passe par l'environnement. `.env.example` documente les noms de
variables et ne contient que des valeurs d'exemple ; `.env` est ignoré par Git.

Les fichiers construits ne sont pas suivis : `frontend/dist/`,
`frontend/node_modules/`, `.venv/`, les caches.

## Ce que l'automatisation a le droit de faire

Une automatisation — assistant IA compris — peut créer une branche, modifier du
code, lancer les tests et ouvrir une PR.

Elle ne peut pas pousser en force sur `main`, contourner la CI, ni déployer en
production. Le déploiement reste une décision humaine, et il porte toujours sur
un SHA de commit GitHub validé — jamais sur « ce qu'il y a dans mon dossier de
travail ».

## Tests hors ligne

La suite ne joint aucun réseau et ne demande aucun secret. Un test qui
réclamerait une clé réelle est un défaut d'isolation à corriger, pas une raison
d'ajouter un secret à la CI.
