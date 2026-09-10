# Plan d'implémentation

1. Ajouter les tests de contrat de l'appel registre, des fonctions acceptées, du
   repli neutre et de la détection/persistance des formulaires.
2. Étendre le modèle de dirigeant et la cascade web sans modifier Apollo/SIRENE.
3. Ajouter la migration `0049_supplier_contact_form` et le stockage daté.
4. Exécuter les tests ciblés, Ruff et la vérification de migration, puis ouvrir la PR.
5. Attendre la CI, fusionner, déployer `main` sur staging puis production, timer
   toujours arrêté, et rejouer les 75 cibles pour mesurer le taux.
