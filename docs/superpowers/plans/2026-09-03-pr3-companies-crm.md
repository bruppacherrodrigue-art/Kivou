# PR3 Companies CRM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer la liste CRM Entreprises, son panneau imbriqué, un déploiement fail-closed commun aux deux environnements et une CI qui ne relance que les surfaces utiles sur les PR.

**Architecture:** La page React consomme les contrats `/companies` sans reconstruire les titulaires depuis `/signals`; le panneau entreprise conserve son état pendant que `SignalDrawer` se superpose. Le script Bash prépare une release identifiée par SHA puis sépare strictement prévalidation sur copie jetable et mutation vive. La CI route les changements puis distribue les cas pytest sur quatre bases PostgreSQL isolées.

**Tech Stack:** React 19, TypeScript, React Router, CSS Modules, Vitest, Playwright, Bash, PostgreSQL 16, Alembic, GitHub Actions.

---

### Task 1: Fermer les contrats frontend `/companies`

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Test: `frontend/src/api/client.test.ts`

- [ ] Ajouter un test rouge qui exige la sérialisation répétée de `contact_status`, `q`, `limit` et `cursor`, puis les payloads `{status}` et `{body}`.
- [ ] Exécuter `npm test -- --run src/api/client.test.ts` et confirmer l'absence des méthodes.
- [ ] Définir `CompanyListItem`, `CompanyListPage`, `CompanyContactStatus`, le profil enrichi et les méthodes `list`, `contact`, `note`.
- [ ] Rejouer le test ciblé puis `npx tsc -b`.

### Task 2: Remplacer la liste Entreprises

**Files:**
- Delete: `frontend/src/pages/Companies.tsx`
- Delete: `frontend/src/pages/CompanyProfile.tsx`
- Create: `frontend/src/companies/CompaniesPage.tsx`
- Create: `frontend/src/companies/CompaniesPage.module.css`
- Create: `frontend/src/companies/CompaniesPage.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] Écrire des tests rouges pour le titre/sous-titre, les quatre segments avec compteurs, `q`, le tableau, les valeurs absentes et « Charger plus ».
- [ ] Confirmer les échecs avec `npm test -- --run src/companies/CompaniesPage.test.tsx`.
- [ ] Implémenter les requêtes serveur, compteurs, pagination par curseur, déduplication et navigation par ligne.
- [ ] Rejouer les tests et vérifier que la page n'appelle jamais `/signals` pour construire la liste.

### Task 3: Ajouter le panneau entreprise et le drawer superposé

**Files:**
- Create: `frontend/src/companies/CompanyDrawer.tsx`
- Create: `frontend/src/companies/CompanyDrawer.module.css`
- Create: `frontend/src/companies/CompanyDrawer.test.tsx`
- Modify: `frontend/src/companies/CompaniesPage.tsx`
- Reuse: `frontend/src/signals/components/SignalRow.tsx`
- Reuse: `frontend/src/signals/components/SignalDrawer.tsx`

- [ ] Écrire les tests rouges du lien profond, identité, largeur desktop, fermeture, deux actions contact, note au blur et historique limité à `contacted_at`.
- [ ] Ajouter le test rouge où un `SignalRow` ouvre `SignalDrawer` au-dessus sans fermer l'entreprise.
- [ ] Implémenter le panneau, les mutations optimistes seulement après succès et l'état « Enregistré » de la note.
- [ ] Rejouer les tests ciblés, puis supprimer `companyProfile.test.tsx` et `referenceCompanies.test.tsx` avec les anciens composants.

### Task 4: Nettoyer le vocabulaire et les traductions Entreprises

**Files:**
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Test: `frontend/src/companies/CompaniesPage.test.tsx`

- [ ] Ajouter un test qui interdit les termes bannis dans le rendu Entreprises.
- [ ] Ajouter les libellés sobres de la nouvelle page et retirer les clés devenues orphelines.
- [ ] Exécuter les tests Entreprises, `npx tsc -b` et `npm run lint`.

### Task 5: Régénérer les références Entreprises

**Files:**
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-companies-desktop.png`
- Modify: `frontend/tests/visual/reference-goldens/dashboard-companies-mobile.png`

- [ ] Réactiver uniquement les deux cas `dashboard-companies` marqués `TODO PR3` et adapter leurs attentes à la liste CRM.
- [ ] Exécuter `npm run test:visual -- --grep dashboard-companies --update-snapshots`.
- [ ] Rejouer les deux tests sans mise à jour et inspecter visuellement les images.

### Task 6: Créer le déploiement fail-closed

**Files:**
- Create: `ops/bin/kivou-deploy.sh`
- Create: `tests/test_ops_deploy_script.py`
- Modify: `ops/README.md`

- [ ] Écrire un test Bash piloté par pytest avec commandes factices où la répétition Alembic échoue, puis vérifier : exit non-zéro, aucun marqueur migration vive/restart/bascule.
- [ ] Confirmer le test rouge avec `uv run pytest -q tests/test_ops_deploy_script.py`.
- [ ] Implémenter validation environnement/SHA, checkout, builds verrouillés, backup, restauration avec rôle applicatif, répétition, migration vive, bascule atomique, restart et readiness.
- [ ] Ajouter les tests d'idempotence, d'ordre des phases et de conservation de la release précédente.
- [ ] Remplacer dans `ops/README.md` la procédure manuelle par l'invocation du script et documenter les prérequis.
- [ ] Exécuter `uv run pytest -q tests/test_ops_deploy_script.py tests/test_ops_api_readiness.py` et `bash -n ops/bin/kivou-deploy.sh`.

### Task 7: Accélérer la CI sans réduire le gate final

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `ops/bin/kivou-pytest-shard.sh`
- Create: `tests/test_ci_workflow.py`

- [ ] Écrire les tests rouges exigeant un détecteur de chemins, quatre shards PostgreSQL, un job d'agrégation et le forçage backend/frontend sur `push main`.
- [ ] Écrire le test rouge du partitionnement déterministe et exhaustif des fichiers `tests/test_*.py`.
- [ ] Implémenter le script de partition sans nouvelle dépendance et le workflow conditionnel.
- [ ] Exécuter `uv run pytest -q tests/test_ci_workflow.py` et vérifier les quatre listes sans doublon ni omission.

### Task 8: Vérification, PR et staging

**Files:**
- Modify only if a verified failure belongs to PR3.

- [ ] Exécuter les suites frontend ciblées, visuelles, build, typecheck et lint.
- [ ] Exécuter les tests backend ciblés et les quatre shards localement ou confirmer leur union par le test de contrat.
- [ ] Vérifier `git diff --check`, les fichiers protégés non suivis et l'absence de changement acquisition.
- [ ] Commiter avec la chaîne co-auteur choisie, pousser et ouvrir la PR vers `main`.
- [ ] Attendre l'unique CI finale décisionnelle, fusionner si verte, puis déployer staging exclusivement avec `ops/bin/kivou-deploy.sh staging <sha>`.
- [ ] Vérifier les SHA actifs, Alembic, readiness et produire le compte rendu en 12 lignes.
