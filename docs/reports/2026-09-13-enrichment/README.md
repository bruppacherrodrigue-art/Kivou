# Activation du worker d'enrichissement des titulaires — 13 septembre 2026

Ces captures proviennent de la console Système de production, en lecture seule,
après le déploiement de `main` au SHA `48680fe04c2e`.

- `captures/production-system-worker-active.png` : vue complète de la console ;
- `captures/production-system-budgets-current.png` : modèles, consommations et
  plafonds OpenRouter chargés pour la journée Europe/Zurich ;
- `captures/production-system-winner-timer.png` : timer
  `kivou-winner-enrichment.timer` actif, avec son dernier et son prochain
  passage.

Le premier passage automatique affiché s'est terminé avec `processed=0` et un
coût nul : le watermark d'activation exclut donc la file historique. La recette
isolée de matérialisation a enrichi une nouvelle fiche en 84 secondes, avec
3 177 tokens d'entrée, pour 0,00135025 USD et sans arbitrage.

Le rapport quantitatif des 65 fiches restantes et la projection des 590
titulaires récents seront ajoutés après l'exécution plafonnée programmée au
reset budgétaire du 14 septembre à 00:05 Europe/Zurich. Aucun backfill des 590
n'est inclus dans cette activation.
