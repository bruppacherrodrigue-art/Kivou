# SPEC-031 — Reliability & Autonomous Operations — design

Status: frozen implementation design
Base: `af2f0122c13d906d5af077e4c620eada7c4db0bc`
Version: `acquisition-operations-v1`

## Scope and non-goals

SPEC-031 makes the existing acquisition engine restart-safe and measurably safe. It adds acquisition-specific incidents/circuit breakers, a bounded dead-letter queue, deterministic health and H-A…H-G readiness evaluation, monotonic autonomy downgrade, internal operational reads, and operator runbooks. It does not enable autonomous outbound, start Hermes, add provider traffic, deploy schedulers, create an SRE framework, or change acquisition business truth.

Production promotion remains a separate operator/deployment decision. A green SPEC-031 implementation means **code ready**, never **production autonomy ready**.

## Current-runtime audit

The merged repository already provides the authorities that SPEC-031 must preserve:

- Hermes is pinned locally by `src/signals/supervisor/hermes.lock.toml` to repository `https://github.com/NousResearch/hermes-agent.git`, tag `v2026.8.18`, commit `e624e9fde561e1add9388384012b295fde669ade`, release `0.20.4`, Python `>=3.11,<3.14`. Runtime verification is local/configured only; no download or GitHub lookup occurs.
- Supervisor commands are closed by `ALLOWED_COMMANDS`; the Hermes bridge exposes bounded Kivou commands and no self-update surface. There is no valid long-running supervisor CLI today, so SPEC-031 will not invent a systemd unit.
- Policy controls are append-only revisions carrying autonomy mode, kill switch, read-only, command allowlists, country/language/wedge bounds, daily cost, and daily volume caps. Policy evaluations are durable.
- `schedule_campaign` and `reallocate_volume` are commercial mutations. `pause_campaign` is risk reduction and `generate_weekly_report` is read-only. Existing Policy behavior correctly keeps risk reduction and safe observation available under emergency controls.
- Campaign mutations revalidate control state immediately before CREATE/CONFIGURE/ADD_LEAD/ACTIVATE and before Step 2. Unknown remote mutations enter `RECONCILE_REQUIRED`; they are not blindly retried. Campaign/provider operation attempts remain governed by their frozen SPEC-026 rules.
- Response evaluation leases, Email resolution attempts, conversion event identities, learning selection/application identities, and acquisition Opportunity event streams are durable and replay-safe. SPEC-031 does not replace their component-specific retry contracts.
- SPEC-030 internal access is authenticated and backed by the configured `KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS` allowlist, whose default is empty. Operational reads reuse this authority.

## Hermes runtime identity and no self-upgrade

`HermesRuntimeIdentity` contains exactly repository, tag, commit, version, and Python contract. The expected identity comes from the committed lock. The observed identity is injected from the local runtime/configuration. Any absent or unequal field makes H-A `NOT_READY`. Verification never contacts the network and Hermes cannot change the expected or observed identity, dependencies, skills, Policy, or environment configuration.

Promotion remains proposal → tests → historical evaluation → shadow → explicit approval → deployment. There is no automatic upgrade path.

## Health and readiness are separate

`AcquisitionOperationalHealth` is an observation at an injected timezone-aware instant. Its components are API, database, Hermes runtime, supervisor loop, Policy control, campaign execution, DLQ, and circuit breakers. Component and aggregate status use only `READY`, `DEGRADED`, and `NOT_READY`. Reasons are closed bounded codes; exception text, secrets, and PII are excluded.

`AutonomousReadiness` evaluates H-A…H-G separately using `READY`, `NOT_READY`, or `INSUFFICIENT_EVIDENCE`, with bounded evidence references and blockers. It reports a highest safe mode from SHADOW, ASSISTED, AUTONOMOUS_CAPPED, or ADAPTIVE_SCALE, but never mutates Policy. Missing evidence never becomes READY.

