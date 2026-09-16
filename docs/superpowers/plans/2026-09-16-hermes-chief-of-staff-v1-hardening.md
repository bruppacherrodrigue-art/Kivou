# Hermes Chief of Staff V1 — plan de durcissement

> **For Codex:** suivre ce plan en TDD, conserver `plan` rétrocompatible et ne
> produire aucun appel fournisseur réel.

Date : 2026-09-16
Branche : `feat/hermes-chief-of-staff-v1`
HEAD initial : `499e40985ad50cfd0c1a62f827aacafa82ad71b9`
Merge-base : `ef159fa8fcc078f1e85811c76e6cfa2bc60e0eae`

## 1. Établir les baselines

- Rejouer les quatre shards backend et le frontend sur le merge-base avec les
  versions, variables et PostgreSQL 16 de CI.
- Rejouer les mêmes commandes sur la branche finale.
- Ne corriger dans cette PR qu'une régression imputable à son diff.

## 2. Verrouiller modèle et budget

- Écrire les tests rouges : route absente, store absent, mauvais usage,
  variables absentes/partielles, aucun fallback et configuration complète.
- Rendre l'adapter invalide avant réservation/transport si la configuration ne
  concorde pas exactement.
- Rendre `_configured_model("report")` fail-closed tout en conservant `plan`.
- Borner l'environnement du subprocessus à la variable de l'opération.
- Rejouer les tests Supervisor et Chief of Staff ciblés.

## 3. Publier la disponibilité réelle des capacités

- Écrire les tests rouges de domaine/source manquant, sources complètes et
  ordre canonique.
- Introduire un contrat de statut et une matrice déterministe possédée par
  Kivou.
- Construire le contexte v2 depuis cette matrice et signaler les faits `STALE`.
- Mettre à jour profil, spécification, ADR et documentation des sources.

## 4. Journaliser chaque tentative sans contenu brut

- Écrire les tests rouges des six statuts terminaux, des rejets JSON/Pydantic/
  sémantiques, de l'idempotence et de l'absence de texte brut.
- Étendre la migration non publiée `0065` avec une table append-only indexée.
- Ajouter un store sans méthode de mutation et corréler le `model_call_journal`
  par identifiant préparé avant l'appel.
- Finaliser exactement une tentative après échec fournisseur, rejet de réponse,
  rejet sémantique, validation sèche, insertion ou conflit idempotent.

## 5. Durcir la validation sémantique

- Écrire les tests rouges pour preuves absentes, sources externes, inconnues,
  langage quantitatif détourné, données périmées, exécution prétendue et
  empreinte/période divergentes.
- Refuser fail-closed avec des codes de rejet fermés et assainis.
- Vérifier que les injections restent du contenu et qu'aucun rejet ne conserve
  la réponse brute.

## 6. Démontrer et vérifier

- Étendre la démonstration offline : capacités, contexte borné, WATCH,
  validation, persistance idempotente, API Founder, tentative assainie,
  `provider_calls=0`, `business_actions=0`.
- Vérifier upgrade depuis `0064`, downgrade documentaire, PostgreSQL, SQLite et
  tête Alembic unique.
- Exécuter toutes les commandes backend/frontend demandées, `git diff --check`
  et une recherche de secrets/artefacts.
- Auto-relire le diff complet, committer, pousser la branche existante, garder
  la PR en brouillon et contrôler son CI sans fusionner.
