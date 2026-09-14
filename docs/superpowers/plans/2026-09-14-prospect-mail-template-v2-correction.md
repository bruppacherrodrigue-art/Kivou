# Prospect Mail Template v2 Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger le rendu v2, son catalogue famille et son contrat, puis régénérer la file de production sans envoi.

**Architecture:** La normalisation reste une fonction pure du renderer. Le YAML porte les formulations françaises complètes avec articles ; le renderer assemble la phrase famille et la justification cible. La régénération existante verrouille et historise les cibles non envoyées.

**Tech Stack:** Python 3.12, PyYAML, SQLAlchemy Core, pytest, Ruff, PostgreSQL, systemd.

---

### Task 1: Verrouiller le contrat corrigé

**Files:**
- Modify: `tests/test_personalization_prospect_mail.py`
- Test: `tests/test_personalization_prospect_mail.py`

- [ ] **Step 1: Write the failing renderer test**

Ajouter un cas dont `signal_holder` vaut `CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD` et vérifier : sujet et corps avec `CMCD`, phrase famille `Sur ce type de lot, le titulaire sous-traite souvent la couverture et la zinguerie, et vous êtes couvreur-zingueur à Sillingy.`, phrase Kivou avant `Bien à vous,`, nouveau P.S., aucune URL BOAMP/DECP, pied source officiel et exactement deux liens.

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest -n0 -q tests/test_personalization_prospect_mail.py`

Expected: FAIL sur l'ancien titulaire, l'ancienne justification, l'URL source et l'ancien P.S.

### Task 2: Corriger le catalogue et le renderer

**Files:**
- Modify: `ops/config/prospect-mail.yaml`
- Modify: `src/signals/personalization/prospect_mail.py`
- Test: `tests/test_personalization_prospect_mail.py`

- [ ] **Step 1: Rewrite every family sentence in YAML**

Chaque `sentence` devient un complément général avec article correct, par exemple `la couverture et la zinguerie`, `le béton prêt à l'emploi`, `l'électricité`, sans prédiction au futur.

- [ ] **Step 2: Implement deterministic holder normalization**

Ajouter une fonction pure qui préfère un sigle terminal explicite en majuscules (`... - CMCD` → `CMCD`) puis applique le nettoyage existant des formes juridiques.

- [ ] **Step 3: Assemble the corrected copy**

Construire la phrase famille depuis le YAML et le métier cible, retirer `signal_source_url` du texte et du HTML, placer la phrase Kivou avant `Bien à vous,`, ajouter la signature puis le nouveau P.S., et conserver la source officielle uniquement dans le pied.

- [ ] **Step 4: Strengthen validation**

Le contrat exige le nouveau P.S., `Bien à vous,`, la source officielle dans le pied, deux URL seulement, aucune URL source, et au plus 110 mots hors pied.

- [ ] **Step 5: Run GREEN checks**

Run: `uv run pytest -n0 -q tests/test_personalization_prospect_mail.py`

Expected: `10 passed` ou davantage.

Run: `uv run ruff check src/signals/personalization/prospect_mail.py tests/test_personalization_prospect_mail.py`

Expected: `All checks passed!`

### Task 3: Publier et régénérer

**Files:**
- Existing: `src/signals/prospection_actions/service.py`

- [ ] **Step 1: Verify the focused prospection suite**

Run: `uv run pytest -n0 -q tests/test_personalization_prospect_mail.py tests/test_assisted_prospect_preparation.py tests/test_prospection_actions_service.py`

Expected: zéro échec.

- [ ] **Step 2: Commit, merge and deploy main**

Créer un commit limité au gabarit, au YAML et aux tests, ouvrir puis fusionner le PR, et déployer le SHA exact avec `ops/bin/kivou-deploy.sh production <SHA>`.

- [ ] **Step 3: Regenerate without sending**

Appeler `ProspectionActions.regenerate_pending_mail_v2()` en production. Vérifier que seules les cibles `pending_review` et `approved` sont mises à jour, qu'un événement `mail_regenerated_v2` est ajouté et que le nombre d'envois reste nul.

- [ ] **Step 4: Read ALPES ZINGUERIE from production**

Relire `prospect_target.target_id = 2788222b-65d1-5754-9f32-18a217040a13`, vérifier le contrat, les deux liens, l'absence d'URL source et afficher le texte exact à Rodrigue.
