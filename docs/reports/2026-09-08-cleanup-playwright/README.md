# Recette Playwright cleanup-2026-09

Staging `staging.kivou.eu`, SHA `f19eec4cacc51a15e5b27ad209fdfe62db3afc4a`.
Chromium installé par `ops/bin/kivou-deploy.sh` dans l'environnement staging.

| Compte | Desktop | Mobile | Observations |
|---|---|---|---|
| Découverte | [signaux](decouverte-desktop-signals.png), [drawer](decouverte-desktop-drawer.png) | [signaux](decouverte-mobile-signals.png), [drawer](decouverte-mobile-drawer.png) | shell et quota Découverte visibles |
| client-3mois / Essentiel | [signaux](client-3mois-desktop-signals.png), [drawer](client-3mois-desktop-drawer.png) | [signaux](client-3mois-mobile-signals.png), [drawer](client-3mois-mobile-drawer.png) | shell client et flux chargés |
| compte de recette | [signaux](recette-desktop-signals.png), [drawer](recette-desktop-drawer.png) | [signaux](recette-mobile-signals.png), [drawer](recette-mobile-drawer.png) | session réutilisée pour éviter le rate-limit login |

Le compte recette a été connecté une seule fois puis la même session a été
redimensionnée à 390 px. Résultats bruts : [recipe-results.json](recipe-results.json).