- **H-A Runtime:** exact pinned identity, compatible Python, fresh supervisor heartbeat, and explicit environment identity.
- **H-B State:** durable Opportunity/campaign/provider/response/conversion/learning identities plus restart/replay validation evidence.
- **H-C Policy:** every allowed command has registered metadata and mapper validation; executable paths have durable Policy audit and no alternate positive-mutation bypass.
- **H-D Shadow:** durable shadow decisions, human-review truth, comparisons, and later outcome references. The current repository lacks a durable human-review verdict, so the repository default is `INSUFFICIENT_EVIDENCE`; no agreement is invented.
- **H-E Capped:** H-A/B/C ready, tested kill switch/read-only, configured breakers/budgets/allowlists/mailboxes/provider prerequisites, healthy delivery evidence, conversion and retention evidence, and no open critical incident. Missing production facts are `NOT_READY` or `INSUFFICIENT_EVIDENCE`.
- **H-F Closed loop:** structural joinability from sent campaign member/opportunity through optional response, click, journey, activation, payment, MRR, retention, and churn. Absence of a downstream outcome is valid; orphaned facts are not.
- **H-G Scale:** the sole allocation mutation remains `reallocate_volume`, requiring a durable SPEC-029 proposal, conversion/retention evidence, Policy APPROVED, ADAPTIVE_SCALE, a compatible allocation baseline, and no relevant open breaker. It cannot increase global volume.

Default environment identity is `UNCONFIGURED`, no production mailbox/cost/breaker deployment evidence is assumed, and the observed Hermes runtime is unconfigured. Default highest safe mode is SHADOW. Automatic changes are downgrade-only.

## Circuit breaker contract

Version: `acquisition-circuit-breaker-v1`.

Scopes are `GLOBAL`, `COUNTRY`, `WEDGE`, `CAMPAIGN`, and `MAILBOX`. Durable states are `OPEN`, `ACKNOWLEDGED`, and `RESOLVED`. Incident severities are `WARNING`, `HIGH`, and `CRITICAL`; only unresolved HIGH/CRITICAL incidents block execution. Breaker authority is the unresolved incident row, so process restart cannot close it.

Trigger types are closed to `BOUNCE_RATE`, `COMPLAINT`, `COMPLIANCE_FAILURE`, `PROVIDER_FAILURE`, `UNEXPECTED_TRANSPORT_TRUTH`, `BUDGET_BREACH`, `COST_DRIFT`, `CONVERSION_DEGRADATION`, `RETENTION_DEGRADATION`, and `MAILBOX_UNAVAILABLE`. Provider AI labels and Hermes metrics are never sources.

The trigger identity is a domain-separated fingerprint of incident version, trigger type, scope, authoritative source refs/window, and metric version. Re-observation converges to the original row. Resolution is explicit; v1 has no time-based auto-close or half-open state.

### Frozen triggers

- **Complaint:** one finalized authoritative SPEC-027 `COMPLAINT` opens a HIGH campaign breaker, marks pause and human review required, and blocks future positive execution. It never auto-resolves.
- **Bounce:** use unique authoritative Step-1-sent campaign members and authoritative Step-1 bounces. Sample must be at least 20. Open HIGH when `bounce_count / sent_count > 0.05`; exactly 5.00% does not open. Step 2 is excluded.
- **Provider failure:** three consecutive unresolved qualifying mutation/reconciliation failures in the same campaign or mailbox scope open HIGH. Terminal failures and unresolved reconciliation-required mutations count; `RATE_LIMITED`, send-window waiting, and proven absence waiting do not. Unknown external outcome remains reconciliation-first and is never converted into a blind retry.
- **Critical transport:** authoritative send after STOPPED/FAILED, duplicate business send, or transport truth conflicting with Kivou safety state opens CRITICAL, preserves SENT truth, blocks future positive mutations, requires review, and triggers critical downgrade. History is never rewritten.
- **Budget/compliance:** authoritative hard-cap bypass or critical compliance failure is CRITICAL. Ordinary `BUDGET_EXCEEDED` remains a Policy hard stop and does not create a second budget ledger.
- **Cost/conversion/retention:** thresholds are an injected, versioned operator contract. Repository default is UNCONFIGURED, so these automatic breakers and their readiness evidence remain unavailable. Missing costs are never zero and no FX/economic formula is invented.

An OPEN/ACKNOWLEDGED HIGH or CRITICAL incident blocks new `schedule_campaign`, CREATE/CONFIGURE/ADD_LEAD/ACTIVATE, Step 2, and relevant learning application through repository guards. Active campaigns are pause-required. Risk reduction and reconciliation remain possible. `pause_campaign` is reused; no replacement command is added.

## Safety controller and autonomy downgrade

Kivou's safety controller, never Hermes, may append a Policy control revision that only reduces authority:

`ADAPTIVE_SCALE → AUTONOMOUS_CAPPED → ASSISTED → SHADOW`, with SHADOW stable. Critical unexpected transport, compliance failure, kill-switch-integrity failure, or budget hard-cap bypass goes directly to SHADOW and sets `kill_switch=true` plus `read_only=true`. Existing allowlists and caps are copied, not broadened. Equivalent requests converge when controls are already at or below the requested safety level; prior revisions remain immutable.

