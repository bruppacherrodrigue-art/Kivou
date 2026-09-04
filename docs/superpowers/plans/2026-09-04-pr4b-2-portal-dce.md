# PR4b-2 Portal DCE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Télécharger anonymement les DCE des instances ATEXO et de XMarchés, tout en appliquant des politiques d’accès réversibles, une cadence humaine et un reporting persistant par hébergeur.

**Architecture:** `documents/portals/` expose un routeur qui choisit un adaptateur à partir de l’empreinte HTML et non du seul domaine. Un fichier de politique relu à chaque tentative bloque les plateformes juridiquement ou techniquement interdites sans redéploiement ; une discipline d’hôte persistée en base impose 20 secondes entre dossiers, backoff et coupure de 24 heures après trois erreurs HTTP consécutives. Le résultat reste un `FetchResult`, puis emprunte sans exception la chaîne bornée archive/extraction de PR4b.

**Tech Stack:** Python 3.12, httpx, Playwright Chromium pour ATEXO, HTML standard library pour XMarchés, SQLAlchemy Core, Alembic batch SQLite/PostgreSQL, pytest hors ligne.

---

### Task 1: Politique et modèle opérationnel

**Files:** create `src/signals/documents/portals/policy.py`; modify `src/signals/documents/model.py`, `src/signals/persistence/schema.py`; create migration `src/signals/persistence/migrations/versions/0037_portal_capture_runtime.py`; test `tests/test_portal_policy.py`, `tests/test_portal_capture_migration.py`.

- [x] Écrire et exécuter les tests RED pour les trois refus par défaut, leur surcharge depuis un JSON relu sans redémarrage, les nouveaux statuts et l’état d’hôte persistant.
- [x] Implémenter le minimum : `portal_blocked`, `cgu_restricted`, registre JSON sûr par défaut et table `portal_capture_runtime` avec migration batch.
- [x] Exécuter les tests ciblés GREEN, puis les migrations SQLite concernées.

### Task 2: Détection et retrait ATEXO

**Files:** create `src/signals/documents/portals/base.py`, `src/signals/documents/portals/registry.py`, `src/signals/documents/portals/atexo.py`, `tests/fixtures/documents/portals/atexo-*.html`, `tests/test_portal_atexo.py`.

- [x] Ajouter des extraits HTML réels et des tests RED prouvant la détection ATEXO sur PLACE, Maximilien, Mégalis et AMPA, plus une instance inconnue portant la même empreinte.
- [x] Tester RED le parcours navigateur anonyme, l’identité Kivou obligatoire lorsque le formulaire la propose, la sélection de l’archive complète et le refus des exécutables.
- [x] Implémenter l’adaptateur Playwright générique à session réutilisée et vérifier les tests GREEN sans réseau.

### Task 3: Retrait XMarchés et statuts bloqués

**Files:** create `src/signals/documents/portals/xmarches.py`, `tests/fixtures/documents/portals/xmarches-*.html`, `tests/test_portal_xmarches.py`; modify `src/signals/documents/portals/registry.py`.

- [x] Écrire les tests RED sur les pages réelles XMarchés : détection, retrait anonyme, archive complète et identité Kivou si demandée.
- [x] Écrire les tests RED garantissant qu’achatpublic, marches-publics.info et Marchés Sécurisés ne déclenchent aucune requête de retrait avec leur politique par défaut.
- [x] Implémenter XMarchés et le routage des refus, puis exécuter les tests GREEN.

### Task 4: Cadence, backoff et circuit-breaker

**Files:** create `src/signals/documents/portals/discipline.py`; modify `src/signals/documents/portals/base.py`; test `tests/test_portal_discipline.py`.

- [x] Tester RED l’intervalle minimal de 20 secondes par hébergeur, le backoff de tout 4xx/5xx, le reset après succès et la coupure persistante de 24 h après trois erreurs consécutives.
- [x] Implémenter la discipline avec horloge/sommeil injectables et stockage SQLAlchemy, puis vérifier GREEN.

### Task 5: Intégration à la capture et configuration

**Files:** modify `src/signals/documents/fetch.py`, `src/signals/documents/early_capture.py`, `src/signals/ingestion/cli.py`, `ops/systemd/kivou-tender-notices.service`, `ops/systemd/production/kivou-tender-notices.service`, `ops/README.md`; test `tests/test_portal_capture_integration.py`, `tests/test_ingestion_cli.py`.

- [x] Tester RED qu’une page portail reconnue est résolue par l’adaptateur, que les bornes existantes s’appliquent aux octets rendus et que raison sociale/mail manquants arrêtent proprement le retrait qui les exige.
- [x] Brancher le routeur au fetcher, charger `KIVOU_PORTAL_POLICY_FILE`, `KIVOU_PORTAL_COMPANY_NAME` et `KIVOU_PORTAL_CONTACT_EMAIL`, documenter les secrets et valeurs initiales, puis vérifier GREEN.

### Task 6: Rapport persistant et livraison

**Files:** modify `src/signals/documents/early_capture.py`, `docs/reports/2026-09-04-early-dce-capture.md`; test `tests/test_early_capture_report.py`.

- [x] Tester RED le tableau par hébergeur lu en base : URL, téléchargés, taux, bloqués/motifs, taille moyenne et exigences classifiées par dossier.
- [x] Implémenter les agrégats SQL sans compteur mémoire et vérifier GREEN.
- [x] Exécuter une seule validation finale backend pertinente, lint, migrations et test d’interdiction réseau ; inspecter le diff, committer, pousser et ouvrir la PR.
- [x] Après CI verte, déployer le SHA via `ops/bin/kivou-deploy.sh`, lancer la fenêtre BOAMP de sept jours avec la commande quotidienne, relire le tableau en base et compléter le rapport avant le compte rendu.
