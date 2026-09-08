# Acquisition provider SHADOW configuration on `kivou-staging`

Date: 2026-08-24
Status: approved conversational design; implementation has not started
Authoritative repository base: `2fe705c5c47bc70ad15c8b8d26cae45efc4fb7a1`
Target environment: `kivou-staging` only

## Objective

Configure Apollo, Instantly and the pinned Hermes supervisor on the staging VPS,
then prove their narrow Kivou integration in strict `SHADOW` mode.

The accepted proof is:

- Apollo authentication and acting-profile reads succeed without consuming a
  search or enrichment credit;
- the Instantly API V2 key is bound to the expected workspace and all three
  configured mailboxes normalize to `READY` through read-only calls;
- pinned Hermes invokes OpenRouter with
  `anthropic/claude-sonnet-4.6`, exposes zero executable tools and returns one
  valid advisory `SupervisorPlan`;
- Kivou remains `STAGING`, `SHADOW`, `READ ONLY`, kill-switched and at autonomous
  live volume zero throughout;
- no external or durable commercial mutation occurs.

This is configuration and connectivity validation, not activation of a live
acquisition runtime.

## Current verified state

The remote `main` SHA observed before this design was
`2fe705c5c47bc70ad15c8b8d26cae45efc4fb7a1`. The VPS was running a clean,
detached deployment at `19c5962bb9d1f96bcc87ca8876e7fb37f3cb42c4` through
`kivou-api.service`, under user/group `kivou`, from `/srv/kivou/app`, with
`/etc/kivou/staging.env` as its systemd environment file.

The deployed source already contains:

- the three bounded Apollo clients for organization search, contact discovery
  and company research;
- the Instantly V2 adapter, mailbox-readiness normalizer, campaign factory,
  provider-operation ledger, worker and webhook boundary;
- the Hermes adapter, bridge, strict contracts and pinned-runtime CLI;
- the Policy Gateway, acquisition event store and SPEC-031 fail-closed
  operational controls.

The missing last-mile wiring is material:

- no runtime configuration reads an Apollo API key or constructs the Apollo
  clients outside tests;
- no runtime configuration reads an Instantly sending API key, binds the three
  mailboxes or constructs `HttpInstantlyProvider`/`CampaignWorker` outside
  tests;
- only the Hermes CLI has a composition root, while the pinned Hermes runtime
  is absent from the VPS;
- no acquisition or Hermes systemd service exists;
- no Apollo, Instantly API, Hermes, OpenRouter or acquisition-environment
  variable name was present in `/etc/kivou/staging.env` at audit time.

Deploying existing code plus arbitrary keys would therefore not satisfy this
design.

## Scope

### Included

- a strict, one-shot acquisition-connectivity composition boundary;
- Apollo zero-credit authentication checks;
- Instantly current-workspace and three-mailbox readiness checks;
- installation of the exact Hermes pin in an isolated runtime;
- OpenRouter configuration with one exact model;
- Policy/environment preconditions and database non-mutation evidence;
- a manually invoked, disabled-by-default systemd `oneshot`;
- offline tests, an opt-in live staging smoke and an operator runbook;
- updates to `.env.example` that contain names and empty examples only.

### Excluded

- production configuration or deployment;
- Apollo organization, people or enrichment calls in the official smoke;
- Apollo credit consumption;
- Instantly campaign, lead, webhook or email mutation;
- Instantly `POST`, `PATCH` or `DELETE` requests;
- creation of a mailbox, campaign, lead, contact, sequence or webhook;
- campaign worker startup, scheduler, timer, queue or daemon;
- persistent Hermes gateway, API server, dashboard or messaging adapter;
- executable Hermes tools, shell access, MCP tools or autonomous repair;
- autonomous, adaptive or assisted live outbound;
- schema or Alembic changes;
- a customer-facing API or frontend change;
- secret storage in Git, logs, database rows, reports or plan output.

## Safety invariants

The one-shot must reject before provider I/O unless all of these are true:

