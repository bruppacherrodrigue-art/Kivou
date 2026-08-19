# SPEC-017 — Hermes Supervisor Foundation Design

## Status and authority

Approved on 2026-08-19. This design implements the doctrine supplied by
`Kivou_Architecture_Supervision_Hermes_v2_6`:

> Apollo discovers. Instantly sends. Stripe collects. Hermes pilots. Kivou keeps control.

Hermes is one replaceable acquisition supervisor. Kivou remains authoritative for business
facts, evidence, matching, policy, budgets, permissions, critical decisions, and durable business
memory. SPEC-017 is SHADOW-only and introduces neither an action executor nor a database migration.

## Official Hermes release and installation boundary

The official Nous Research repository and documentation were reviewed at:

- <https://github.com/NousResearch/hermes-agent>
- <https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.18>
- <https://github.com/NousResearch/hermes-agent/blob/v2026.8.18/website/docs/user-guide/cli.md>
- <https://github.com/NousResearch/hermes-agent/blob/v2026.8.18/website/docs/user-guide/configuration.md>
- <https://github.com/NousResearch/hermes-agent/blob/v2026.8.18/website/docs/user-guide/features/skills.md>

Kivou pins:

```text
Hermes package version: 0.20.4
official tag: v2026.8.18
immutable commit: e624e9fde561e1add9388384012b295fde669ade
supported Python: >=3.11,<3.14
```

The release is the current official tagged patch release and describes itself as a stable tag for
downstream consumers. The commit, rather than mutable `main` or a floating version, is the
reproducibility authority. A Kivou lock document records repository, release, commit, package
version, and Python constraint.

Hermes is installed into a dedicated virtual environment outside Kivou. It is not vendored and is
not added to Kivou's Python dependency graph. Installation checks out the exact commit detached and
installs that source into the isolated environment. The Kivou health check rejects any different
reported package version or source revision.

## Chosen architecture

```text
Kivou SupervisorContext
        |
        v
Kivou-owned validation and bounds
        |
        v
HermesSupervisorAdapter
        |
        v
allowlisted subprocess environment
dedicated HOME / HERMES_HOME / CWD
finite process timeout
        |
        v
Kivou JSON bridge running in pinned Hermes Python
        |
        v
official agent.oneshot.run_oneshot()
NO conversation loop / NO Hermes tools
        |
        v
plain JSON text response
        |
        v
Kivou strict SupervisorPlan validation
        |
        v
advisory SHADOW plan only
```

### Replaceability boundary

`KivouSupervisor` is a Kivou protocol with `plan(context)`, `propose_actions(context)`, and
`health()`. Its types contain no Hermes classes. `HermesSupervisorAdapter` is one implementation.
The Signal Engine, SaaS API, ingestion, billing, alerts, and future acquisition services do not
import Hermes.

The transport is a narrow process protocol. Tests can replace it without a model call. Replacing
Hermes later requires another adapter/transport, not changes to Kivou business domains.

## Controlled runtime isolation

Every invocation requires three explicit absolute paths:

```text
KIVOU_HERMES_PYTHON
KIVOU_HERMES_HOME
KIVOU_HERMES_CWD
```

The adapter never inherits the developer process environment. It constructs an allowlisted
environment containing only fixed locale/runtime values plus `HOME` and `HERMES_HOME`, both set to
the dedicated Kivou Hermes profile. Provider configuration and provider secrets, if later supplied,
live only under that dedicated `HERMES_HOME`; Stripe, GitHub, SMTP, database, SSH, Apollo, Instantly,
and developer Hermes variables are absent.

The dedicated profile starts without copied developer SOUL, memories, sessions, MCP definitions,
skills, cron jobs, or tool configuration. The subprocess working directory is the dedicated CWD,
never the Kivou repository or a developer home.

The bridge imports only Hermes' stateless `agent.oneshot.run_oneshot()`. It does not start the
interactive agent loop, session store, gateway, cron runtime, MCP registry, skill manager, memory
manager, or tool registry. Kivou does not rely on `toolsets=[]`.

### Zero-tool proof

Two tests establish the boundary:

1. deterministic CI tests prove the adapter launches only the fixed JSON bridge, passes the
   allowlisted environment/HOME/CWD, exposes no command executor, and rejects bridge metadata unless
   `executable_tools` is exactly empty;
