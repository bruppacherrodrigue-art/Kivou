# Staging Secret Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the repository-side cause of #81 and provide a safe, testable operator path for rotating and auditing staging secrets without putting secret values in process arguments or output.

**Architecture:** Add one dependency-free operator CLI with two operations: atomically replace allowlisted variables in a protected environment file from another protected file, and scan journal text from stdin against secret values held only in memory while emitting counters only. Document the exact staging sequence, provider boundary, consumer validation, journald rotation/purge, and rollback in one runbook.

**Tech Stack:** Python 3.12 standard library, pytest, systemd/journald, POSIX file ownership and modes.

---

### Task 1: Prove the unsafe paths are rejected

**Files:**
- Create: `tests/test_ops_secret_hygiene.py`
- Test: `docs/runbooks/09-staging-secret-rotation.md`
- Test: `ops/bin/kivou_secret_hygiene.py`

- [ ] Write tests that invoke the future CLI with fake PostgreSQL, SMTP, Stripe TEST, and webhook secrets; assert that journal matches produce only numeric counters and that no fake value appears on stdout or stderr.
- [ ] Write a test that asserts replacement preserves the target mode and replaces all four allowlisted values atomically without printing them.
- [ ] Write repository-policy assertions rejecting secret-bearing `sudo env`, secret-bearing `grep` arguments, and database URLs in operator command arguments.
- [ ] Run `uv run pytest tests/test_ops_secret_hygiene.py -q` and confirm RED because the CLI and runbook do not exist.

### Task 2: Implement the minimal hygiene CLI

**Files:**
- Create: `ops/bin/kivou_secret_hygiene.py`
- Modify: `tests/test_ops_secret_hygiene.py`

- [ ] Implement strict parsing for exactly `KIVOU_DATABASE_URL`, `SMTP_PASSWORD`, `STRIPE_SECRET_KEY`, and `STRIPE_WEBHOOK_SECRET` from a mode-0600 values file.
- [ ] Implement `replace-env` using a temporary file in the target directory, `fsync`, preserved owner/group/mode, and `os.replace`; output counts only.
- [ ] Implement `audit-journal` as a streaming stdin scan; retain values only in memory, output only `secret_values_checked`, `matching_lines`, and `matching_occurrences`, and return non-zero when matches exist.
- [ ] Run the focused tests until GREEN, then `uv run ruff check ops/bin/kivou_secret_hygiene.py tests/test_ops_secret_hygiene.py`.

### Task 3: Version the safe rotation procedure

**Files:**
- Create: `docs/runbooks/09-staging-secret-rotation.md`
- Modify: `ops/README.md`
- Modify: `tests/test_ops_secret_hygiene.py`

- [ ] Document a root-only tmpfs workspace, provider rotation order, protected value files, atomic replacement, consumer restart order, DB/API/SMTP/Stripe TEST/webhook TEST proofs, destruction of backups, journald rotate/vacuum, and counter-only final scan.
- [ ] Explicitly prohibit secret values in argv, `sudo env`, `grep`, terminal output, shell history, Git, GitHub, and journald; retain `EnvironmentFile=/etc/kivou/staging.env` for service parity.
- [ ] Document rollback without retaining compromised values after successful validation.
- [ ] Run `uv run pytest tests/test_ops_secret_hygiene.py tests/test_ops_alerts_runtime.py tests/test_ops_backup_runtime.py tests/test_reliability_runbooks_architecture.py -q`, Ruff, and `git diff --check`.

### Task 4: Deliver and operate #81

**Files:**
- Modify only through the reviewed PR above; staging secret values remain outside Git.

- [ ] Commit the repository changes, push `fix/staging-secret-operations`, and open a PR referencing #81 with root cause, minimal fix, risks/rollback, proofs, and closure criteria.
- [ ] Run the standard GitHub CI once on the final PR HEAD; review, squash-merge, verify the exact `main` SHA, and deploy that SHA to staging without production changes.
- [ ] Rotate all four staging values using existing provider access, update `/etc/kivou/staging.env` atomically as `root:kivou` mode `600`, and restart only affected staging consumers.
- [ ] Validate PostgreSQL, API, SMTP, Stripe TEST Checkout, and signed Stripe TEST webhook; delete root-only backups after validation.
- [ ] Rotate/vacuum journald per server policy and run the counter-only audit over both old and new values; require zero matches before documenting evidence and closing #81.