1. `KIVOU_ACQUISITION_ENVIRONMENT` resolves exactly to `STAGING`.
2. The effective durable Policy control is unambiguous and current.
3. Its autonomy mode is exactly `SHADOW`.
4. `read_only` and `kill_switch` are both true.
5. The effective autonomous live volume cap is zero.
6. There is no unresolved positive-execution ambiguity that would make the
   operational snapshot untrustworthy.

The smoke does not activate the kill switch or append a Policy control itself.
The existing explicit operator command establishes that authority before the
smoke; the smoke only reads and validates it. This prevents a connectivity
command from silently changing control state.

Provider checks are diagnostics, not Kivou business actions. They receive no
opportunity, supplier, contact, email body, campaign arguments or Hermes
proposal. The official smoke has no path to a paid Apollo endpoint or an
Instantly mutation method.

## Architecture

### One-shot composition package

A focused `signals.acquisition_connectivity` package owns this deployment
boundary:

```text
src/signals/acquisition_connectivity/
  __init__.py
  __main__.py
  cli.py
  config.py
  contracts.py
  apollo.py
  instantly.py
  service.py
```

Responsibilities are intentionally split:

- `contracts.py` defines closed result states, bounded safe error categories,
  the versioned deployment document and exact mailbox bindings;
- `config.py` reads and strictly validates environment variables and the JSON
  deployment document without network or database access;
- `apollo.py` exposes only the two approved credential probes;
- `instantly.py` exposes only current-workspace and mailbox-readiness reads;
- `service.py` sequences the preflight, provider probes and Hermes invocation;
- `cli.py` emits one bounded summary and stable exit codes;
- `__main__.py` is the explicit operator entry point.

The package must not import `CampaignWorker`, `CampaignService`, Apollo
discovery services, response processing, webhook handlers or any outbound
executor. Existing business clients remain unchanged unless a narrowly shared
read-only response normalizer is required.

### Systemd boundary

`ops/systemd/kivou-acquisition-shadow-smoke.service` is a `Type=oneshot` unit
with:

- `User=kivou` and `Group=kivou`;
- `WorkingDirectory=/srv/kivou/app`;
- the existing `/etc/kivou/staging.env` for the database/control read boundary;
- `/etc/kivou/acquisition-shadow.env` for provider and Hermes settings;
- an `ExecStart` that invokes only
  `/srv/kivou/app/.venv/bin/python -m signals.acquisition_connectivity check`;
- no `[Install]` target, timer, restart loop or automatic startup;
- systemd filesystem hardening compatible with the existing Kivou and Hermes
  paths;
- no network listener.

Loading the existing application environment means the trusted Kivou one-shot
can read the same database authority as the API. The Hermes child remains
separately scrubbed by the existing subprocess transport and receives only its
dedicated `HOME`, `HERMES_HOME`, locale and Python runtime variables.

## Deployment configuration

### Root-owned environment file

`/etc/kivou/acquisition-shadow.env` is `0600 root:kivou` and contains exactly
the deployment variable names needed by the composition root:

```text
KIVOU_ACQUISITION_ENVIRONMENT=STAGING
KIVOU_ACQUISITION_SHADOW_CONFIG=/etc/kivou/acquisition-shadow.json
KIVOU_APOLLO_API_KEY=
KIVOU_INSTANTLY_API_KEY=
KIVOU_HERMES_PYTHON=/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python
KIVOU_HERMES_HOME=/var/lib/kivou/hermes-shadow
KIVOU_HERMES_CWD=/var/lib/kivou/hermes-shadow/work
```

Real values are never added to `.env.example`. Provider keys must be entered
directly on the VPS through a protected operator session, not pasted into chat,
shell history, a Git command, a process argument or a CI variable used by normal
tests.

### Versioned non-secret deployment document

`/etc/kivou/acquisition-shadow.json` is `0640 root:kivou`. It has a strict
closed schema:

