# Signaux + Entreprises 1280 — plan d’implémentation

## Étape 1 — validation visuelle

1. Ajouter un flag serveur fermé par défaut et l’exposer aux pages Signaux et Entreprises.
2. Brancher les deux écrans sur le conteneur centré de 1 280 px, avec une liste de 640 px, un panneau de 600 px, deux moitiés sous 1 280 px utiles et une feuille plein écran sous 900 px.
3. Rendre le nouveau tableau Signaux et la fiche de décision dans l’ordre validé, en réutilisant la fiche Contact connectée à l’annuaire commun.
4. Simplifier la liste Entreprises et conserver la fiche entreprise validée, dont le contact est flouté en Découverte.
5. Commiter la maquette fournie, pousser la branche, activer le flag sur staging et enrichir le jeu de recette de façon bornée.
6. Capturer Signaux et Entreprises à 1 440 px, 2 560 px et 390 px pour QA Découverte et client-3mois.

## Étape 2 — après accord de Rodrigue

1. Ajouter ou mettre à jour les tests du composant, les contrats et les goldens utiles.
2. Exécuter les vérifications ciblées et la CI, corriger les régressions dans le périmètre.
3. Ouvrir la PR, fusionner après CI verte, puis déployer la révision fusionnée depuis `main`.
4. Vérifier la production avec les comptes de recette et fournir les captures desktop et mobile.

Le parcours d’atterrissage kat1 et les services d’acquisition, de recherche entreprise et de recherche de contact restent hors périmètre.
