# Supplier Domain Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conserver uniquement les domaines et adresses professionnelles rattachés à l'entreprise SIRENE correspondante.

**Architecture:** Chaque candidat de domaine passe d'abord par la liste noire, puis par la présence d'un mot distinctif de la raison sociale dans le domaine, enfin, si nécessaire, par la présence du SIREN ou SIRET dans le pied de page ou les mentions légales. Le verdict est journalisé et persisté; l'annuaire refuse ensuite toute adresse dont le domaine n'est pas exactement le domaine validé. Un état daté force la revérification des entrées purgées.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy/Alembic, pytest, npm lockfile.

---

### Task 1: Domaine et adresse

- [x] Écrire et faire échouer les tests de liste noire, rapprochement SIREN et domaine e-mail strict.
- [x] Implémenter les trois verdicts bornés et leur journalisation.
- [x] Persister la méthode de validation et refuser les adresses hors domaine.

### Task 2: Annuaire et données existantes

- [x] Ajouter l'état persistant de revérification et sa migration.
- [ ] Déployer la migration puis purger les entrées tierces identifiées en production.
- [ ] Rejouer les 75 cibles avec le timer d'acquisition arrêté.

### Task 3: Dépendances et vérification

- [x] Verrouiller `js-yaml` sur la première version corrigée compatible.
- [x] Documenter le report de Vitest 4 et de la branche tmpfs.
- [ ] Exécuter les tests ciblés, la CI, puis vérifier le replay production.