```json
{
  "schema_version": "acquisition-shadow-connectivity-v1",
  "instantly_workspace_ref": "workspace-staging-stable-ref",
  "mailboxes": [
    {
      "mailbox_ref": "mailbox-staging-01",
      "provider_account_id": "provider-account-binding-1"
    },
    {
      "mailbox_ref": "mailbox-staging-02",
      "provider_account_id": "provider-account-binding-2"
    },
    {
      "mailbox_ref": "mailbox-staging-03",
      "provider_account_id": "provider-account-binding-3"
    }
  ]
}
```

The actual Instantly account lookup contract currently addresses accounts by
provider email. Those values remain protected deployment data and are never
printed; the example above is semantic, not a claim that opaque IDs can replace
emails on the wire.

Validation requires exactly three entries, unique stable mailbox refs, unique
provider account bindings, bounded strings, no unknown fields and an exact
schema version. This is not the production `MailboxCatalog`: entries gain no
country, language, wedge, cap or `enabled=true` authorization. The default
campaign catalog remains empty and unusable.

## Provider boundaries

### Apollo

The Apollo probe permits exactly:

```text
GET https://api.apollo.io/api/v1/auth/health
GET https://api.apollo.io/api/v1/users/api_profile
```

It sends the credential only as `x-api-key`, enforces the fixed HTTPS origin,
finite timeouts and a bounded response size, and retains only a boolean health
result plus an opaque acting-user fingerprint. It does not retain or print the
profile payload. Both endpoints are authentication/identity checks; the
official smoke calls no search or enrichment endpoint and consumes no search or
enrichment credit.

The existing Apollo Organization Search, People Search, People Enrichment and
Organization Enrichment clients are deliberately not composed into this
one-shot. `SHADOW` business services continue to short-circuit before Apollo.

### Instantly

The Instantly probe permits exactly:

```text
GET https://api.instantly.ai/api/v2/workspaces/current
GET https://api.instantly.ai/api/v2/accounts/{provider-account-email}
```

It sends the API V2 key only as `Authorization: Bearer ...`, uses the fixed
official base URL, finite timeouts and bounded response sizes, and validates
the returned workspace identity before any account lookup. A workspace mismatch
rejects the whole smoke.

Each configured account response is reduced by the existing strict normalizer
to `READY`, `TEMPORARILY_UNAVAILABLE`, `UNHEALTHY` or `UNKNOWN`. The overall
Instantly result passes only when all three distinct mailboxes are exactly
`READY`. Output contains stable `mailbox_ref` values, never full addresses or
raw account objects.

The probe type exposes no arbitrary method/path/body escape hatch. Architecture
tests reject `POST`, `PATCH` and `DELETE` literals and any import of the campaign
worker or mutation service in this package.

### Hermes and OpenRouter

Kivou retains its immutable Hermes pin:

```text
repository = https://github.com/NousResearch/hermes-agent.git
tag        = v2026.8.18
commit     = e624e9fde561e1add9388384012b295fde669ade
version    = 0.20.4
python     = >=3.11,<3.14
```

Installation uses the exact commit at:

```text
/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
```

Source and virtual environment are root-owned and immutable to the runtime
user. Mutable runtime state is isolated under:

```text
/var/lib/kivou/hermes-shadow
/var/lib/kivou/hermes-shadow/work
```

Both are owned by `kivou:kivou`; `HERMES_HOME` is `0700`. Its `.env` is `0600`
and contains only `OPENROUTER_API_KEY`. The exact non-secret model configuration
is:

```yaml
model:
  provider: openrouter
  default: anthropic/claude-sonnet-4.6
provider_routing:
  require_parameters: true
  data_collection: deny
```

No fallback model is configured in v1. A missing or unavailable exact model
fails closed instead of silently changing model semantics. No dashboard,
gateway, API server, messaging adapter, terminal backend, executable toolset,
delegation or autonomous memory authority is enabled.