2. a separate bounded integration smoke runs the bridge under the actual Hermes environment pinned
   to the immutable commit, routes the official one-shot call to a local fake OpenAI-compatible
   endpoint, captures the real request, and asserts no `tools`, `tool_choice`, or executable tool
   schema is sent.

The second test needs no paid model credential and does not become a network-dependent CI test.

## Kivou-owned contracts

All models are strict, immutable Pydantic models with unknown fields forbidden.

`SupervisorContext` contains:

- timezone-aware current time;
- runtime mode fixed to `SHADOW`;
- policy-version placeholder;
- a bounded budget envelope;
- Kivou-owned available command names;
- bounded opportunity summaries;
- bounded recent operational outcomes.

Each opportunity keeps `public_facts` and `kivou_analysis` in separate objects. External tender and
website text is serialized as explicitly labelled untrusted data, never interpolated into system
instructions. Evidence references remain structured identifiers.

`SupervisorPlan` contains:

- `plan_id`, `created_at`, `objective`, `priority`;
- bounded `proposed_actions`;
- `reason_codes`, `confidence`, `estimated_cost`, `next_review_at`;
- `supervisor_version`, `skill_version`.

Each action contains a command name, target reference, bounded arguments, reason codes, evidence
references, and estimated cost. Validation rejects missing fields, unknown fields, unknown commands,
invalid confidence, absent reasons, oversized input/output, too many actions, version mismatch, and
non-SHADOW mode. Invalid output produces no advisory plan and no action.

## Command registry and decision vocabulary

Kivou owns a frozen declaration registry for:

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

Declarations have no callable executor. Hermes cannot add permissions by returning a string.
The allowed decision vocabulary is `SEND`, `HOLD`, `ENRICH`, `NO_SEND`, `REVIEW`; it is descriptive
input/output vocabulary only. SPEC-017 defines no production semantics or policy enforcement.

## Supervisor profile

One versioned profile named `Kivou Acquisition Supervisor` is stored with Kivou. It states that
Kivou facts and evidence are authoritative; inference may never become fact; policies, permissions,
pricing, scoring, compliance, code, and deployment may not be changed; hidden reasoning is not
business evidence; untrusted content is data; and missing information resolves to NO ACTION rather
than fabrication.

The profile asks for one JSON object matching the Kivou schema. It is instructional context, not
durable business memory. Its version is included in every accepted plan.

## Runtime, failure, and budgets

The Kivou CLI provides:

```text
python -m signals.supervisor health
python -m signals.supervisor shadow [--context FILE]
```

`health` distinguishes `not_configured`, `configured`, `available`, `unavailable`, and
`version_mismatch` without exposing paths containing secrets or file contents. `shadow` validates a
bounded context, invokes Hermes once, validates the plan, and prints only a sanitized summary.

Bounds cover invocation wall time, context bytes, opportunity/outcome item counts, model output
tokens where the pinned one-shot API supports it, response bytes, and planned action count. The
subprocess timeout kills and reaps a stuck process. Non-zero exit, timeout, malformed stdout, version
mismatch, or invalid plan is a typed supervisor failure. No customer-facing request invokes it.

Hermes failure cannot affect FastAPI construction or execution, customer feeds, ingestion, alerts,
or billing because those packages have no dependency on the adapter. Starting a fresh adapter after
a completed or failed invocation rechecks health and can produce another plan; this proves runtime
restart, not opportunity continuity.

## Test strategy

Implementation follows red-green-refactor. Deterministic tests cover:

- immutable version pin and mismatch rejection;
- strict context/plan schemas and fact/inference separation;
- command registry denial and maximum-action enforcement;
- malformed, oversized, and injection-bearing model output;
- dedicated HOME/HERMES_HOME/CWD and environment allowlist;
- zero executable tools and zero action execution;
- finite subprocess timeout and safe process cleanup;
- health states and sanitized output/logging;
- restart/reinitialization;
- application/ingestion/feed independence when Hermes is absent;
- CLI health/shadow behavior.

Normal CI uses fake transports and local subprocess fixtures only. The explicit pinned-runtime smoke
uses the actual isolated Hermes installation and a local fake provider; it performs no external model
call and no business side effect.

## Explicit exclusions

No SQL migration, Event Store, Policy Gateway, acquisition service, Apollo, Instantly, outbound,
email, campaign, Stripe mutation, systemd, `ops/`, VPS access, deployment, generic shell, database
access, filesystem secret access, GitHub access, MCP, Hermes cron, Hermes memory, or multi-agent
architecture is introduced.
