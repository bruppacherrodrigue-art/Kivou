# Prospection assistée — plan d'implémentation

> **Contrat partagé :** `docs/superpowers/specs/2026-09-11-assisted-prospection-actions-contract.md`

**But :** préparer jusqu'à 25 cibles par jour en `pending_review`, puis permettre au Founder de les valider, corriger, écarter et envoyer manuellement, sans ouvrir l'envoi automatique du runtime.

**Architecture :** une table `prospect_target` conserve le message final et l'instantané des preuves ; un service applicatif transactionnel porte toutes les mutations ; un adaptateur Instantly à permis borné ne peut être appelé que par `send`. Le runtime `ASSISTED` matérialise les cibles après personnalisation et s'arrête avant les étapes de campagne. Le rôle PostgreSQL Founder d'écriture est séparé de la connexion de lecture existante.

**Stack :** Python 3.12, Pydantic, SQLAlchemy Core, Alembic, FastAPI, PostgreSQL, httpx, pytest.

---

## 1. Persistance et contrats applicatifs

- Ajouter `prospect_target`, `prospect_target_history` et `prospect_send_request` dans le schéma et une migration Alembic.
- Contraindre statuts, motifs de rejet, vérification MX, plafonds et identifiants d'idempotence.
- Définir les modèles Pydantic `ProspectTargetV1` et les cinq commandes/réponses publiées.
- Tester migration, validation fermée des motifs et sérialisation du mail final.

## 2. Store et actions de revue

- Implémenter liste paginée, approbation optimiste, correction auditée et rejet propagé à `supplier_directory`.
- Réémettre le jeton d'attribution lorsque l'adresse change et revérifier MX.
- Tester conflits de version, transitions, absence de dirigeant et effets annuaire.

## 3. Envoi manuel borné

- Implémenter un port Instantly et ses adaptateurs fake/live avec permis éphémère limité aux cibles de la requête.
- Prévalider le lot sous verrou : kill switch, approved, MX, suppression, versions, plafond 25.
- Rendre `request_id` idempotent et persister identifiant, coût et compte de requêtes par cible.
- Tester refus sans validation, refus MX, kill switch, plafond, idempotence et absence d'appel avant validation complète.

## 4. Préparation `ASSISTED`

- Étendre le schéma de configuration à `ASSISTED` tout en conservant `SHADOW` et le verrou d'envoi par défaut.
- Après personnalisation, créer une cible prête à partir depuis le signal, l'annuaire et le contact ; ne jamais exécuter campagne/provider handoff en `ASSISTED`.
- Appliquer l'unicité avis/jour, 25 cibles/jour, 5 signaux/jour, effectif >= 10, MX, suppression et délai de 90 jours.
- Tester trois cycles fake et la production de la file sans mutation fournisseur.

## 5. Qualité des coordonnées résiduelles

- Accepter une adresse publiée sur un site confirmé même si son domaine diffère, en conservant l'URL de preuve.
- Retenter les erreurs de connexion à J+1 deux fois ; ne marquer `sans site` qu'après 30 résultats analysés (10 x 3 requêtes).
- Tester la distinction absence exhaustive / panne temporaire et la fraîcheur de 90 jours.

## 6. Retours et statistiques

- Projeter ouvertures, clics, réponses, désinscriptions et bounces sur `prospect_target`.
- Invalider l'adresse annuaire sur bounce et inscrire la suppression sur désinscription.
- Étendre `stats --since` avec préparées, validées, motifs de rejet, envoyées et événements aval.
- Tester bounce, réponse et agrégats.

## 7. Accès PostgreSQL et exploitation

- Ajouter une connexion Founder d'écriture dédiée, refusée si le rôle n'est pas `kivou_founder_rw` en production.
- Accorder uniquement les droits nécessaires aux tables de prospection et aux corrections d'annuaire.
- Documenter kill switch, cadence assisted et reprise ; mettre à jour les exemples de configuration.
- Tester la validation de configuration et les permissions attendues.

## 8. Validation et livraison

- Exécuter les tests ciblés après chaque tranche, puis les contrôles statiques concernés.
- Pousser la branche et ouvrir la PR avec contrat et design court.
- Après fusion : staging fake, trois cycles, scénario 5/1/2/5 et captures ; production `ASSISTED` uniquement après validation staging, sans envoi automatique.
