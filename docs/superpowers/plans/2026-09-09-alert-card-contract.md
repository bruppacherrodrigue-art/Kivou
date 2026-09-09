# Alert Card Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every transactional alert an exact Aujourd'hui card and prove it against the real dashboard response and dry-run mail output.

**Architecture:** Extract one card-to-message projection used by production delivery and dry-run inspection. Keep recency claims available to internal freshness logic but exclude them from the client projection. Synchronize all environment-specific systemd units from each deployed release.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest, Bash, systemd, SMTP, ripgrep.

---

### Task 1: Contract-first real mail projection

**Files:**
- Modify: `src/signals/alerts/cli.py`
- Modify: `src/signals/alerts/job.py`
- Modify: `src/signals/alerts/renderer.py`
- Modify: `tests/test_alerts_cycle.py`
- Modify: `tests/test_smtp_gateway.py`

- [ ] Add a failing contract test that invokes the CLI dry-run path with an account id and asserts the emitted message contains only the dashboard card fields, `Ouvrir`, désinscription and legal footer; assert the three forbidden recency strings are absent.
- [ ] Make the test use the same materialized signal and card data as `GET /dashboard`, comparing every displayed field rather than testing renderer internals.
- [ ] Extract the message construction from `_run_for_account` so both SMTP delivery and `--dry-run --account` use it; dry-run must never acquire a delivery lease, write delivery rows, or call SMTP.
- [ ] Render one HTML card per signal with the exact dashboard field order and one `Ouvrir` link, with no greeting or extra prose before the first card; retain only unsubscribe and legal footer after cards.
- [ ] Remove headline/why-now claim fields from the client projection while leaving freshness claims available to internal decision logic.
- [ ] Run the new contract test red then green, followed by `tests/test_alerts_cycle.py` and `tests/test_smtp_gateway.py`.
- [ ] Change the deterministic Message-ID default domain and its assertions to `kivou.eu`; preserve deterministic retry identity.
- [ ] Commit: `fix(alerts): make mail cards identical to dashboard`.

### Task 2: Deployment and host evidence

**Files:**
- Modify: `ops/bin/kivou-deploy.sh`
- Modify: `tests/test_ops_deploy_script.py`
- Modify: `docs/reports/2026-09-09-recette-prod/README.md`

- [ ] Keep the existing failing-first synchronization test and extend it to verify production and staging source directories, file mode `0644`, `daemon-reload`, and the idempotent deployment path.
- [ ] Install `rg` on both hosts with `sudo apt-get update` and `sudo apt-get install -y ripgrep`, then verify `rg --version` without printing environment secrets.
- [ ] Deploy the merged `main` SHA to staging and production only after CI is green; verify readiness and that installed units hash to the active release copies.
- [ ] Capture `rg -n` proofs over the rendered dry-run HTML/text and assert counts of `Une attribution concernant`, `Publication récente`, and `date de décision` are zero.
- [ ] Commit: `ops: make alert rendering evidence reproducible` if report changes remain after the implementation commit.

### Task 3: Production resend and acceptance evidence

**Files:**
- Modify: `docs/reports/2026-09-09-recette-prod/README.md`

- [ ] Run `python -m signals.alerts --dry-run --account <recipe-account>` on the active production release and save the rendered output outside the repository until verified.
- [ ] Compare the dry-run output to the authenticated production `GET /dashboard` response for the same signal.
- [ ] Send one real QA alert after deployment, query the durable delivery row for exact recipient and Message-ID, and collect the application/system journal lines.
- [ ] Record only the reproducible commands, status, Message-ID domain, recipient, and zero-count forbidden-string proof in the report.
- [ ] Run the full backend suite, frontend suite, shell syntax checks, and `git diff --check`; update PR #194, wait for all checks green, squash-merge, and verify `main` SHA before deployment.

