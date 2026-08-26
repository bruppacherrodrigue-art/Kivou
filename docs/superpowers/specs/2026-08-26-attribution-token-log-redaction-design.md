# Sensitive link token log redaction

Status: approved core design; reset-link scope review pending

Date: 2026-08-26

Scope: staging audit blocker #84 and reset-link follow-up #93

## Problem

The public attribution endpoint deliberately carries an opaque bearer token in
`GET /a/{token}`. Nginx and uvicorn currently write the complete request target
to their access logs. A valid attribution token would therefore be copied into
both `/var/log/nginx/access.log` and the `kivou-api` journal before FastAPI can
validate it.

The password-reset link carries its opaque bearer token in
`GET /reset-password?token=...`. This frontend route currently inherits nginx's
combined access format, so its first real use would copy the token into the
nginx access log. A counter-only staging audit found zero current reset-token
targets in nginx and uvicorn logs: this is a confirmed latent defect, not an
existing disclosed value.

The nginx route itself is correct: it reaches FastAPI, invalid tokens return the
application JSON 404, and the SPA fallback is not involved. The missing
boundary is log minimization. A valid 303/cookie staging proof and any further
real reset proof must not run until that boundary is deployed and verified.

## Decision

Redact attribution request targets at both logging layers and reset-link query
targets at nginx. Keep normal access logging for every other route.

### Nginx

Define two dedicated log formats in the versioned HTTP-level nginx fragment.
For attribution and reset-link requests they may record only operational fields
that cannot contain the raw target:

- remote address;
- timestamp;
- request method;
- the literal path `/a/[redacted]` or
  `/reset-password?token=[redacted]`, selected by the exact location;
- HTTP protocol;
- response status;
- response size and duration.

The format must not reference `$request`, `$request_uri`, `$uri`, `$args`, a
referer, or any request header. The exact `location ^~ /a/` and
`location = /reset-password` each use their own fixed format in the existing
nginx access log.

Nginx error messages cannot be given a custom format and can include the raw
request when rate limiting or an upstream failure occurs. The attribution
locations therefore send their own error logs to `/dev/null`. This loss is
limited to nginx diagnostic messages for `/a/*` and `/reset-password`; the
sanitized access lines still record status and duration, and application data
remains the authority for a valid click or reset.

The reset location serves the current `index.html` directly from the inherited
frontend root with `try_files /index.html =404`. It repeats the versioned
security-header include and `Cache-Control: no-cache`, so it preserves the SPA
entry-point contract without an internal redirect into a location that could
select the global raw log format.

All other locations retain their current access and error logging.

### Uvicorn

Add a dependency-free `logging.Filter` owned by `signals.api`. It is installed
on `uvicorn.access` by `build_application()`, after uvicorn has configured its
loggers and before the application serves requests.

For the documented uvicorn access-record tuple, the filter replaces a target
that starts with `/a/`, including any query string, with exactly
`/a/[redacted]`. It leaves a structurally valid record for any other route
unchanged. It does not inspect or mutate application, runtime-event, root, or
provider loggers.

Installation is idempotent so application reconstruction and multi-worker
startup cannot stack filters. If a future uvicorn version supplies an unknown
record shape, the access record is suppressed rather than risk rendering a raw
target. This fail-closed behavior is covered by a compatibility test.

The filter is installed only when `build_application()` runs. Importing
`signals.api.asgi` remains inert and does not open a database or mutate global
logging.

## Versioned boundary

The implementation is confined to:

- `src/signals/api/access_logging.py` for the filter and its idempotent
  installer;
- `src/signals/api/asgi.py` for production wiring;
- `ops/nginx/kivou-limits.conf` for the HTTP-level sanitized format;
- `ops/nginx/kivou-staging.conf` for both sensitive-link locations;
- focused API/nginx tests;
- the existing nginx deployment and rollback section in `ops/README.md`;
- this specification and its TDD implementation plan.

It does not add a systemd unit: the currently deployed API command remains
unchanged, and the application-owned filter travels with the reviewed backend
SHA.

## Rejected alternatives

### Disable every uvicorn access log

`--no-access-log` is simple but global. It would remove useful loopback and
application-boundary evidence for every route, while nginx would still need its
own attribution-specific protection.