There is no automatic autonomy increase. Readiness output cannot change controls.

## Kill switch and READ ONLY

Activation uses the existing append-only Policy control path. Kill switch plus READ ONLY denies `schedule_campaign`, `reallocate_volume`, provider positive operations, activation, and Step 2. Campaigns become pause-required through breaker/safety observation. `pause_campaign`, reconciliation, incident inspection, and `generate_weekly_report` remain available according to existing risk-reduction/read-only profiles.

The live provider guards, not the control boolean alone, are the enforcement point. If transport still reports a send, Kivou preserves SENT, records a CRITICAL incident, and does not reverse acquisition state.

## Retry contract

Existing retry contracts remain authoritative: SPEC-026 reconciliation, response leases and three Email resolution attempts, acquisition retries, conversion identities, and learning replay are unchanged.

For bounded operational work without a frozen contract, `acquisition-retry-policy-v1` permits at most five attempts with backoff 1, 2, 4, 8, and 16 minutes. Exhaustion requires explicit requeue. Any unknown external mutation result returns `RECONCILE_FIRST`, never an ordinary retry.

## Dead-letter queue

The acquisition DLQ is a durable bounded reference index, not a payload bus. Work types are closed to workflows that exist on main: `SUPERVISOR_CYCLE`, `SUPPLIER_DISCOVERY`, `CONTACT_DISCOVERY`, `COMPANY_RESEARCH`, `CAMPAIGN_PROVIDER_OPERATION`, `RESPONSE_RESOLUTION`, `CONVERSION_RECONCILIATION`, and `LEARNING_CYCLE`.

An exhausted/terminal work identity produces one `acquisition_dead_letter` row. It stores only opaque work/scope/source refs, attempt/timestamps, bounded failure code, retry version, component, and status (`OPEN`, `REQUEUED`, `RESOLVED`). It stores no work payload, provider body, response content, address, secret, or PII.

Requeue is explicit by `dead_letter_ref`. Kivou reconstructs work from durable refs through a typed component handler. Before dispatch it rechecks present breaker, kill switch/read-only, staleness, Policy where applicable, and the original component idempotency contract. Missing handler or uncertain provider mutation fails closed. History is retained after replay and resolution.

## Persistence

Migration `0021_reliability_operations`, down revision `0020_hermes_learning_loop`, creates exactly two tables:

1. `acquisition_operational_incident`: immutable trigger identity plus bounded mutable acknowledgement/resolution lifecycle, breaker scope/severity, safe metric values, Policy control before/after refs, and pause/review requirements.
2. `acquisition_dead_letter`: immutable exhaustion identity plus bounded requeue/resolution lifecycle and durable work references.

No heartbeat, breaker, retry, runbook, or health-history table is added. State machine `acquisition-state-v1` and acquisition `EventType` remain unchanged.

## Restart/replay semantics

Correctness never depends on a Python object. Tests discard services/workers and rebuild them against the same database for unclaimed/claimed work, post-Policy state, provider unknown outcome, response lease, conversion milestone, learning proposal, OPEN incident, DLQ row, and active kill switch. Existing component identities prevent duplicate outcomes; unknown provider mutations reconcile first. An incident or dead letter cannot disappear on API, worker, Hermes, database-client, or VPS process restart.

## Internal access and environment separation

Detailed health, readiness, incidents, and dead letters are read-only internal endpoints under `/internal/acquisition-ops/*`. They reuse authenticated sessions plus `KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS`; the empty default denies everyone. Public health remains shallow and exposes no runtime identity, database detail, Policy revision, breaker reason, DLQ count, or provider configuration.

Deployment evidence contains an explicit environment identity (`UNCONFIGURED`, `STAGING`, or `PRODUCTION`). Workers never infer production. The default is UNCONFIGURED. No generic administrator token or Hermes-visible production secret is introduced.

## Runbooks and scheduled operations

Seven runbooks cover Hermes restart, kill switch/read-only, breaker incidents, provider reconciliation, DLQ recovery, VPS/database restart, and staging-to-production promotion. They use only checked repository interfaces, avoid destructive SQL and embedded secrets, and require verification/rollback. Since main has no tested persistent supervisor command, no systemd unit or cron is invented or activated.

## Boundaries

SPEC-031 adds no customer UI, customer reply, dashboard, allocation algorithm, acquisition state, EventType, provider adapter, or live scheduling. It does not deploy, configure mailboxes, enable ADAPTIVE_SCALE/AUTONOMOUS_CAPPED, increase caps, start Hermes, or contact any external service.
