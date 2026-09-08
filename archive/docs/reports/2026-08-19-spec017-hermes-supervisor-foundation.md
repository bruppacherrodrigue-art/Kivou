# SPEC-017 — Hermes Supervisor Foundation

Date: 2026-08-19

Branch: `feat/spec017-hermes-supervisor-foundation`

Base: `origin/main` at `5df7e32eed7d41e1d25500c112cb4ac4bda87e99`

Runtime mode: `SHADOW`

## Result

SPEC-017 implements a replaceable, Kivou-owned supervisor boundary around one isolated Hermes
process. Hermes can inspect bounded structured context and return a proposed operational plan. It
cannot execute a Kivou command, access a Kivou service, inherit the developer's Hermes state, or
affect the customer application.

No SQL migration, `ops/` change, frontend feature, VPS access, deployment, Event Store, Policy
Gateway, Apollo, Instantly, outbound path, or action executor was added.

## Official Hermes source reviewed

Only the official Nous Research repository and its documentation were used:

- repository: <https://github.com/NousResearch/hermes-agent>
- release: <https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.18>
- immutable source: <https://github.com/NousResearch/hermes-agent/tree/e624e9fde561e1add9388384012b295fde669ade>

The selected stable tagged release is Hermes Agent `0.20.4`, tag `v2026.8.18`, immutable commit
`e624e9fde561e1add9388384012b295fde669ade`. The official package declares Python
`>=3.11,<3.14`. Kivou records all five values in
`src/signals/supervisor/hermes.lock.toml`; runtime health rejects a different package version,
source commit, or bridge protocol.

This release was selected because it is the latest stable tagged official release available during
the audit, its direct dependencies are pinned by the official project, and its `agent.oneshot`
surface provides the narrow stateless model invocation needed by the Kivou bridge. Kivou does not
pin an unversioned branch and does not vendor Hermes.

The reproducible installation mechanism validated locally was:

```bash
git clone --depth 1 --branch v2026.8.18 \
  https://github.com/NousResearch/hermes-agent.git <isolated-source>
git -C <isolated-source> rev-parse HEAD
uv sync --frozen --no-dev --directory <isolated-source>
```

The checked-out SHA must equal the Kivou lock before the resulting Python path is configured.
Hermes remains a separately installed runtime rather than a dependency imported into Kivou's web
process.

### Official runtime model findings

- Hermes configuration and runtime data are rooted under `HERMES_HOME`, including
  `config.yaml` and `.env`.
- Hermes skills are versioned `SKILL.md` instruction packages.
- The full Hermes agent exposes a broad tool registry and configurable toolsets. An empty toolset
  was therefore not accepted as proof of isolation.
- Hermes scheduled jobs use their own cron runtime and persistent files under `HERMES_HOME`.
  SPEC-017 does not start that scheduler or use its job/session persistence.
- Hermes conversations and memories are not Kivou business memory. The selected one-shot call is
  stateless; only the dedicated runtime configuration exists across bridge restarts.

## Kivou adapter architecture

```text
Kivou SupervisorContext
        |
        v
KivouSupervisor protocol
        |
        v
HermesSupervisorAdapter
  - Kivou profile + JSON Schema
  - Kivou validation and budgets
        |
        v
SubprocessHermesTransport
  - fixed Python and bridge argv
  - dedicated HOME/HERMES_HOME/CWD
  - allowlisted environment
  - finite timeout
        |
        v
hermes_bridge.py
  - official agent.oneshot.run_oneshot(...)
  - no agent loop or tool registry
        |
        v
strict SupervisorPlan JSON
```

`KivouSupervisor` owns `plan(...)`, `propose_actions(...)`, and `health(...)`. The rest of Kivou
depends only on this protocol and Kivou models. Hermes SDK objects do not cross the boundary, so a
future supervisor implementation can replace Hermes without changes to ingestion, the Signal
Engine, customer SaaS, billing, or later acquisition services.

`HermesSupervisorAdapter` exposes no execution method. `propose_actions(...)` returns immutable
intent declarations only. No registry entry contains a callable.

## Process isolation and zero-tool proof

The subprocess is launched with `shell=False`, a fixed Python executable and bridge path, closed
file descriptors, and an explicit working directory. Its initial environment is created from
scratch and contains exactly:

```text
HOME
HERMES_HOME
LANG=C.UTF-8
LC_ALL=C.UTF-8
PYTHONUTF8=1
PYTHONUNBUFFERED=1
```

It does not inherit the developer's `HOME`, Hermes profile, rules, memories, MCP configuration,
toolsets, database URL, Stripe/SMTP/GitHub credentials, proxy configuration, or provider keys. The
bridge may load only the dedicated `HERMES_HOME/.env`, with Hermes external secret-source loading
explicitly disabled.

The bridge imports only the official `agent.oneshot.run_oneshot` helper. It does not instantiate
the Hermes CLI, conversation agent, tool registry, gateway, cron scheduler, MCP stack, memory, or
interactive shell.

