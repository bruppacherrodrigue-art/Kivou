# Acquisition AirMail managed cadence readiness design

Date: 2026-08-26
Status: approved conversational design; written specification review pending
Authoritative repository base: `2a859158778f5070a74a3288f26694d84cae785a`
Target: `kivou-staging` Acquisition runtime only
Tracking issue: #83

## Objective

Allow the bounded QA Acquisition runtime to recognize the three configured
Instantly AirMail accounts as send-ready when Instantly deliberately omits
`sending_gap` and refuses to mutate that setting for managed AirMail accounts.

The change must preserve the existing fail-closed send-readiness gate. It does
not authorize a provider mutation, add a default cadence, relax readiness for
ordinary mailboxes, enable the Acquisition timer, or contact a prospect.

## Confirmed root cause

The staging accounts expose the following bounded, non-secret facts:

- `provider_code=8`;
- `is_managed_account=true`;
- active account and warmup states;
- completed setup, a positive daily limit and active tracking;
- no `sending_gap` property.

The official account update route rejects `sending_gap` changes for these
AirMail accounts. The strict Kivou send-readiness profile therefore returns
`UNKNOWN`, which correctly blocks both the runtime dependency probe and the
campaign path.

The current adapter also drops `provider_code` and `is_managed_account` from
its explicit response allowlist and converts an omitted allowed property into a
present `None` value. The runtime cannot currently prove either the managed
AirMail exception or the provider's omission.

## Selected design

### Protected per-mailbox cadence

Extend the existing closed `ShadowMailboxBinding` deployment contract with one
optional field:

```json
{
  "mailbox_ref": "mailbox-staging-01",
  "provider_account_id": "mailbox-one@example.com",
  "managed_airmail_sending_gap_minutes": 10
}
```

`managed_airmail_sending_gap_minutes` is an operator-owned strict positive
integer between 1 and 1,440 inclusive. Booleans and numeric strings are
rejected rather than coerced. The value is not a provider observation and is
never derived from an account name, domain, email address, previous response
or hard-coded runtime default.

The field remains optional for configuration compatibility. When it is absent,
the existing strict runtime behavior is unchanged and a missing provider gap
remains `UNKNOWN`. The schema version remains
`acquisition-shadow-connectivity-v1` because the addition is backward
compatible and fail-closed; the deployment sequence must install compatible
code before adding the new field to the protected staging document.

### Exact provider proof

The Instantly account adapter will add only `provider_code` and
`is_managed_account` to its explicit account allowlist. It will
retain only keys actually present in the provider response so the normalizer
can distinguish omission from an explicit null or malformed value. The raw
provider payload is neither logged nor persisted.

The configured cadence may replace a missing provider `sending_gap` only when
all of the following are true in the same fresh account response:

1. the strict send-readiness profile is active;
2. `provider_code` is exactly integer `8` and not a boolean;
3. `is_managed_account` is exactly `true`;
4. the `sending_gap` property is absent, not present with `null`;
5. the protected binding supplies an in-range cadence for that exact provider
   account;
6. every existing status, warmup, setup, daily-limit and tracking check passes.

If the provider supplies a valid `sending_gap`, that value remains
authoritative. When a protected AirMail cadence is also configured, the two
values must match; a mismatch returns `UNKNOWN` until the operator reconciles
the protected configuration. An explicit null, malformed value, missing
AirMail marker, non-AirMail account or unmanaged account also returns
`UNKNOWN`.

### One shared send-readiness path

`normalize_mailbox_readiness` remains the only fact normalizer.
`InstantlyMailboxReadinessSource` gains an optional, immutable per-account map
of managed AirMail cadences and keeps the existing `MailboxReadinessSource`
interface. Account identifiers are normalized only for an exact case-insensitive
configuration lookup and never leave the process.

The source rejects construction with both a cadence map and
`require_sending_gap=False`. This prevents a connectivity-only profile from
being confused with the strict send-readiness exception.

The Acquisition composition derives the map from the protected connectivity
document and passes the same strict source configuration to:

- `ProductionRuntimeDependencyProbe`, which controls truthful runtime
  readiness; and
- the existing `CampaignService` and `CampaignWorker` boundary, which
  revalidates readiness before scheduling and provider execution.

The manual connectivity smoke retains its existing explicit
`require_sending_gap=False` profile and receives no configured cadence map. It
continues to prove read-only connectivity only and cannot certify send
readiness.

