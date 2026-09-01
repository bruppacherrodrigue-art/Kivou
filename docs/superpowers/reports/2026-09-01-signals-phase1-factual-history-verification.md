# Signaux Phase 1 — rapport de vérification

**Date :** 2026-09-01
**Branche :** `fix/signals-phase1-factual-history`
**Base vérifiée :** `68888298c5e4f2a4bb1ea8d34eaf4c156ee586ae`
**Périmètre :** faits vérifiés, historique, navigation et Winner Enrichment uniquement
**Déploiement :** aucun staging, aucune production
**IA commerciale : DÉSACTIVÉE**

## Résultat

La page Signaux est désormais un workspace master-detail factuel. La liste et
le détail possèdent des scrolls indépendants sur desktop ; la vue mobile affiche
un seul panneau, focalise le titre du détail sans déplacer la liste et rend le
focus au retour. Les liens directs, précédent/suivant, les filtres URL et la
sélection restent stables.

L'historique passe par une pagination serveur à curseur fermé et un tri
déterministe : date d'attribution réelle, sinon notification, sinon publication,
puis clé stable du signal. Les droits existants restent l'autorité serveur :
Discovery est limité aux attributions accordées, Essential à 30 jours, Pro à
365 jours et Scale à tout l'historique disponible. Aucun plan, prix ou checkout
n'a été modifié.

Le détail et les cartes utilisent exclusivement `factual_display` et
`winner_enrichment`. Signaux ignore les anciens artefacts de présentation,
l'analyse, les besoins plausibles, les rôles et les recommandations, même si
ces champs existent encore pour d'autres surfaces. Un teaser verrouillé ne
reçoit ni `presentation`, ni faits protégés, ni clé entreprise.

## Causes racines

1. Signaux utilisait le flux de la page et des actions de focus/scroll globales,
   tandis qu'Entreprises isolait déjà la liste et le détail. Une sélection
   pouvait donc remonter la fenêtre et déplacer les cartes.
2. Le frontend demandait systématiquement `freshness=new`; l'API récente était
   paginée par offset et une limite de candidats, sans contrat d'historique à
   curseur. Les anciennes attributions étaient invisibles ou recherchées par
   balayage de pages.
3. La hiérarchie de Signaux dépendait de titres administratifs et de la
   présentation commerciale héritée, au lieu d'un contrat factuel borné produit
   par le serveur.
4. La fiche gagnante pouvait être projetée pendant un GET. Cela empêchait de
   garantir des GET sans effet, un chargement batché et un état d'enrichissement
   durable.
5. La régression visuelle supposait une page unique très longue. Elle ne
   contrôlait ni les deux scrolls, ni les états factuels, ni les erreurs console.

## Décisions d'architecture

- `signals.feed.history` encode un curseur Base64/JSON à clés exactes, versionné,
  borné et rejeté en 422 s'il est malformé. La lecture keyset est isolée par
  compte et résiste aux insertions concurrentes placées avant le curseur.
- `/signals` distingue `view=recent` et `view=history`. Les filtres période,
  pays, subdivision, statut et CPV sont vérifiés côté serveur selon le niveau de
  filtre du plan. La réponse explique les limites au lieu de simuler un vide.
- `factual_display` est construit uniquement depuis l'identité résolue et les
  faits structurés du marché. Les titres sont bornés à 220 caractères et ne
  requalifient jamais publication en attribution.
- `winner_enrichment_job` porte un cycle durable `pending`, `in_progress`,
  `completed`, `partial`, `failed`, trois tentatives au maximum et des claims
  concurrents. Le worker est explicite, non démarré automatiquement, idempotent
  et ne lit que les sources déjà autorisées et stockées.
- Les GET Signaux/Entreprises ne lancent ni connecteur ni worker. Ils lisent en
  batch les clés entreprises et les états d'enrichissement ; les tests de
  compteur de requêtes protègent l'absence de N+1.
- Le frontend conserve vue, filtres et sélection dans l'URL et transmet le
  curseur serveur sans le reconstruire. Une génération de requête invalide les
  réponses devenues obsolètes.

## Migration et backfill

La migration additive `0030_winner_enrichment`, enfant de
`0029_production_observation`, crée uniquement `winner_enrichment_job`, ses
contraintes et ses deux index. Le backfill SQL est set-based et hors réseau :

- toutes les lignes `materialized_signal` sont mises en file, y compris une
  identité non résolue ;
- une fiche existante n'est `completed` que si les faits officiels requis sont
  présents ; sinon elle est `partial` ;
- une fiche absente reste `pending` pour le worker explicite.

La migration a été exécutée uniquement dans les bases éphémères de test. Elle
n'a été appliquée ni en staging ni en production.

## Vérifications exécutées

### Backend

- `uv run pytest -q` — interrompu volontairement à **32 % sans échec observé**
  pour ne pas dupliquer pendant plus d'une heure le job Backend distant. Le
  même `pytest -q` reste un gate obligatoire dans GitHub Actions et son résultat
  exact sera reporté sur la PR.
