# Sensitive link token log redaction

Status: approved design; implementation complete in PR

Date: 2026-08-26

Scope: staging audit blocker #84 and reset-link follow-up #93

## Problem

Two public links carry opaque bearer tokens in their request target:

- attribution: `GET /a/{token}`;
- password reset: `GET /reset-password?token=...`.

Nginx currently inherits the combined access format, which records the complete
request and referer. Uvicorn independently records the complete target for the
attribution request proxied to FastAPI. A valid attribution click would
therefore copy its token into nginx and journald. The first real reset click
would copy its token into nginx.

A counter-only staging audit found no real reset-token target in current logs.
The attribution route was exercised only with a deliberately invalid synthetic
marker. No valid token was read or published during discovery.

The reset page creates a second-order risk: with
`Referrer-Policy: strict-origin-when-cross-origin`, same-origin asset requests
may carry the complete reset URL in `Referer`. Merely sanitizing the first page
request would leave that token available to later access or error logs.

## Decision

Nginx becomes the sole public HTTP access-log authority. It keeps bounded
operational evidence while excluding query strings, referers, request headers
and sensitive path values. Uvicorn's duplicate access logger is disabled by the
versioned API service. Application, runtime-event and service error logs remain
enabled.

This infrastructure-owned boundary is simpler and more durable than depending
on uvicorn's private `LogRecord` tuple shape.

## Nginx access-log contract

Define at HTTP scope:

1. one non-volatile `map` from normalized `$uri` to a safe path:
   - every value beginning `/a/` becomes the literal `/a/[redacted]`;
   - `/reset-password` remains the literal `/reset-password`;
   - every other value remains normalized `$uri`;
2. each server evaluates that map once in the server rewrite phase and stores
   the result in the variable used by the access log, before location routing;
3. one `escape=json` log format containing only:
   - remote address;
   - timestamp;
   - request method;
   - safe mapped path;
   - HTTP protocol;
   - response status;
   - response size;
   - request duration.

Neither the map nor the log format may reference `$request`, `$request_uri`,
`$args`, a referer, user agent, cookie, upstream header or arbitrary request
header. The server-phase assignment forces nginx's normal non-volatile map
cache to retain the original normalized safe value even if `try_files` later
changes the current `$uri` to `/index.html`. This preserves
`/reset-password` as operational evidence, excludes its query token, and
redacts both encoded and ordinary attribution paths.

Both the HTTP/80 redirect server and the HTTPS server explicitly select this
format. They therefore override nginx's inherited combined access log instead
of adding a second log destination.

## Sensitive response and error contract

Both servers contain explicit sensitive locations for `/a/` and
`/reset-password`.

Each of the four locations includes the same root-owned runtime gate. The
versioned open candidate is inert; the versioned closed candidate contains only
`return 503`. Swapping that one small fragment atomically and reloading nginx
can therefore close every sensitive link without changing the rest of the SaaS
or restoring an unsafe configuration.

On HTTPS:

- `/a/` retains its rate limit and FastAPI proxy;
- `/reset-password` serves the current `index.html` directly from the inherited
  frontend root with `try_files /index.html =404`;
- both locations use a dedicated security-header include whose
  `Referrer-Policy` is exactly `no-referrer`;
- the attribution proxy hides FastAPI's own `Referrer-Policy` before nginx adds
  the single authoritative value;
- the reset entry point retains `Cache-Control: no-cache`;
- both locations send their nginx error log to `/dev/null` because nginx error
  records cannot be custom-formatted and can reproduce the raw request or
  referer.

On HTTP/80, the two explicit locations retain the canonical HTTPS redirect,
add `Referrer-Policy: no-referrer`, and suppress their local error log. The
redirect keeps the original request target so the link remains functional, but
the server's safe access format cannot record it.

The dedicated sensitive security-header fragment contains the same reviewed
headers as the ordinary fragment except for the stricter referrer policy. A
test compares the directives so later security-header changes cannot drift
silently.

All other routing, rate limits, TLS, static caching and proxy behavior remain
unchanged.

## Uvicorn and systemd contract

Add the existing staging API unit to `ops/systemd/kivou-api.service`, preserving
its deployed user, group, working directory, environment file, two workers,
loopback binding, trusted proxy boundary, restart policy and hardening.

Its uvicorn command adds exactly `--no-access-log`. It does not disable
`uvicorn.error`, `signals.runtime_events`, application exceptions or journald.
Nginx retains one sanitized access entry for every public request, so public
operational visibility is not lost.

The unit contains no secret or environment value. Its active staging copy must
match the reviewed file byte-for-byte after deployment.

## Versioned boundary

The implementation is confined to:

- `ops/nginx/kivou-limits.conf` for the safe-path map and format;
- `ops/nginx/kivou-staging.conf` for both server-level access logs and the four
  HTTP/HTTPS sensitive locations;
- a new sensitive-link security-header fragment under `ops/nginx/`;
- versioned open and closed sensitive-link gate fragments under `ops/nginx/`;
- `ops/systemd/kivou-api.service` for the reproducible uvicorn command;
- focused nginx/systemd contract tests;
- an exact blue/green deployment and security-preserving rollback procedure in
  `ops/README.md`;
- this specification and its TDD implementation plan.

No Python application module, frontend file, database model or migration is
changed.

## Rejected alternatives

### A targeted Python filter on `uvicorn.access`

This preserves duplicate access lines but depends on uvicorn's private message
template and argument tuple. It requires fail-closed compatibility logic and
still leaves nginx, HTTP/80, referers, deployment ordering and rollback to solve
separately.

### Per-location access logging only