The configured cadence is included in the existing deployment and per-mailbox
configuration fingerprints. The resulting normalized seconds are also already
covered by `MailboxReadiness.readiness_fingerprint`. A cadence change therefore
changes the auditable runtime identity and cannot silently reuse an old proof.

## Decision table

| Protected cadence | Provider classification | Provider gap | Strict result |
| --- | --- | --- | --- |
| absent | any | absent | `UNKNOWN` |
| absent | any | valid | existing provider-authoritative result |
| valid | AirMail code 8, managed | absent | use configured cadence |
| valid | AirMail code 8, managed | same valid value | use provider value |
| valid | AirMail code 8, managed | different valid value | `UNKNOWN` |
| valid | AirMail code 8, managed | null or malformed | `UNKNOWN` |
| valid | missing, non-AirMail or unmanaged | any value | `UNKNOWN` |
| invalid | any | any value | configuration rejected before provider I/O |

All other mailbox state transitions retain their existing meanings:
`UNHEALTHY`, `TEMPORARILY_UNAVAILABLE` and `UNKNOWN` are not promoted by this
change.

## Failure and safety behavior

- Invalid or out-of-range protected configuration fails as `NOT_CONFIGURED`
  before provider access.
- Missing or contradictory provider proof returns `UNKNOWN`; the runtime
  exposes the existing opaque `MAILBOX_DEPENDENCY_NOT_READY` reason.
- No `PATCH`, additional GET, retry, account mutation or provider-side default
  is introduced.
- No account identifier, provider response, API key or configured mailbox value
  is added to logs, database rows, CLI output or Git.
- No migration, API contract, frontend, SaaS entitlement, Signal Engine,
  Apollo, contact-discovery, personalization, compliance, Stripe, pricing or
  production behavior changes.
- The Acquisition timer remains disabled until the merged code, protected
  configuration and one controlled QA cycle satisfy issue #83.

## Test strategy

Implementation follows TDD. Tests must first fail against the current behavior
and then prove:

1. the deployment contract accepts 1, 10 and 1,440 minutes and rejects zero,
   booleans, numeric strings, values above 1,440 and unknown properties;
2. an existing v1 document without the optional field still loads while its
   strict missing-gap runtime result remains `UNKNOWN`;
3. the adapter retains only the two new bounded account facts and preserves
   actual key omission without leaking any other payload field;
4. a strict managed AirMail account with an omitted gap normalizes to `READY`
   with 600 seconds when configured for 10 minutes;
5. the same response remains `UNKNOWN` without protected configuration;
6. missing markers, non-AirMail, unmanaged, null, malformed and conflicting
   provider values remain `UNKNOWN`;
7. an exact valid provider gap remains authoritative;
8. a cadence can apply only to its exact case-insensitive account identity and
   can never cross to another configured account;
9. the ordinary default send-readiness profile is unchanged;
10. the manual connectivity opt-out remains the only
   `require_sending_gap=False` production caller;
11. combining that opt-out with a configured cadence map is rejected;
12. both the dependency probe and campaign composition receive the same strict
   configured source;
13. changing the configured cadence changes the deployment and mailbox
    configuration fingerprints;
14. no test performs a real network request or provider mutation;
15. targeted tests, the complete backend suite, Ruff and `git diff --check`
    pass on the final implementation HEAD.

## Staging rollout and rollback

After the implementation PR is green and merged:

1. deploy the exact approved `main` SHA while the Acquisition timer stays
   disabled;
2. preserve a root-only copy of the protected connectivity JSON;
3. atomically add the 10-minute value to the three verified AirMail bindings,
   preserving `root:kivou` ownership and mode `0640`;
4. run a read-only dependency check and require all mailbox facts to be fresh
   and `READY`;
5. continue with the already authorized bounded QA Acquisition proof only if
   readiness passes;
6. leave the runtime in SHADOW/QA mode with the kill switch available and no
   external campaign.

Rollback restores the protected JSON copy before switching to code that
predates this field. It then restores the prior immutable application release.
No database rollback is required because this design adds no migration or
durable schema.

## Definition of done for this correction

The correction is complete only when the implementation is merged, deployed on
staging, the protected three-mailbox cadence is installed, the strict runtime
dependency probe reports the AirMail accounts ready, the controlled QA cycle
passes without contacting a prospect, and issue #83's remaining independent
criteria are satisfied. This document alone does not close #83.
