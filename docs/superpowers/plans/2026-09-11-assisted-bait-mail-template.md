# Assisted Bait Mail Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every acquisition mail renderer with one validated French template in `signals.personalization`, then regenerate the production review queue without sending.

**Architecture:** A versioned YAML catalog owns family wording and ordinary-French work terms. A pure personalization renderer normalizes the recipient, subject, work description, amount, date, and three links, then applies a fail-closed contract. Assisted preparation persists the contract result and Founder actions refuse approval or delivery when it failed; the legacy shadow entry point delegates to the same renderer.

**Tech Stack:** Python 3.12, Pydantic, PyYAML, SQLAlchemy/Alembic, pytest, PostgreSQL, systemd deployment tooling.

---

### Task 1: Specify the exact renderer contract

**Files:**
- Create: `tests/test_personalization_prospect_mail.py`
- Modify: `tests/test_acquisition_runtime_shadow_mail.py`

- [ ] **Step 1: Write the failing rendering tests**

```python
mail = render_prospect_mail(arbomis_row)
assert mail.subject == "PAUL BROCHIER vient de gagner un chantier charpente en Isère"
assert mail.text.startswith("Bonjour Arnaud Lefebvre,")
assert "la charpente, l'isolation et la couverture" in mail.text
assert mail.text.count("https://") == 3
assert mail.contract_failure is None
```

- [ ] **Step 2: Run the tests and confirm RED because the new renderer does not exist**

Run: `timeout 60s .venv/bin/pytest -q -n 0 tests/test_personalization_prospect_mail.py tests/test_acquisition_runtime_shadow_mail.py`

- [ ] **Step 3: Add focused cases for fallback greeting, title sanitization, amount/date formats, the 90-word limit, forbidden fragments, and delegation from shadow mode**

- [ ] **Step 4: Run the same command and keep it RED until implementation begins**

### Task 2: Implement the single personalization source

**Files:**
- Create: `ops/config/prospect-mail.yaml`
- Create: `src/signals/personalization/prospect_mail.py`
- Modify: `src/signals/acquisition_runtime/shadow_mail.py`
- Delete: `src/signals/prospection_actions/mail.py`

- [ ] **Step 1: Version family labels/sentences and ordinary-French work terms in YAML**
- [ ] **Step 2: Implement deterministic normalization and plain-text/HTML rendering**
- [ ] **Step 3: Implement `validate_prospect_mail` as a fail-closed contract that returns one stable failure reason**
- [ ] **Step 4: Make the shadow compatibility entry point delegate to this renderer and remove the old copy**
- [ ] **Step 5: Run Task 1 tests and confirm GREEN**

### Task 3: Persist and enforce the contract

**Files:**
- Create: `src/signals/persistence/migrations/versions/0054_prospect_mail_contract.py`
- Modify: `src/signals/persistence/schema.py`
- Modify: `src/signals/prospection_actions/preparation.py`
- Modify: `src/signals/prospection_actions/service.py`
- Modify: `tests/test_assisted_prospect_preparation.py`
- Modify: `tests/test_prospection_actions_service.py`
- Modify: `tests/test_prospection_actions_send.py`
- Modify: `tests/test_prospection_actions_migration.py`

- [ ] **Step 1: Write failing tests proving preparation stores `passed`, failed copy remains `pending_review`, and approval/send reject failed copy**
- [ ] **Step 2: Run the four focused test modules and confirm RED for missing contract fields**
- [ ] **Step 3: Add `signal_department`, `mail_contract_status`, and `mail_contract_failure`; tighten the body word-count check to 90**
- [ ] **Step 4: Render in preparation/correction through personalization and guard approval plus delivery**
- [ ] **Step 5: Run the focused tests and Ruff; confirm GREEN**

### Task 4: Integrate and prove production output

**Files:**
- Modify: production review rows through the deployed application command only
- Create: `docs/reports/2026-09-11-assisted-mail-template/production-queue.png`

- [ ] **Step 1: Scan source code for all retired fragments and require zero matches**
- [ ] **Step 2: Commit once, push to `main`, verify no CI run is active, and deploy `main` with `ops/bin/kivou-deploy.sh`**
- [ ] **Step 3: Verify readiness, stopped timer, active kill switch, and zero sent rows**
- [ ] **Step 4: Purge only the unsent review queue and run one assisted production cycle with delivery disabled**
- [ ] **Step 5: Extract ARBONIS, DUBOURGEAT, and DUBOIS ISOLATION subject/text from PostgreSQL**
- [ ] **Step 6: Capture the rendered queue and run DOM/source counts for every forbidden fragment**
- [ ] **Step 7: Recheck zero sent rows and report the three complete mails**
