# SPEC-031 — Reliability & Autonomous Operations — implementation

Status: code ready for supervisor review; production autonomy not ready

## Artifact boundary

- SPEC-030 squash/base lineage: `9b7cb4298f5a51b476976a8ec47d8e652a806285`
- implementation base/current main: `af2f0122c13d906d5af077e4c620eada7c4db0bc`
- executable SHA: `ef263fd1551d994e1d774505fdf7ca3b5c6a0b5d`
- executable CI: `32631262409` — SUCCESS
- Alembic head: `0021_reliability_operations`
- migration chain: `0020_hermes_learning_loop -> 0021_reliability_operations`
- SPEC-031 tables: exactly `acquisition_operational_incident` and `acquisition_dead_letter`
- acquisition state machine: `acquisition-state-v1`, unchanged
- acquisition `EventType`: unchanged

The intervening main change from the original SPEC-030 squash to the implementation base added only `docs/LEGAL_CONTENT.md` and `docs/ROAD_TO_LIVE.md`. The branch was rebased before publication; no acquisition, Policy, persistence, or runtime contract changed in that delta.

## Runtime identity and health

The existing Hermes lock remains authoritative: repository `https://github.com/NousResearch/hermes-agent.git`, tag `v2026.8.18`, commit `e624e9fde561e1add9388384012b295fde669ade`, version `0.20.4`, Python `>=3.11,<3.14`. `HermesRuntimeIdentity` verifies a configured/local observation against all five fields. Missing or mismatched observations are `NOT_READY`; verification performs no download or network lookup and exposes no self-upgrade path.

`acquisition-operational-health-v1` reports bounded `READY`, `DEGRADED`, or `NOT_READY` components for API, database, Hermes runtime, supervisor loop, Policy control, campaign execution, DLQ, and circuit breakers. It uses an injected time, emits reason codes rather than exception bodies, and stores no health history.

The repository-default H-A…H-G evidence is deliberately conservative:

- H-A Runtime: `NOT_READY` because the Hermes observation, persistent loop, and deployment environment are not configured by repository defaults.
- H-B State: `READY` at the code-contract level through durable replay identities and restart tests.
- H-C Policy: `READY` at the code-contract level; `ALLOWED_COMMANDS` and Policy profiles have exact coverage, and no new Hermes command exists.
- H-D Shadow: `INSUFFICIENT_EVIDENCE`; durable human-review verdict truth is not invented.
- H-E Capped: `NOT_READY`; production mailbox/provider prerequisites and complete acquisition-cost coverage are absent, and no production breaker evidence is assumed.
- H-F Closed loop: `READY` structurally; sent member/opportunity identities join safely to optional response, click, journey, activation, payment, MRR, retention, and churn facts, while no downstream outcome remains valid.
- H-G Scale: `NOT_READY` by default because the allocation envelope is unconfigured. The executable path still requires the sole `reallocate_volume` command, a durable SPEC-029 proposal, conversion/retention evidence, Policy approval, `ADAPTIVE_SCALE`, a non-stale baseline, and no relevant breaker.

The default `highest_safe_mode` is `SHADOW`. The readiness report is read-only and never changes the actual Policy mode.

## Incidents and circuit breakers

`acquisition-circuit-breaker-v1` uses scopes `GLOBAL`, `COUNTRY`, `WEDGE`, `CAMPAIGN`, and `MAILBOX`; severities `WARNING`, `HIGH`, and `CRITICAL`; and durable states `OPEN`, `ACKNOWLEDGED`, and `RESOLVED`. Unresolved HIGH/CRITICAL incidents are breaker authority and survive reconstruction of every service object. Resolution is explicit; v1 does not auto-close incidents.

- Bounce: unique authoritative Step-1 members only; minimum sample 20; `bounce_rate > 5%` opens HIGH. Exactly 5.00% does not.
- Complaint: one authoritative terminal SPEC-027 `COMPLAINT` opens a HIGH campaign breaker, requires pause and human review, and never auto-resolves.
- Provider failure: three consecutive qualifying unresolved provider/reconciliation failures open HIGH. Normal `RATE_LIMITED`, send-window, and waiting states do not. Unknown external mutation truth remains reconciliation-first.
- Critical transport: authoritative send after STOPPED/FAILED, duplicate business send, or conflicting transport truth preserves SENT, opens CRITICAL, blocks future positive mutations, and invokes the critical safety downgrade without rewriting history.
- Conversion/retention degradation: thresholds are versioned and operator-owned; repository default is `UNCONFIGURED`, so no universal floor is invented.

