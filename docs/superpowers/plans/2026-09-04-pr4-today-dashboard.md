# PR4 Today Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer l’écran Aujourd’hui, le shell et le vocabulaire Kivou final, supprimer l’ancienne implémentation de référence et exposer la ville dans le profil entreprise.

**Architecture:** Le dashboard consomme le contrat agrégé existant et compose les primitives Signal déjà livrées. Le shell reste propriétaire du profil et du plan, tandis que les primitives historiques encore utiles quittent `reference/` pour des modules neutres. Le backend enrichit uniquement `CompanyProfile.city`.

**Tech Stack:** React 19, TypeScript, React Router, Vitest, Playwright, FastAPI, Pydantic, pytest.

---

### Task 1: Contrat dashboard frontend

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Test: `frontend/src/pages/dashboard.test.tsx`

- [ ] Écrire des tests qui montent `/app/dashboard` avec un payload `GET /dashboard` réaliste et échouent faute de bandeau, cartes, listes et état vide.
- [ ] Exécuter uniquement `npm test -- --run src/pages/dashboard.test.tsx` et confirmer les échecs attendus.
- [ ] Déclarer `DashboardResponse`, `DashboardWeek`, `DashboardFollowUp` et `dashboard.get()` conformément au JSON backend.
- [ ] Réexécuter le test ciblé sans lancer la suite globale.

### Task 2: Écran Aujourd’hui

**Files:**
- Replace: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/pages/Dashboard.module.css`
- Test: `frontend/src/pages/dashboard.test.tsx`

- [ ] Ajouter les tests RED pour le titre première visite/visite suivante, les trois cartes et la première raison de fit.
- [ ] Implémenter le chargement du dashboard et du profil actif, les cartes compactes et les formats date/montant/lieu.
- [ ] Ajouter le test RED d’ouverture du `SignalDrawer`, puis brancher le drawer partagé.
- [ ] Ajouter le test RED d’Ignorer qui appelle le feedback et fait apparaître le signal suivant, puis implémenter mutation optimiste et rechargement.
- [ ] Ajouter les tests RED des relances, compteurs et états vides, puis implémenter les deux listes.
- [ ] Vérifier le fichier ciblé après chaque cycle rouge/vert.

### Task 3: Shell final

**Files:**
- Modify: `frontend/src/layouts/AppShell.tsx`
- Modify: `frontend/src/styles/dashboard.css`
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Test: `frontend/src/layouts/appShellReference.test.tsx`
- Test: `frontend/src/pages/referenceResponsiveContract.test.tsx`

- [ ] Écrire les attentes RED sur l’ordre Aujourd’hui · Signaux · Entreprises · Profil cible · Alertes · Réglages et le bandeau plan complet.
- [ ] Ajouter les routes distinctes aux six entrées et supprimer le second titre de page du topbar.
- [ ] Composer le bandeau plan depuis billing + profil actif, avec « — » pour les absences.
- [ ] Retirer le skip PR4 responsive et rendre la page sans défilement à 1280 × 800.

### Task 4: Sortie de `reference/`

**Files:**
- Delete: `frontend/src/reference/`
- Delete: `frontend/src/pages/PhaseABtpDemo.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: imports under `frontend/src/`
- Modify: `frontend/tests/visual/reference-port.spec.ts`

- [ ] Cartographier chaque import encore actif et déplacer seulement les primitives nécessaires vers `components/ui`, `components`, `hooks`, `layouts` et `styles`.
- [ ] Mettre à jour les imports avec `rg`, puis vérifier qu’aucune occurrence `src/reference` ne reste.
- [ ] Supprimer le branchement et la démo Phase A non liés depuis la landing.
- [ ] Exécuter typecheck et les tests ciblés des consommateurs déplacés.

### Task 5: Vocabulaire client

**Files:**
- Modify: `frontend/src/i18n/fr.ts`
- Modify: `frontend/src/i18n/en.ts`
- Modify: `frontend/src/pages/Landing.tsx`
- Modify: `frontend/src/pages/Product.tsx`
- Modify: `frontend/src/pages/PublicPricing.tsx`
- Modify: `frontend/src/pages/Onboarding.tsx`
- Modify: `src/signals/alerts/content.py`
- Test: existing landing, pricing, onboarding and alert content tests

- [ ] Ajouter un test de garde qui recherche les termes bannis dans les surfaces client demandées.
- [ ] Remplacer les formulations par signal, titulaire et profil cible sans modifier les textes juridiques ni les commentaires techniques hors surface.
- [ ] Supprimer les clés i18n devenues orphelines avec l’ancien dashboard.
- [ ] Lister dans le rapport final les occurrences laissées volontairement et leur justification.

### Task 6: Ville du profil entreprise

**Files:**
- Modify: `src/signals/companies/contracts.py`
- Modify: `src/signals/api/routes_companies.py`
- Modify: `frontend/src/api/types.ts`
- Test: `tests/test_saas_company_api.py`
- Test: `frontend/src/companies/CompaniesPage.test.tsx`

- [ ] Écrire un test backend RED exigeant `city` dans `GET /companies/{key}`.
- [ ] Dériver la ville depuis les signaux accessibles déjà chargés et l’ajouter au contrat Pydantic.
- [ ] Écrire le test frontend RED du deep-link direct, puis afficher la ville renvoyée.
- [ ] Exécuter uniquement ces tests backend/frontend.

### Task 7: Goldens et livraison

**Files:**
- Modify: `frontend/tests/visual/reference-port.spec.ts`
- Modify: `frontend/tests/visual/*.png`

- [ ] Retirer tous les `test.skip` PR4 et régénérer les goldens Aujourd’hui bureau/mobile et menu mobile.
- [ ] Inspecter visuellement les images à 1280 × 800 et mobile ; corriger uniquement les écarts au design approuvé.
- [ ] Exécuter une fois les suites complètes frontend/backend, les builds, typecheck, lint et `git diff --check`.
- [ ] Ouvrir la PR vers `main`, attendre la CI décisionnelle, fusionner sans force-push.
- [ ] Déployer le SHA de merge via `ops/bin/kivou-deploy.sh`, vérifier idempotence, symlinks et readiness.