- suite de migrations affectées — **221 passed in 215.58s**.
- `uv run pytest -q tests/test_ingestion_e2e.py tests/test_winner_enrichment_api.py tests/test_feed_history.py`
  — **9 passed in 15.07s**.
- régressions feed/paywall/faits ciblées — **107 passed in 160.24s**.
- worker, API et GET sans provider ciblés — **36 passed, 1 skipped in 45.11s**.
- `uv run ruff check .` — **PASS**, `All checks passed!`.

### Frontend

- tests ciblés Signaux + Entreprises + adapters — **219 passed in 5.54s**.
- `npm test -- --run` — **724 passed, 43 files, 34.19s**.
- `npm run typecheck` — **PASS**.
- `npm run lint` — **PASS**.
- `npm run build` — **PASS**, 2 009 modules, 3.96s ; avertissement historique
  de taille de chunk uniquement.
- `npm run build:founder` — **PASS**, 32 modules, 1.05s.
- `npm run test:visual` — **33 passed in 44.7s**.

### Dépôt

- `git diff --check` — **PASS** sur les changements non commités ; le contrôle
  final `origin/main...HEAD` est rejoué après le commit de ce rapport.
- recherche des ajouts `provider`, `model`, `prompt`, `Hermes`, `Acquisition`,
  `Apollo` — aucun import ou appel live dans les chemins Phase 1.

## Captures inspectées à résolution d'origine

Goldens suivis :

- `frontend/tests/visual/reference-goldens/dashboard-signals-desktop.png` ;
- `frontend/tests/visual/reference-goldens/dashboard-signals-mobile.png`.

Captures locales d'inspection, volontairement ignorées par Git :

- `output/playwright/signals-phase1/before-desktop.png` ;
- `output/playwright/signals-phase1/before-mobile.png` ;
- `output/playwright/signals-phase1/desktop-rich.png` ;
- `output/playwright/signals-phase1/desktop-old-failed-no-location.png` ;
- `output/playwright/signals-phase1/desktop-pending-no-amount.png` ;
- `output/playwright/signals-phase1/mobile-partial.png`.

L'inspection confirme : aucun chevauchement mobile, aucun débordement
horizontal, liste et détail indépendants, sélection visible, états compacts,
sources techniques repliées, faits absents explicitement « Non publié » et
aucune erreur console. Elle a révélé puis fait corriger une clé React dupliquée
dans les groupes de preuves.

## Fichiers modifiés

- Backend : routes et droits Signaux, requête historique, curseur, projection
  factuelle, service/contrats/schéma d'entreprise, worker et matérialisation.
- Migration : `0030_winner_enrichment.py` et attentes de tête Alembic.
- Frontend : contrats API, adapters, modèles, `SignalsFeed`, détail factuel,
  styles, traductions FR/EN et harness.
- Tests : pagination/entitlements/faits/enrichissement/migrations, workspaces
  Signaux et Entreprises, accessibilité, états, fixtures et goldens Playwright.
- Documentation : conception, plan et ce rapport.

La liste exacte reste disponible par :
`git diff --name-only origin/main...HEAD`.

## Limites et risques restants

- Aucun nouveau registre, fournisseur payant ou crawling n'est ajouté. Les
  données site, secteur, taille ou description restent « indisponibles » si les
  connecteurs autorisés ne les ont pas déjà publiées.
- Le worker n'est pas auto-activé par cette PR. Son ordonnancement opérationnel
  devra être décidé séparément avant tout environnement partagé.
- Les artefacts commerciaux hérités demeurent compatibles pour les autres
  surfaces, mais Signaux ne les lit pas. La Phase 2 devra définir provider,
  prompts versionnés, QA Signals, worker hors GET et jeu d'évaluation avant
  toute activation `PASS/FULL`.
- La migration doit être appliquée après sauvegarde dans une mission de
  déploiement distincte ; cette PR ne prouve aucun runtime staging.

## Rollback

1. Revenir aux commits applicatifs précédents et reconstruire le frontend.
2. Laisser par défaut la migration additive `0030` en place : l'ancien code
   ignore la table et aucune colonne existante n'est modifiée.
3. Ne downgrader qu'après sauvegarde et décision DBA explicite. Le downgrade
   supprime uniquement les deux index et `winner_enrichment_job`, donc son état
   de travail serait perdu.
4. Aucun rollback de pricing, provider ou production n'est nécessaire : aucun
   de ces périmètres n'est touché.

## Statut IA

**IA commerciale : DÉSACTIVÉE.** Aucun modèle, provider, prompt, worker IA,
Hermes, Acquisition Engine, email ou simulation de pertinence commerciale n'a
été choisi, appelé ou activé. Les statuts affichés décrivent uniquement la
complétude des faits et l'état réel du Winner Enrichment.
