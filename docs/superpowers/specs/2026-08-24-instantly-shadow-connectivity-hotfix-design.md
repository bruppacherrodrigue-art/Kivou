# Instantly SHADOW Connectivity Hotfix Design

## Objective

Make the manual STAGING SHADOW smoke recognize the three configured Instantly
mailboxes without weakening the send-readiness gate used by `CampaignWorker`.
The hotfix remains read-only and does not add a provider, worker, policy, store,
contract, scheduler, timer, or outbound execution path.

## Confirmed root cause

One bounded read-only diagnostic against each configured STAGING account
returned the same non-secret evidence:

- account status `1` (active);
- warmup status `1` (active);
- `setup_pending=false`;
- a positive daily limit;
- tracking status `CTD_ACTIVE`;
- no `sending_gap` property.

The current official Instantly OpenAPI `Account` schema exposes
`sending_gap` as an optional number and `tracking_domain_status` as a nullable
string without an enum. It documents `active` only as an example. The existing
Kivou normalizer requires an integer gap and recognizes several positive
tracking values, but not the real `CTD_ACTIVE` token. It therefore returns
`UNKNOWN` for all three accounts.

Official contract:
<https://api.instantly.ai/openapi/api_v2.json>

## Selected design

Keep `normalize_mailbox_readiness` and `InstantlyMailboxReadinessSource` as the
single normalization path. Add an explicit `require_sending_gap` option whose
default is `True`.

- The ordinary source and every `CampaignWorker` consumer retain the default.
  A missing gap therefore continues to produce `UNKNOWN` for anything that can
  schedule or execute outbound work.
- The acquisition connectivity composition alone constructs the existing
  source with `require_sending_gap=False`. This profile proves account
  connectivity, not send scheduling configuration.
- In that connectivity profile, a missing gap is represented by the existing
  bounded zero value in `MailboxReadiness`; the smoke neither persists nor
  consumes it as send configuration.
- The exact normalized token `ctd_active` joins the closed positive tracking
  vocabulary. Other unknown tokens remain `UNKNOWN`; negative tokens remain
  `UNHEALTHY`.
- `READY` still requires active account status, active warmup, completed setup,
  a strictly positive daily limit, and a recognized positive tracking status.

The option is deliberately unavailable through configuration or CLI flags.
It is fixed in the composition root, so an operator cannot use the smoke to
alter outbound readiness semantics.

## Data flow and failure behavior

The existing smoke sequence is unchanged: preflight policy and counters run
before provider access, then workspace identity and the three account GETs are
performed. Each account still passes through the existing source and
normalizer. Any missing positive evidence other than the OpenAPI-optional gap,
any unknown provider state, any transport error, or any non-zero local counter
delta fails closed with the existing error vocabulary.

No new request method or endpoint is introduced. The only Instantly account
operation remains `GET /api/v2/accounts/{email}`.

## Verification

Tests will prove:

1. The captured response shape (`CTD_ACTIVE`, missing gap) is `UNKNOWN` under
   the default send-readiness profile.
2. The same shape is `READY` only under the explicit connectivity profile.
3. Unknown, paused, unhealthy, zero-limit, setup-pending, and malformed states
   remain closed in both profiles.
4. The connectivity composition is the only production caller opting out of
   the gap requirement.
5. Instantly smoke requests remain bounded GETs with redacted output and no
   mutation path.
6. Targeted tests, Ruff, whitespace/diff checks, and the backend suite pass
   before delivery.

After deployment, the oneshot remains static and inactive. One manual smoke may
be run under the existing STAGING, SHADOW, read-only, kill-switch, and zero
volume controls. No campaign, lead, email, worker, scheduler, or timer is
started.