The existing Kivou adapter remains the only invocation boundary. `health()`
must prove the exact tag/commit/version and `executable_tools=()`. `plan()`
receives one bounded `SupervisorContext` with `runtime_mode=SHADOW`, strict
command vocabulary, maximum output 2,048 tokens, maximum ten proposed actions,
30-second Kivou invocation timeout and a CHF 1 maximum cycle envelope. The
returned plan must pass Kivou's strict schema, version, budget and command
validation. The smoke prints only plan ID, action count, estimated cost,
review time and `status=advisory`; it does not persist raw output or reasoning.

Hermes configuration follows the upstream separation between non-secret
`config.yaml` and secret `.env`. The selected OpenRouter model has a context
window above Hermes' 64K minimum and supports structured outputs. Relevant
upstream references, verified on 2026-08-24:

- <https://hermes-agent.nousresearch.com/docs/user-guide/configuring-models>
- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/environment-variables.md>
- <https://openrouter.ai/anthropic/claude-4.6-sonnet-20260217>

## Execution flow

The `check` command performs these steps sequentially:

1. Parse configuration without logging values.
2. Read durable Policy and operational state.
3. Enforce every safety invariant before network access.
4. Snapshot bounded counts for acquisition campaigns, campaign members,
   provider operations and provider events.
5. Call Apollo credential health.
6. Read and fingerprint the Apollo acting profile.
7. Read and verify the current Instantly workspace.
8. Read and normalize the three configured Instantly mailboxes.
9. Check the isolated Hermes runtime identity and zero-tool boundary.
10. Invoke one real OpenRouter-backed advisory plan.
11. Re-read the four bounded database counts and require exact equality.
12. Emit one redacted summary and return success.

Failure stops the sequence immediately. A later provider is not contacted after
an earlier failure. The postcondition check still runs after any network stage
that was reached, so a local database mutation cannot be hidden by a later
provider error.

For example, a valid zero-action plan produces this bounded output shape. A
non-zero advisory action count remains valid only inside the existing maximum
of ten and does not become executable:

```text
acquisition_shadow environment=STAGING policy=SHADOW read_only=true kill_switch=true
apollo auth=READY acting_profile=BOUND
instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3
hermes state=AVAILABLE version=0.20.4 executable_tools=0 model=anthropic/claude-sonnet-4.6
shadow_plan status=advisory actions=0 estimated_cost=0.00
mutation_delta campaigns=0 members=0 provider_operations=0 provider_events=0
result=PASS
```

## Failure model

Configuration, transport and protocol failures map to a closed vocabulary such
as:

- `NOT_CONFIGURED`
- `WRONG_ENVIRONMENT`
- `POLICY_NOT_SHADOW`
- `READ_ONLY_REQUIRED`
- `KILL_SWITCH_REQUIRED`
- `AUTH`
- `PERMISSION`
- `PLAN_REQUIRED`
- `RATE_LIMITED`
- `TIMEOUT`
- `NETWORK`
- `SERVER_ERROR`
- `MALFORMED_RESPONSE`
- `WORKSPACE_MISMATCH`
- `MAILBOX_NOT_READY`
- `HERMES_VERSION_MISMATCH`
- `HERMES_TOOLS_EXPOSED`
- `HERMES_PLAN_INVALID`
- `LOCAL_MUTATION_DETECTED`

No automatic retry occurs within the one-shot. `Retry-After` may be reported as
a bounded duration for operator information, but the command does not sleep or
retry. Authentication, permission, plan and contract errors are never retried.
Timeouts and network failures remain failures rather than ambiguous success.

Exceptions and logs must not contain API keys, Authorization headers, raw
provider bodies, Apollo profile values, mailbox addresses, Hermes prompts,
model transcripts, hidden reasoning or full configuration documents.

## Testing

Normal tests remain offline and secret-free.

### Unit and contract tests

- strict parsing of complete configuration;
- every missing variable and missing file fails closed;
- wrong environment, unknown fields, wrong schema version and malformed JSON;
- exactly-three mailbox cardinality and uniqueness;
- Apollo exact URL/method/header, zero-credit endpoint allowlist, timeouts,
  response bounds and redaction;