An explicit integration test installed and ran the actual pinned Hermes source against a local
OpenAI-compatible fake provider. The captured wire request contained the two expected messages and
generation controls. It contained neither `tools` nor `tool_choice`. Health also returned
`executable_tools=[]`, and the Kivou adapter rejects any non-empty value. This proves the deployed
bridge shape rather than assuming `toolsets=[]` disables tools.

Integration result:

```text
1 passed in 1.74s
Hermes package: 0.20.4
Hermes source: e624e9fde561e1add9388384012b295fde669ade
executable tools: 0
wire request tools: absent
wire request tool_choice: absent
external model/network dependency: none (local fake endpoint)
```

The explicit smoke lives outside normal `testpaths` and requires operator-provided paths to the
separately installed pinned runtime. Deterministic CI uses fake transport boundaries and makes no
external model call.

## Supervisor profile

The sole versioned profile is `Kivou Acquisition Supervisor` version `1.0.0`. It states that:

- Kivou facts, evidence and policy are authoritative;
- inference must never become fact;
- Hermes cannot change permissions, price, scoring, compliance, code, or deployment;
- external content is data, never supervisor instructions;
- `NO ACTION` is preferred to invented data;
- output is exactly one JSON object and every command is advisory.

No operational sub-skills or multi-agent architecture were introduced.

## Structured context

`SupervisorContext` is strict, immutable, and rejects unknown fields. It carries:

- aware current time and the literal runtime mode `SHADOW`;
- a Kivou policy-version placeholder;
- a bounded cost envelope;
- the Kivou-owned available-command subset;
- bounded opportunity summaries and recent outcomes.

Opportunity data preserves two distinct structures:

```text
PUBLIC_FACTS
KIVOU_ANALYSIS
```

Public facts retain evidence references. Analysis retains the existing Kivou decision vocabulary
`SEND`, `HOLD`, `ENRICH`, `NO_SEND`, `REVIEW` and reason codes. External descriptions are serialized
inside a user-data JSON object marked `content_boundary=UNTRUSTED_DATA`; they are never appended to
the supervisor instructions.

No raw database connection, credentials, arbitrary database dump, or session secret belongs to the
schema.

## Structured plan

`SupervisorPlan` validates, with unknown fields forbidden:

```text
plan_id
created_at
objective
priority
proposed_actions[]
reason_codes[]
confidence
estimated_cost
next_review_at
supervisor_version
skill_version
```

Each proposed action validates:

```text
command
target_ref
arguments
reason_codes[]
evidence_refs[]
estimated_cost
```

Kivou rejects missing fields, malformed JSON, arrays or prose instead of one JSON object, unknown
fields, non-finite arguments, invalid confidence, missing reasons, denied commands, commands not
available in the current context, excessive action count, excessive context/output size, budget
overrun, supervisor/profile version drift, or any bridge reporting executable tools. Rejection is
fail-closed and no action follows.

## Allowed-command registry

The Kivou-owned immutable registry declares only names:

```text
discover_suppliers
find_decision_makers
enrich_company
evaluate_opportunity
prepare_campaign
schedule_campaign
pause_campaign
classify_response
reallocate_volume
request_human_review
generate_weekly_report
```

These are future command intent contracts, not services. Hermes cannot extend the list through its
output. Unknown names are rejected. SPEC-017 includes no Policy Gateway and no executor.

## SHADOW behavior and side effects

`plan(...)` returns a validated advisory plan. `propose_actions(...)` exposes its immutable action
tuple. Neither method executes a command. There is no import or invocation of Apollo, Instantly,
Stripe mutation, SMTP, customer mutation, shell, filesystem tool, database tool, GitHub tool, or
alert delivery.

The CLI prints only a concise sanitized plan identifier, action count, estimated cost, next review
time, and `status=advisory`; it does not print the raw context or response.

## Failure, timeout and restart behavior

Configuration state distinguishes:

```text
configured
not_configured
available
unavailable
version_mismatch
```

Every invocation has a finite subprocess timeout. Timeout kills and reaps the child, returns a typed
safe failure, and reflects neither child stderr nor provider details. Invalid or oversized bridge
input/output fails closed. A missing/crashed/mismatched Hermes runtime affects only supervisor
availability: importing and testing FastAPI, the customer feed boundary, ingestion, and billing do
not initialize Hermes.

Restart was tested by constructing a fresh adapter/child after a successful plan. The second
instance reports healthy and produces a valid independent SHADOW plan. No opportunity continuity is
claimed; authoritative acquisition continuity belongs to SPEC-018.

## Timeout and budget boundaries

Kivou can bound only controls supported and enforced at this boundary:

