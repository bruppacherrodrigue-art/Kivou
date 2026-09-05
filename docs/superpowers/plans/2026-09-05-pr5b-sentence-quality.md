# PR5b Sentence Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Imposer une phrase client factuelle, structurée et variée, puis démontrer sur 50 couples de trois profils staging un rejet inférieur à 15 % et zéro doublon de conséquence.

**Architecture:** `personalization.for_you` reste l’unique politique déterministe : il construit les équivalences factuelles et valide structure, titulaire et ancrage profil. Un constructeur de prompt partagé est consommé par les transports Anthropic et OpenRouter. Le benchmark crée trois profils isolés, matérialise 17/17/16 couples, exécute le worker borné et mesure séparément phrases complètes et conséquences normalisées.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy, pytest, OpenRouter, PostgreSQL staging.

---

### Task 1: Équivalences factuelles

**Files:**
- Modify: `src/signals/personalization/for_you.py`
- Test: `tests/test_for_you_sentence.py`

- [ ] Écrire des tests rouges acceptant `250 k€` depuis `250000 EUR`, `1,2 M€` depuis `1200000 EUR`, `2 ans` depuis `24 mois`, `août 2026` depuis `2026-08-12`, et `Isère` depuis un code postal `38000` présent dans l’entrée.
- [ ] Ajouter des contre-tests qui rejettent montant, durée, date et département non dérivables.
- [ ] Exécuter `timeout 60 uv run pytest -q tests/test_for_you_sentence.py -k equivalence` et constater les échecs attendus.
- [ ] Implémenter des ensembles de formes canoniques depuis les entrées : montants décimaux avec unités, durées mois/années, mois français depuis ISO, département depuis code postal français.
- [ ] Réexécuter le fichier ciblé et conserver tous les cas verts.

### Task 2: Contrat structurel adaptable

**Files:**
- Modify: `src/signals/personalization/for_you.py`
- Test: `tests/test_for_you_sentence.py`

- [ ] Écrire quatre tests rouges pour lieu présent/absent croisé avec bloc montant-date présent/absent, sans `—`.
- [ ] Écrire les tests rouges : titulaire absent, conséquence sans terme profil, `pourrait nécessiter`, `Ce marché porte sur`.
- [ ] Ajouter au motif fermé les rejets structurels nécessaires dans `src/signals/persistence/schema.py` et une migration seulement si le stockage exige de nouvelles valeurs ; sinon réutiliser `invalid_shape` pour éviter une migration.
- [ ] Implémenter la validation : titulaire normalisé obligatoire, séparateur `:`, conséquence non vide ancrée dans `profile_sector`, `profile_zones` ou `offer_summary`, formulations bannies.
- [ ] Exécuter `timeout 60 uv run pytest -q tests/test_for_you_sentence.py` jusqu’au vert.

### Task 3: Prompt partagé

**Files:**
- Modify: `src/signals/personalization/for_you.py`
- Modify: `src/signals/documents/providers.py`
- Modify: `src/signals/documents/openrouter.py`
- Test: `tests/test_for_you_sentence.py`

- [ ] Écrire un test rouge sur `build_for_you_prompt()` exigeant le gabarit, les omissions conditionnelles, les formulations bannies et la délimitation des entrées non fiables.
- [ ] Écrire un test rouge prouvant que les deux adaptateurs envoient exactement ce prompt partagé.
- [ ] Implémenter le constructeur sans nom de fournisseur dans `for_you.py`, puis supprimer les deux prompts dupliqués.
- [ ] Passer `timeout 120 uv run pytest -q tests/test_for_you_sentence.py tests/test_document_openrouter.py tests/test_document_classification.py::TestProviderBoundary` et Ruff ciblé.

### Task 4: Cache et politique v2

**Files:**
- Modify: `src/signals/personalization/for_you.py`
- Test: `tests/test_for_you_materialization.py`
- Test: `tests/test_for_you_worker.py`

- [ ] Écrire un test rouge prouvant que la nouvelle version de politique crée un nouveau couple sans modifier l’ancienne ligne.
- [ ] Passer `POLICY_VERSION` à `for-you-v2` afin que les phrases v1 ne soient jamais servies comme sorties conformes au nouveau contrat.
- [ ] Vérifier matérialisation non bloquante, cache et worker avec timeout.

### Task 5: Benchmark staging contrôlé

**Files:**
- Modify: `docs/reports/2026-09-04-pr5b-for-you-benchmark.md`

- [ ] Déployer le SHA applicatif vert via `kivou-deploy.sh` et vérifier readiness.
- [ ] Créer trois comptes/profils de benchmark identifiables et complets : bardage métallique/Isère, CVC plomberie/PACA, espaces verts/Nord.
- [ ] Sélectionner et matérialiser exactement 17, 17 et 16 signaux correspondant respectivement aux trois profils ; conserver leurs identifiants pour limiter le worker à ces 50 lignes v2.
- [ ] Exécuter le worker avec concurrence 4 et un plafond explicite couvrant uniquement ces 50 nouvelles tentatives.
- [ ] Interroger `for_you_sentence` : taux de rejet, 20 phrases, présence titulaire, ancrage conséquence, doublons complets et doublons du fragment après `:` normalisé.
- [ ] Si rejet ≥ 15 %, doublon de conséquence > 0 ou conformité < 50/50, corriger prompt/politique par un nouveau cycle TDD avant tout nouveau replay borné.
- [ ] Mettre à jour le rapport avec la méthode, les trois profils, les résultats et les 20 phrases.

### Task 6: Vérification et livraison en un commit

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-pr5b-for-you-sentence-design.md`
- Add: `docs/superpowers/plans/2026-09-05-pr5b-sentence-quality.md`

- [ ] Exécuter les suites ciblées backend, Ruff, `git diff --check`, puis une seule CI décisionnelle après le push.
- [ ] Amender le commit local `fix(personalization): tighten client sentence contract` avec plan, code, tests et rapport.
- [ ] Pousser une seule fois sans force, vérifier la CI et mettre à jour la PR #168.