Open breakers are enforced before `schedule_campaign`, positive provider CREATE/CONFIGURE/ADD_LEAD/ACTIVATE work, Step 2, and learning-plan application. Risk reduction and reconciliation remain available.

## Kill switch, READ ONLY, and autonomy downgrade

The safety controller writes only append-only Policy control revisions and can only reduce authority:

`ADAPTIVE_SCALE -> AUTONOMOUS_CAPPED -> ASSISTED -> SHADOW`.

Equivalent downgrade requests converge. Critical safety failures go directly to `SHADOW` with `kill_switch=true` and `read_only=true`, preserving prior controls and never broadening caps or allowlists. There is no automatic upgrade.

End-to-end tests prove kill switch/READ ONLY deny `schedule_campaign`, `reallocate_volume`, provider-positive operations, activation, and Step 2. Existing risk-reduction `pause_campaign` and read-only `generate_weekly_report` remain available through their current Policy profiles. If transport still reports a send, Kivou preserves the truth and records a CRITICAL incident.

## Retry, DLQ, and restart safety

Frozen component contracts remain authoritative for provider reconciliation, response leases/Email resolution, acquisition retries, conversion identity, and learning replay. `acquisition-retry-policy-v1` applies only where no prior contract exists: five attempts with 1, 2, 4, 8, and 16 minute delays. Exhaustion requires explicit requeue; unknown external mutation results return `RECONCILE_FIRST`.

The acquisition DLQ stores only bounded opaque work/scope/state references, attempts, times, a failure code, component, retry version, and lifecycle. It contains no arbitrary payload, provider body, response content, email, customer PII, or secret. Exhaustion is idempotent; restart preserves OPEN entries. Requeue accepts only `dead_letter_ref`, reconstructs through a typed handler, and rechecks breaker, kill/read-only state, staleness, Policy where applicable, and original idempotency. Resolution retains history.

Restart tests discard and reconstruct services against the same database across work claim, Policy decision, provider unknown outcome, response classification, conversion milestone, learning proposal, OPEN breaker, DLQ, and active emergency control paths. They prove replay convergence, durable breaker/DLQ state, no duplicate business outcome, and no blind provider retry.

## Internal access and environment separation

Read-only endpoints are limited to:

- `GET /internal/acquisition-ops/health`
- `GET /internal/acquisition-ops/readiness`
- `GET /internal/acquisition-ops/incidents`
- `GET /internal/acquisition-ops/dead-letters`

They reuse authenticated sessions plus the existing `KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS` allowlist. Its empty default denies everyone. Public health remains shallow. No mutation endpoint or customer UI was added.

`KIVOU_ACQUISITION_ENVIRONMENT` is explicit and closed to `UNCONFIGURED`, `STAGING`, or `PRODUCTION`; the default is `UNCONFIGURED`. Workers never infer production, Hermes receives no production secret, and no service/cron/systemd process is installed or started.

## Runbooks

Seven safe operator runbooks were added under `docs/runbooks/`:

1. `01-hermes-runtime-restart.md`
2. `02-kill-switch-and-read-only.md`
3. `03-circuit-breaker-incident.md`
4. `04-provider-reconciliation.md`
5. `05-dead-letter-recovery.md`
6. `06-vps-database-restart.md`
7. `07-staging-to-production-promotion.md`

They use tested repository entry points, contain no secrets or destructive SQL, prohibit safety bypasses, and require post-action verification and explicit reopening. No live service-manager configuration was added because the repository has no tested persistent Hermes command.

## Validation

Executable CI `32631262409` checked the PR merge context on executable SHA `ef263fd1551d994e1d774505fdf7ca3b5c6a0b5d`:

- backend: `4023 passed, 2 skipped`;
- skipped: exactly the two existing opt-in Stripe TEST smokes in `tests/test_billing_stripe_test_smoke.py`; no SPEC-031 skip;
- Ruff: PASS;
- frontend: `306 passed`;
- build, typecheck, lint: PASS;
- local `git diff --check`: PASS.

All tests are offline. No Hermes runtime, model, Apollo, Instantly, Stripe, provider, email, campaign activation, deployment, or production control/configuration was invoked or changed.

## Production-enablement boundary

SPEC-031 CODE READY does not mean PRODUCTION AUTONOMY READY. Repository defaults leave environment identity unconfigured, Hermes unobserved, shadow evidence insufficient, complete cost/provider/mailbox readiness absent, allocation envelope absent, and the highest safe mode at SHADOW. Production promotion requires a separate explicit deployment decision and real evidence; this PR does not enable it.
