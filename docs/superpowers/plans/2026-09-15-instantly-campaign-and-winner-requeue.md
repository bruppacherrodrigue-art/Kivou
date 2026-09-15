# Instantly Campaign and Winner Requeue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the Instantly v2 assisted campaign payload and the invalid terminal-to-pending winner enrichment transition, then validate both in production with one isolated Gmail delivery.

**Architecture:** Keep both fixes at their sources: campaign serialization in the Instantly adapter and lifecycle reset in prospect preparation. Do not alter the database constraint or the 21 approved prospects.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy, PostgreSQL, pytest, Instantly API v2.

---

### Task 1: Instantly v2 campaign payload

**Files:**
- Modify: `src/signals/campaigns/instantly.py`
- Test: `tests/test_instantly_adapter.py`

- [x] Add a failing adapter test requiring `Europe/Belgrade` and `delay: 0` in the assisted campaign request.
- [x] Run the test and confirm it fails against `Europe/Paris` and the absent delay.
- [x] Change only those two request fields and document why Belgrade is used.
- [x] Run the adapter tests and confirm they pass.

### Task 2: Winner enrichment requeue lifecycle

**Files:**
- Modify: `src/signals/prospection_actions/preparation.py`
- Test: `tests/test_assisted_prospect_preparation.py`

- [x] Add a failing regression test that starts from a `partial` job with attempt and timestamps populated.
- [x] Run the test and confirm the lifecycle constraint rejects the current update.
- [x] Reset `attempt_count`, `started_at`, and `finished_at` when requeueing to `pending`.
- [x] Run preparation and enrichment tests and confirm they pass.

### Task 3: Release and real validation

**Files:**
- No production data-model changes.

- [x] Run focused pytest, Ruff, and `git diff --check`.
- [ ] Commit and push the exact SHA to `main`.
- [ ] Deploy through `kivou-deploy.sh` and verify the active release.
- [ ] Create and delete one empty Instantly validation campaign.
- [ ] Rerun the acquisition cycle and verify the lifecycle exception is gone.
- [ ] Create an isolated campaign and one fictitious lead for `rodrigue.bruppacher@gmail.com`, activate it after successful verification, and report the provider identifiers and state.
