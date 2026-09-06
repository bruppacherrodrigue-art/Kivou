# Compte rendu recette finition — 2026-09-06
Branche : `fix/recette-finition` depuis `main`; staging déployé par `ops/bin/kivou-deploy.sh`.
Checkout staging réparé sans suppression : `source.broken-2026-09-06`; propriétaire `kivou:kivou` et git-dir valides.
Garde-fou déployé : git-dir valide et propriétaire `kivou:kivou` requis avant toute action.
Backfill objets : 0 signal dématérialisé; 1465 conservés sur libellé CPV.
Contrat hors ligne : 1 signal + 1 profil; phrase, titulaire, objet, montant, lieu et date égaux sur les quatre canaux.
Propagation contact : `À contacter 277 → 276`; `Contactées 29 → 30`; compteurs partagés confirmés.
Playwright Découverte : desktop et mobile verts, drawer ouvert, aucune largeur débordante.
Playwright Essentiel : desktop et mobile verts, drawer ouvert, aucune largeur débordante.
Captures jointes : `docs/reports/2026-09-06-recette-finition/captures/`.
Performance avant (05/09, chargement page) : `/signals` 1,8 s; `/companies` 2,9 s.
Performance après : `/signals` médiane 129,2 ms, p95 311,8 ms.
Performance après : `/companies` médiane 270,8 ms, p95 436,5 ms; cible < 1 s atteinte.
Filtre Secteur : disponible en Essentiel, décision Rodrigue intégrée.
Tests ciblés backend, frontend et déploiement verts; staging via `kivou-deploy.sh` confirmé.
