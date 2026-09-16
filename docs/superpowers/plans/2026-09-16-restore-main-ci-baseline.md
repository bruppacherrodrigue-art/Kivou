# Restore Main CI Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restaurer les trois contrats CI cassés sur `main` sans modifier le comportement métier, le renderer commercial partagé ni le comportement responsive approuvé.

**Architecture:** La route `claim-access` reçoit une publication nginx exacte et symétrique, sous la limite d'authentification existante. Les contrats mail et responsive sont réalignés sur leurs sources versionnées actuelles, avec une preuve structurelle du rôle du breakpoint mobile.

**Tech Stack:** Python 3.12, pytest, nginx, React, TypeScript, Vitest, CSS, Ruff, npm.

---

### Task 1: Publier explicitement `POST /auth/claim-access`

**Files:**
- Modify: `tests/test_ops_nginx_routes.py`
- Modify: `ops/nginx/kivou-staging.conf`
- Modify: `ops/nginx/kivou-production.conf`
- Test: `tests/test_ops_nginx_routes.py`
- Test: `tests/test_ops_production_runtime.py`

- [ ] **Step 1: Étendre le contrat avant la configuration**

Ajouter `("POST", "/auth/claim-access")` à `PUBLIC_ASGI_ROUTES`, ajouter
`"= /auth/claim-access"` à `EXPECTED_PROXY_SELECTORS`, puis ajouter un test
qui lit les deux configurations et exige exactement :

```python
(
    "limit_req zone=kivou_auth burst=3 nodelay;",
    "proxy_pass http://127.0.0.1:KIVOU_API_PORT;",
    "include /etc/nginx/kivou-proxy-params.conf;",
)
```

Le test vérifie aussi l'absence de `add_header`, `proxy_hide_header`,
`sensitive-links-gate` et `try_files` dans cette location ordinaire.

- [ ] **Step 2: Vérifier RED**

Run:

```bash
uv run pytest -q -n 0 \
  tests/test_ops_nginx_routes.py::test_every_reviewed_public_route_reaches_fastapi_and_private_routes_do_not \
  tests/test_ops_nginx_routes.py::test_claim_access_uses_the_reviewed_auth_proxy_contract_in_staging_and_production
```

Expected: échec parce que la location exacte `= /auth/claim-access` manque.

- [ ] **Step 3: Ajouter la configuration minimale**

Dans les deux fichiers nginx, immédiatement après `signup`, ajouter :

```nginx
location = /auth/claim-access {
    limit_req zone=kivou_auth burst=3 nodelay;
    proxy_pass http://127.0.0.1:KIVOU_API_PORT;
    include /etc/nginx/kivou-proxy-params.conf;
}
```

- [ ] **Step 4: Vérifier GREEN et la parité**

Run:

```bash
uv run pytest -q tests/test_ops_nginx_routes.py
uv run pytest -q tests/test_ops_production_runtime.py
uv run pytest -q tests/test_attribution_landing.py
```

Expected: zéro échec.

- [ ] **Step 5: Commit nginx**

```bash
git add tests/test_ops_nginx_routes.py ops/nginx/kivou-staging.conf ops/nginx/kivou-production.conf
git commit -m "fix(nginx): publish claim-access under reviewed auth limits"
```

### Task 2: Réaligner le contrat mail SHADOW

**Files:**
- Modify: `tests/test_acquisition_runtime_shadow_mail.py`
- Test: `tests/test_acquisition_runtime_shadow_mail.py`
- Test: `tests/test_personalization_prospect_mail.py`
- Test: `tests/test_personalization_validator.py`

- [ ] **Step 1: Conserver la preuve RED existante**

Le test initial échoue avec `à Rhône`, tandis que le renderer partagé produit
`en Rhône`. Le test canonique `test_shared_relevance_sentence_uses_en_for_a_department_only`
prouve que `en <département>` est la décision versionnée actuelle.