- Instantly exact base URL, workspace binding, three GETs, all readiness states,
  partial failure and redaction;
- absence of arbitrary HTTP method/path/body APIs;
- Policy `SHADOW + READ ONLY + kill switch + cap zero` preflight;
- Hermes pin, zero tools, exact model, timeout, invalid JSON/schema, command and
  budget rejection;
- bounded CLI output and stable exit codes;
- unchanged before/after database counts on success and every failure stage.

### Architecture tests

- the new package cannot import campaign workers, outbound services, webhook
  mutation paths or Apollo discovery orchestration;
- no network call occurs at import or default ASGI construction;
- provider API keys are absent from `.env.example` values, fixtures, snapshots
  and reports;
- no `POST`, `PATCH` or `DELETE` request exists in the connectivity package;
- no systemd timer, restart loop, enablement target or public listener is added;
- default campaign deployment remains empty and non-executable.

### Verification before staging

- focused provider/supervisor/reliability tests;
- complete backend suite;
- Ruff and diff whitespace checks;
- frontend tests only if shared files outside this backend/ops scope change;
- GitHub Actions success on the exact executable SHA.

### Opt-in staging smoke

The real smoke is excluded from normal pytest and CI. It runs only through the
manual systemd one-shot after secrets are provisioned directly on the VPS. Its
evidence records the deployed SHA, environment, Policy control revision,
provider result categories, Hermes pin/model, zero-tool count and zero mutation
delta. It records no secret or raw provider payload.

## Deployment procedure

1. Implement on a dedicated branch from a freshly verified remote `main`.
2. Run offline verification and GitHub CI.
3. Merge only after explicit review; do not deploy a feature-branch SHA.
4. Confirm the merge SHA and current-main CI.
5. Deploy that exact main artifact to `kivou-staging` using the existing
   controlled release procedure.
6. Verify `kivou-api.service` and migration head `0021_reliability_operations`
   before secret provisioning.
7. Install the exact Hermes commit and verify its source hash/version.
8. Create protected configuration files without exposing their contents.
9. Establish or verify the explicit SHADOW/READ ONLY/kill-switch Policy control.
10. Install the disabled one-shot unit and run `systemctl daemon-reload`.
11. Run backend health/readiness, then manually start the one-shot.
12. Retain the bounded evidence and recheck `kivou-api.service`.

The service must never be enabled or scheduled during this phase.

## Rollback

On failure:

- stop the one-shot if still running;
- leave SHADOW, READ ONLY and the kill switch active;
- restore the previously approved Kivou application artifact;
- remove the unit from active systemd state or leave it disabled;
- retain audit/evidence rows and do not roll back the database;
- keep provider secrets protected for diagnosis or rotate them through each
  provider if exposure is suspected;
- do not downgrade Hermes, change the pin or substitute a fallback model.

No schema change is introduced, so rollback requires no database downgrade.

## Acceptance criteria

The design is delivered only when all of the following are evidenced against
the exact staging deployment SHA:

- configuration files have the specified ownership/modes and no secret appears
  in Git or logs;
- the effective environment and Policy controls satisfy every precondition;
- Apollo returns authenticated health and a bound acting profile through only
  the two permitted GET endpoints;
- Instantly returns the expected current workspace and all three mailboxes are
  exactly `READY`;
- Hermes reports version `0.20.4`, commit
  `e624e9fde561e1add9388384012b295fde669ade`, zero executable tools and exact
  model `anthropic/claude-sonnet-4.6`;
- one real advisory plan passes Kivou validation within the CHF 1 envelope;
- database mutation deltas are all zero;
- no campaign, lead, webhook, email or provider operation is created;
- `kivou-api.service` remains healthy before and after;
- the one-shot remains disabled and unscheduled.

Any unmet criterion yields `NOT_READY`; partial connectivity is reported by
component and never upgraded to overall success.