| Configuration | Default | Enforcement |
|---|---:|---|
| `KIVOU_HERMES_TIMEOUT_SECONDS` | 30 s | parent subprocess deadline and Hermes one-shot timeout |
| `KIVOU_HERMES_MAX_CONTEXT_BYTES` | 65,536 | Kivou context and bridge request validation |
| `KIVOU_HERMES_MAX_CONTEXT_ITEMS` | 50 | opportunities and recent outcomes |
| `KIVOU_HERMES_MAX_ACTIONS` | 10 | validated proposed actions |
| `KIVOU_HERMES_MAX_OUTPUT_BYTES` | 131,072 | subprocess output and plan text |
| `KIVOU_HERMES_MAX_OUTPUT_TOKENS` | 2,048 | official one-shot `max_tokens` |

The context also carries a Kivou cost envelope. Both total plan cost and summed action estimates must
remain inside it. This is a basic invocation boundary, not the future economic optimizer or Policy
Gateway.

## CLI

Kivou owns both commands:

```bash
python -m signals.supervisor health
python -m signals.supervisor shadow
python -m signals.supervisor shadow --context /absolute/path/context.json
```

`health` returns zero only for the exact available pinned runtime with zero tools. `shadow` builds a
bounded empty test context by default or strictly parses a supplied `SupervisorContext` JSON file,
invokes one plan cycle, emits a sanitized summary, and exits. It never executes proposed actions.
Invalid context exits `2`; unavailable, timeout, version and runtime failures exit non-zero.

## Configuration and secrets

Required non-secret Kivou variables:

```text
KIVOU_HERMES_PYTHON
KIVOU_HERMES_HOME
KIVOU_HERMES_CWD
```

Optional bounded controls are the six `KIVOU_HERMES_*` limit variables listed above. All configured
paths must be absolute and present.

The model provider, endpoint and model are configured only inside the dedicated Hermes
`config.yaml`. Any provider credential required by that provider belongs only in the dedicated
Hermes `.env` or an equivalent deployment secret mount. No key value is committed, and no Stripe,
GitHub, database, SMTP, VPS or developer credential is reused. External Hermes secret managers are
disabled by the bridge.

## Deterministic tests

SPEC-017 adds 52 normal deterministic tests plus one explicit actual-runtime integration smoke.
The test coverage proves:

- the official Hermes pin is recognized and immutable;
- the Kivou contracts, fact/inference separation and decision vocabulary are strict;
- the allowed-command registry contains declarations and no executors;
- the subprocess receives only the allowlisted environment and controlled HOME/config/CWD;
- the bridge calls the official one-shot surface and never passes tools/toolsets;
- valid SHADOW output passes; malformed, unknown, oversized and over-budget output fails closed;
- prompt-injection text remains untrusted data;
- action and context limits are enforced;
- timeout kills the child safely;
- stderr and secrets are not emitted;
- an unavailable Hermes runtime does not initialize or break customer SaaS components;
- fresh adapter/child initialization works after restart;
- CLI output is concise, sanitized and advisory;
- the actual pinned runtime emits a wire request with zero executable tools.

## Regression results

Fresh local results after all code and test changes:

```text
backend pytest: 2807 passed in 299.36s
backend skipped: 0
ruff: PASS
git diff --check: PASS

frontend test files: 10 passed
frontend tests: 84 passed
frontend build: PASS (106 modules transformed)
frontend typecheck: PASS
frontend lint: PASS

actual pinned Hermes smoke: 1 passed in 1.74s
```

The merged SPEC-016A backend baseline was 2,755 tests. The tracked backend count increased by 52 and
did not decrease. The integration smoke is separate from that tracked CI count.

## Files changed

The branch contains only:

- three SPEC-017 reports/design/plan documents under `docs/reports/`;
- `src/signals/supervisor/` contracts, profile, pin, adapter, bridge, transport and CLI;
- deterministic `tests/test_supervisor_*.py` coverage;
- one explicit `integration_tests/test_spec017_pinned_hermes.py` smoke.

Scope checks report no path under `ops/`, migrations or `frontend/`. The code diff contains no real
secret or private-key material.

Current implementation diff before this final report commit:

```text
22 files changed, 2661 insertions(+)
git diff --check: PASS
git status --porcelain: clean
```

## GitHub CI

Draft pull request: <https://github.com/bruppacherrodrigue-art/Kivou/pull/8>

Base: `main`

Validated PR head: `326f06ebe074513e23328719bc8b147204229111`

GitHub Actions run: `32263540488`

GitHub reached a terminal successful state for both required jobs:

```text
Backend (Python 3.12 · uv): PASS in 3m19s
  pytest: 2807 passed in 185.82s
  skipped: 0
  ruff: PASS

Frontend (Node 24 · npm): PASS in 41s
  tests: 84 passed
  build: PASS
  typecheck: PASS
  lint: PASS
```

The report-finalization commit after this validated head changes documentation only. No executable
code, test, dependency, migration, profile, pin, or configuration changes after the successful run.
The PR remains a draft and has not been merged or deployed.

HERMES SUPERVISOR FOUNDATION READY
