# Staging Backup Runbook Executability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the versioned Card Intelligence staging rollout executable when the SSH login directory is private and backups remain `kivou:700`/`600`.

**Architecture:** Keep the rollout topology and ordering unchanged. Pin every remote shell in sections 3–6 to the shared `/srv/kivou` working directory, and execute the two backup metadata reads as `kivou`; a structural test locks both invariants before staging resumes.

**Tech Stack:** Markdown runbook, Bash, Python 3.12, pytest, Ruff, GitHub Actions.

---

### Task 1: Add the failing runbook regression test

**Files:**
- Modify: `tests/test_card_presentation_runbook.py`
- Test: `tests/test_card_presentation_runbook.py`

- [ ] **Step 1: Add the failing test below after the existing backup test**

```python
def test_remote_rollout_shells_use_shared_cwd_and_private_backup_identity() -> None:
    commands = _commands(
        _between(
            _body(),
            "## 3. Sauvegarder, lister et restaurer dans une base scratch unique",
            "## 7. Exiger le compte QA puis backfiller FR et EN séparément",
        )
    )

    shared_prefix = "set -euo pipefail\ncd /srv/kivou\n"
    assert commands.count(shared_prefix + "KIVOU_FINAL_SHORT=$1") == 1
    assert commands.count(shared_prefix + "KIVOU_FINAL_SHA=$1") == 1
    assert commands.count(shared_prefix + "KIVOU_RELEASE_DIR=$1") == 4
    assert (
        'test "$(sudo -u kivou stat -c \'%U:%G:%a\' '
        '"$KIVOU_BACKUP_FILE")" = "kivou:kivou:600"'
        in commands
    )
    assert (
        'KIVOU_BACKUP_BYTES=$(sudo -u kivou stat -c \'%s\' '
        '"$KIVOU_BACKUP_FILE")'
        in commands
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run pytest tests/test_card_presentation_runbook.py::test_remote_rollout_shells_use_shared_cwd_and_private_backup_identity -q
```

Expected: `FAIL`; the current runbook contains no `cd /srv/kivou` prefixes and reads both backup metadata fields as the SSH user.

- [ ] **Step 3: Commit only the failing test**

```bash
git add tests/test_card_presentation_runbook.py
git commit -m "test(ops): reproduce private backup rollout failure"
```

### Task 2: Make the remote shells executable

**Files:**
- Modify: `docs/runbooks/11-staging-card-presentation-rollout.md`
- Test: `tests/test_card_presentation_runbook.py`

- [ ] **Step 1: Pin the shared working directory in the six remote shells**

Immediately after `set -euo pipefail` in the section 3 backup shell, both
section 4 backend shells, the section 5 blue/green bootstrap and proof shell,
and the section 6 frontend shell, add:

```bash
cd /srv/kivou
```

Do not add it to the local section 5 extraction shell.

- [ ] **Step 2: Read private dump metadata as `kivou`**

Replace the owner/mode assertion with:

```bash
test "$(sudo -u kivou stat -c '%U:%G:%a' "$KIVOU_BACKUP_FILE")" = \
  "kivou:kivou:600"
```

Replace the size read with:

```bash
KIVOU_BACKUP_BYTES=$(sudo -u kivou stat -c '%s' "$KIVOU_BACKUP_FILE")
```

- [ ] **Step 3: Run the focused test and verify GREEN**

Run:

```bash
uv run pytest tests/test_card_presentation_runbook.py::test_remote_rollout_shells_use_shared_cwd_and_private_backup_identity -q
```

Expected: `1 passed`.

- [ ] **Step 4: Run the complete runbook suite and lint**

Run:

```bash
uv run pytest tests/test_card_presentation_runbook.py -q
uv run ruff check tests/test_card_presentation_runbook.py
git diff --check
```

Expected: all runbook tests pass, Ruff exits `0`, and `git diff --check` emits no output.

- [ ] **Step 5: Commit the minimal implementation**

```bash
git add docs/runbooks/11-staging-card-presentation-rollout.md
git commit -m "fix(ops): make staging backup rollout executable"
```

### Task 3: Integrate and re-establish the deployment gate

**Files:**
- Verify: `.github/workflows/ci.yml`
- Verify: `docs/runbooks/11-staging-card-presentation-rollout.md`

- [ ] **Step 1: Push normally and open a focused PR against current `main`**

```bash
git push -u origin fix/staging-runbook-executable
gh pr create --base main --head fix/staging-runbook-executable \
  --title "fix(ops): rendre le rollout staging exécutable" \
  --body-file /tmp/kivou-runbook-pr-body.md
```

The PR body must record the real failure, the untouched `0027` state, the
fresh but diagnostic-only backup, the test evidence, and that production was
not contacted.

- [ ] **Step 2: Require both real PR jobs**

Run `gh run view` for the PR SHA and require non-empty successful steps for:

```text
Backend: dependency sync, Tests, Lint
Frontend: dependency install, Tests, Chromium, visual regression,
          Build, Founder Console build, Typecheck, Lint
```

Expected: both jobs `completed/success`; only conditional visual artifact upload may be skipped.

- [ ] **Step 3: Squash merge and prove the merged tree**

Require unchanged `main`, mark the PR Ready, squash merge without force-push,
then assert that the merge parent is the reviewed base and the merge tree is
identical to the reviewed head tree.

- [ ] **Step 4: Require the exact final `main` push CI**

Find the `push` run for the exact merge SHA and apply the same two-job,
non-empty-step assertions. Expected: complete success before any new staging
mutation.

- [ ] **Step 5: Restart the versioned rollout from section 1**

Recreate the SHA-scoped evidence directory for the new final SHA, revalidate
the protected QA binding and browser storage state, rerun a fresh backup and
scratch restore, then continue the existing versioned runbook. Do not reuse
the diagnostic backup as the migration gate.