This leaves query strings and referers available elsewhere, including asset
requests following the reset page. It also risks falling back to the global
combined format after an internal redirect.

### Changing token transport

Moving either token would break existing deep-link contracts and expand the
change into conversion, authentication, React and e-mail templates. The token
contracts are not defective; their logging boundary is.

## Security and privacy invariants

- No attribution token, reset token, token fragment, query string, referer,
  e-mail address, provider identifier, request body, secret or attribution
  cookie enters the new access logs.
- Valid links keep their existing behavior: attribution returns `303 /signup`
  and its secure cookie; reset serves the non-cached SPA and confirms through
  the existing API.
- Invalid attribution remains application JSON 404 with no cookie and no SPA
  fallback.
- No migration, provider call, e-mail, prospect action, Stripe mutation or
  production action belongs to this change.

## TDD proof

Tests are written and observed failing before configuration changes. They
prove:

1. the safe nginx format contains no raw-target, query, referer, cookie or
   arbitrary-header variable;
2. the non-volatile safe-path map redacts normalized `/a/`, preserves the
   literal reset entry point, and is forced into the nginx variable cache by a
   server-phase assignment before `try_files`;
3. both HTTP and HTTPS servers explicitly select exactly one safe access log;
4. both servers have explicit attribution and reset locations;
5. the HTTPS attribution location preserves proxy/rate limits, hides the
   upstream referrer policy and suppresses its error log;
6. the HTTPS reset location serves `index.html` directly, is non-cached and
   suppresses its error log;
7. all four sensitive locations emit exactly one `no-referrer` policy;
8. sensitive and ordinary security fragments have identical directives except
   for referrer policy;
9. every sensitive location includes the same runtime gate, whose open and
   closed candidates are respectively inert and exactly `return 503`;
10. ordinary API/static/SPA locations retain their current routing and cache
   contracts;
11. the versioned API unit matches the deployed runtime contract and contains
    exactly one `--no-access-log` flag without disabling error logs;
12. the runbook contains an executable atomic transition and a rollback that
    never restores raw logging.

The focused tests run first. The final PR head then runs the standard backend
suite, Ruff, nginx contract tests, `systemd-analyze verify`, and
`git diff --check`. Frontend validation is unnecessary because no frontend file
or behavior changes.

## Atomic staging deployment

The runbook versions the exact blue/green procedure; it does not refer to an
undeclared operational convention.

1. Build the reviewed main SHA as a new release and run its API on loopback port
   8001 with `--no-access-log`, the protected environment file and the same
   hardening as the normal service.
2. Validate the green API directly: application import, `/openapi.json` 200 and
   unauthenticated `/me` 401.
3. Build and validate an nginx candidate from the new safe templates with its
   reviewed proxy destinations pointing to green port 8001.
4. Snapshot the active nginx files and API unit root-only.
5. Publish the safe nginx bundle atomically and reload. The nginx reload is the
   single public transition: requests use either old nginx plus old API or safe
   nginx plus green API, never one new and one old logging layer.
6. Monitor public availability, atomically switch `/srv/kivou/app`, install the
   versioned API unit, reload systemd and restart the normal port-8000 API while
   public traffic remains on green.
7. Validate port 8000, publish the final safe nginx candidate pointing to 8000,
   reload, validate public traffic, then stop green.

No valid sensitive token is generated or exercised before step 7 succeeds.

## Staging validation

After the atomic transition, use only synthetic markers first:

- exercise attribution and reset links over HTTP and HTTPS;
- verify expected 301, JSON 404 and non-cached SPA responses;
- request a real static asset with a synthetic sensitive `Referer`;
- require zero marker occurrences in nginx access/error logs and
  `kivou-api` journald since the deployment boundary;
- require sanitized attribution paths and reset paths in nginx access evidence;
- require exactly one `Referrer-Policy: no-referrer` on sensitive responses;
- require nginx and API active, `nginx -t` green, no asset error and the public
  SaaS smoke unchanged.

Only then may #84 use its separately authorized valid token held entirely in
process memory. Its script emits only PASS/FAIL and numeric counts. It must show
303, fixed redirect and cookie attributes, one durable click, no journey, and
zero token occurrence in every log. #93 needs no new real reset e-mail: the
synthetic query and downstream-referer proofs close its logging defect.

## Security-preserving rollback

Rollback never restores the old nginx access format or the old API unit. Those
files are a security floor, not application state.

- If the application release fails, keep safe nginx and the versioned
  `--no-access-log` unit, switch only `/srv/kivou/app` to the previous release,
  restart port 8000 while green carries traffic, validate it, then switch the
  safe proxy back to 8000.
- If either sensitive location fails functionally, publish a validated
  closed-gate candidate. It keeps the safe access format, `no-referrer` header
  and suppressed error log but returns 503 before proxy or static handling.
  Never fall back to a location with the ordinary referrer policy.
- If a safe nginx candidate fails `nginx -t`, do not reload it and do not run a
  valid sensitive-link proof. The previous process remains authoritative.
- If a post-reload failure cannot retain the safe logging floor, close the two
  sensitive routes and keep the rest of staging available; never restore raw
  token logging.

The runbook gives exact commands, health gates and root-only snapshot paths for
each branch. It never prints or accepts a real token.

## Residual limit

The guarantee covers syntactically valid HTTP requests that reach either Kivou
server block and browser navigation produced by Kivou responses. A malformed
request rejected by nginx before server/location selection remains governed by
nginx's global error policy. Protecting arbitrary malformed request lines would
require a host-wide nginx error-log policy and is outside #84 and #93.