- [ ] **Step 2: Corriger uniquement l'attente obsolète**

Remplacer :

```python
"et vous êtes fournisseur de béton prêt à l'emploi à Rhône."
```

par :

```python
"et vous êtes fournisseur de béton prêt à l'emploi en Rhône."
```

Ne modifier ni `shadow_mail.py`, ni le catalogue, ni le renderer partagé.

- [ ] **Step 3: Vérifier GREEN et les consommateurs**

Run:

```bash
uv run pytest -q tests/test_acquisition_runtime_shadow_mail.py
uv run pytest -q tests/test_personalization_prospect_mail.py
uv run pytest -q tests/test_personalization_validator.py
```

Expected: zéro échec, statut SHADOW et contrats de contenu inchangés.

- [ ] **Step 4: Commit acquisition**

```bash
git add tests/test_acquisition_runtime_shadow_mail.py
git commit -m "fix(acquisition): align shadow mail copy contract"
```

### Task 3: Réaligner le contrat responsive de la bannière

**Files:**
- Modify: `frontend/src/pages/referenceResponsiveContract.test.tsx`
- Modify: `frontend/src/presentation/dashboard/app-shell.css`
- Test: `frontend/src/pages/referenceResponsiveContract.test.tsx`
- Test: `frontend/src/layouts/appShellOnboarding.test.tsx`

- [ ] **Step 1: Conserver la preuve RED existante**

Le contrat reçoit `max-width: 640px` en première position alors que sa liste
attendue commence à `min-width: 768px`.

- [ ] **Step 2: Verrouiller le rôle et les limites du breakpoint**

Ajouter `max-width: 640px` à la première position de l'inventaire. Ajouter un
test qui extrait la valeur `640` du bloc de la bannière, exige les trois règles
de pile mobile et vérifie les largeurs suivantes :

```typescript
[
  [390, true],
  [639, true],
  [640, true],
  [641, false],
  [1440, false],
]
```

- [ ] **Step 3: Documenter la décision CSS**

Ajouter un commentaire devant le media query indiquant que la copie et le CTA
de création d'accès s'empilent jusqu'à 640 px pour rester utilisables, sans
modifier les déclarations CSS.

- [ ] **Step 4: Vérifier GREEN**

Run:

```bash
cd frontend
npm test -- --run src/pages/referenceResponsiveContract.test.tsx
npm test -- --run src/layouts/appShellOnboarding.test.tsx
```

Expected: zéro échec.

- [ ] **Step 5: Commit frontend**

```bash
git add frontend/src/pages/referenceResponsiveContract.test.tsx frontend/src/presentation/dashboard/app-shell.css
git commit -m "fix(frontend): align responsive breakpoint contract"
```

### Task 4: Vérification complète et PR

**Files:**
- Verify only: repository and frontend suites

- [ ] **Step 1: Exécuter tous les tests ciblés requis**

Exécuter les commandes backend et frontend imposées dans la mission, sans
`skip`, `xfail`, retry ni élargissement de tolérance.

- [ ] **Step 2: Exécuter les quatre shards PostgreSQL de la CI**

Run:

```bash
ops/bin/kivou-pytest-shard.sh 0 4
ops/bin/kivou-pytest-shard.sh 1 4
ops/bin/kivou-pytest-shard.sh 2 4
ops/bin/kivou-pytest-shard.sh 3 4
```

Expected: quatre sorties avec zéro échec.

- [ ] **Step 3: Vérifier les artefacts et le diff**

Run:

```bash
uv run ruff check .
git diff --check origin/main...HEAD
```

Expected: succès et worktree propre après commit.

- [ ] **Step 4: Pousser et ouvrir la PR**

Pousser `fix/restore-main-ci-baseline`, ouvrir une PR vers `main` intitulée
`fix(ci): restore main baseline contracts`, attendre sa CI et ne fusionner
aucune PR.
