1. PR #173, branche fix/recette-finition depuis main, SHA staging e9f1381.
2. Compte staging actif: release e9f1381, déploiement exclusivement via ops/bin/kivou-deploy.sh.
3. Backfill objets: 0 signaux dématérialisés, 1 464 basculés sur libellé CPV.
4. Contrat quatre canaux hors ligne: 1/1 passe, phrase, titulaire, objet, montant, lieu et date identiques.
5. Drawer besoins: statuts déterminés/null, bloc absent du DOM quand aucun besoin n’est déterminé.
6. SignalCardRow sous 900 px: aucun table à 390 px, carte verrouillée incluse, aucun débordement.
7. Entreprises desktop: grille 1fr 520px, panneau à droite, liste Entreprise · Statut, sans fixed; mobile plein écran.
8. Statut contact: table unique propagée à Aujourd’hui, Cette semaine et Entreprises; scénario panneau validé.
9. Réglages: titre sans-serif, champs absents omis, sans tiret ni « Tarif facturé absent », Données export/suppression.
10. Zone: helper partagé et summary.profile.zone_labels, aucun code pays affiché sur mobile.
11. Playwright staging final: PLAYWRIGHT_FINITION_GREEN, Découverte et Essentiel, desktop/mobile, drawer inclus.
12. Captures jointes: decouverte-{desktop,mobile}.png et essentiel-{desktop,mobile}.png.
13. Performance client-3mois: baseline 05/09 page load 1,8 s /signals et 2,9 s /companies.
14. Performance après: médiane 129/271 ms, p95 312/437 ms; cible <1 s atteinte, sujet clos.
15. Contrôles locaux ciblés: 81/81 Vitest et typecheck verts; PR #173 prête pour revue production.