### Disable nginx access logging only and filter uvicorn

This protects the normal access files but loses all nginx status/duration
evidence for attribution and reset-link requests. It also leaves nginx error
logging as a raw request leak.

### Change token transport or attribution semantics

Moving the token into another channel would break already-issued deep links and
expand the change into the conversion contract. The route and token model are
not defective; the defect is confined to logging.

## Security and privacy invariants

- No token, token fragment, query string, e-mail address, provider identifier,
  request body, secret, or attribution cookie is written by the new logs.
- An attribution token remains available only in request memory long enough
  for the existing verification and cookie response. A reset token remains only
  in the browser location and the existing reset-confirmation request; nginx
  never records it.
- The response contract is unchanged: valid token `303 /signup`, invalid token
  application JSON `404`, no SPA fallback.
- The reset contract is unchanged: `/reset-password?token=...` serves the SPA
  entry point with no cache, and React submits the token through the existing
  confirmation API.
- Rate limits, TLS, proxy headers, cookie flags, attribution expiry, source
  validation, and conversion persistence are unchanged.
- No migration, provider request, e-mail, prospect action, Stripe mutation, or
  production action belongs to this change.

## TDD proof

Tests are written and observed failing before implementation. They prove:

1. a synthetic `/a/<marker>?<query>` uvicorn record renders only
   `/a/[redacted]`;
2. neither marker nor query survives in the rendered record;
3. a normal route such as `/me?cursor=opaque` is unchanged;
4. installing the filter twice yields exactly one instance;
5. root and `signals.runtime_events` loggers remain untouched;
6. an unknown uvicorn access-record shape is suppressed;
7. `build_application()` installs the filter while module import remains inert;
8. neither nginx sensitive-link format contains raw-target or header variables;
9. only `location ^~ /a/` selects the attribution format and neutralizes its
   error log;
10. only `location = /reset-password` selects the reset format, neutralizes its
    error log, and serves the non-cached SPA entry point directly;
11. all other nginx proxy and frontend locations retain normal logging and
    routing.

The focused tests run first. The final PR head then runs the repository's
standard backend suite, Ruff, nginx contract tests, `systemd-analyze verify`
where applicable, and `git diff --check`. Frontend validation is not required
because no frontend file or behavior changes.

## Staging deployment and validation

Deploy the reviewed main SHA without a migration. Restart the API through the
existing zero-downtime blue/green procedure so new workers load the filter.
Publish the nginx bundle atomically, run `nginx -t`, and reload nginx without a
configuration rewrite.

After the switchover, send one invalid synthetic attribution marker and one
synthetic reset query marker. Verify with counter-only searches scoped to the
deployment timestamp:

- nginx contains one sanitized `/a/[redacted]` access entry and zero marker
  occurrences;
- `kivou-api` journald contains a sanitized access entry and zero marker
  occurrences;
- the response remains application JSON 404 with no cookie and no SPA HTML;
- nginx contains one sanitized reset-link access entry, zero reset-marker
  occurrences, and the route still returns the non-cached SPA entry point;
- nginx and the API remain active and the public SaaS smoke is unchanged.

Only after this proof may blocker #84 continue with an authorized valid token
held entirely in process memory. That proof emits only PASS/FAIL and numeric
counts. It must show 303, the fixed redirect and cookie attributes, one durable
click, no journey, and zero token occurrences in nginx or journald. #93 can be
closed after the synthetic reset marker proves the runtime boundary; it does
not require generating or sending another password-reset e-mail.

## Rollback

Before deployment, retain the previous backend release and a root-only nginx
snapshot. Rollback restores the nginx snapshot atomically, validates it with
`nginx -t`, reloads nginx, switches the backend symlink to the previous release,
and restarts the API through the same zero-downtime procedure.

The previous release reintroduces token logging. Therefore no valid
attribution-token proof may run after rollback. Existing logs are not broadly
deleted; validation uses synthetic markers and counter-only searches.

## Residual limit

The guarantee covers syntactically valid HTTP requests selected by
`location ^~ /a/` or `location = /reset-password` and all application access
records. A malformed request rejected by nginx before location selection is
governed by nginx's global error policy. Extending redaction to arbitrary
malformed request lines would require a broader server-wide logging design and
is outside blockers #84 and #93.
