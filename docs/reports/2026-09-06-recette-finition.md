0. Bloc compte desktop/mobile, déconnexion serveur et liens Settings/ICP: implémenté; auth/session ciblées vertes.
1. Phrase `for_you_sentence` et besoins déterminés: contrat partagé et fallback factuel implémentés; 117 tests backend ciblés verts.
2. Signaux sous 900 px: rendu ligne-carte responsive implémenté; couverture frontend complète verte.
3. Objet manquant/CPV: fallback CPV et exclusion du feed implémentés; 62 tests feed/carte verts.
4. Panneau Entreprises: desktop côte à côte et mobile plein écran via breakpoint 900 px; tests UI verts.
5. Statut contact: source existante conservée et propagation panel/feed validée par les tests existants.
6. Réglages: export/suppression et confirmations existants conservés; suite Settings verte.
7. Lignes verrouillées et offres: lien de découverte corrigé vers `/tarifs`; tests feed/paywall verts.
8. Identité entreprise: ligne publique SIRET/IDE/TVA conservée; provenance TED/SIMAP du drawer non supprimée.
9. Libellé date: cartes/drawer utilisent « Attribué le »; test de contrat frontend vert.
10. Bandeau Aujourd’hui: « correspondent fortement » masqué lorsque N=0; tests dashboard verts.
11. Quota illimité: affichage « N signaux ouverts ce mois » lorsque le quota est nul/illimité; tests frontend verts.
12. Zones: projection `zone_labels` et libellés lisibles conservés; aucun code pays ajouté aux phrases fallback.
13. Performance: non mesurée sur client-3mois dans cet environnement; benchmark distant restant à exécuter.
14. Secteur: disponible en Essentiel et Pro via niveau `basic`; test paywall vert. Recette: 670 tests frontend et backend ciblé verts; Playwright/staging non exécutés, variables DB absentes (`kivou-deploy.sh` bloque sur `KIVOU_DATABASE_URL`).
