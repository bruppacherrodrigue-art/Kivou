# Kivou Founder Console

## Decision

Kivou has **one and only one** founder control surface:

`https://control.kivou.eu`

There is no permanent `control.staging.kivou.eu` console. Validation happens in tests, CI and local or ephemeral review before deployment. When production is ready, this single console is connected directly to production read models.

The console is not a route, skin or internal twin of the customer dashboard. It has its own frontend build, its own FastAPI process, its own hostname, its own access boundary and its own deployment directory.

## Operator

HTTPS Basic Auth allows one operator only:

- username: `rodrigue`;
- account metadata: `rodrigue.bruppacher@gmail.com`.

The password exists only in the root-managed `/etc/kivou/founder.htpasswd` file
on the production server. There is no signup, invitation or customer session in
V1.

## Security model

```text
Public DNS for control.kivou.eu
  -> nginx HTTP redirect / ACME challenge and HTTPS Basic Auth
  -> Founder API on 127.0.0.1:8011
      -> GET read models through PostgreSQL role kivou_founder_ro
      -> bounded assisted-prospection actions through PostgreSQL role kivou_founder_rw
```

Defense in depth:

1. only the dedicated `control.kivou.eu` nginx vhost serves the console over HTTPS;
2. nginx requires Basic Auth from the root-managed password file;
3. nginx overwrites `X-Kivou-Founder-Origin-Secret` with a local root-managed secret;
4. nginx overwrites `X-Kivou-Founder-User` with the authenticated Basic Auth username;
5. the API requires the proxy secret and the configured username must exactly match `rodrigue`;
6. the Founder API mounts no customer route;
7. read-model sessions use `kivou_founder_ro` and start with `default_transaction_read_only=on`;
8. the read-model role receives CONNECT, USAGE and SELECT only;
9. each read-model session verifies `SHOW transaction_read_only = on` before serving reads;
10. assisted-prospection actions are isolated under `/api/founder/actions/prospection/*` and use only `kivou_founder_rw`;
11. the action role has narrowly enumerated grants for the review queue, send audit, suppression lookup and approved supplier-directory corrections;
12. both Founder database connections have a bounded statement timeout.

Basic Auth and the origin secret are separate controls. The secret prevents
direct calls to the local API from succeeding with a forged username header.

## Repository layout

```text
frontend/founder/                 standalone React entrypoint
frontend/vite.founder.config.ts   separate Vite build -> frontend/dist-founder
src/signals/founder_api/          separate FastAPI application and read models
ops/nginx/kivou-founder-control.conf
ops/systemd/kivou-founder-api.service
ops/examples/founder-console.env.example
```

The customer SPA remains built into `frontend/dist`. The Founder Console is built into `frontend/dist-founder` and deployed independently to `/srv/kivou-founder/frontend`.

## Authority boundary

The Founder service has two separate server-side capabilities:

- consultation endpoints compose read models through `kivou_founder_ro`;
- the existing `/api/founder/actions/prospection/list`, `/approve`, `/correct`,
  `/reject` and `/send` routes use the separately credentialed
  `kivou_founder_rw` action service and its bounded grants.

The console remains read-only outside **Prospection**. On that page, the
operator can validate, correct or reject a prepared target and send only a
previously validated batch. Every mutation carries the displayed
`expected_version`; send also carries one stable UUID `request_id`. The UI
applies the decision optimistically, rolls it back on failure, and displays the
API message and code for `409`, `422` and `502` responses.
The queue shows how many targets remain server-side and loads at most one next
page per status after an explicit **Charger la suite** click. A send contains at
most 25 approved targets; if more are waiting, the next batch stays visible.
Every terminal provider result is reconciled from the server before a failed
target can be retried with a new request UUID. Only an ambiguous proxy or
transport failure keeps the same UUID for a safe idempotent replay.

nginx keeps the `/api/founder/` prefix GET/HEAD-only. Four exact locations
allow POST: `/approve`, `/correct`, `/reject` and `/send` below
`/api/founder/actions/prospection`. Those exact locations apply the same Basic
Auth, rate limit, overwritten Founder identity and origin-secret headers as the
read route. No other Founder or customer path gains write authority.

This UI constraint is not an absence of server-side write routes. The Founder
API still mounts no customer route, never exposes a customer mutation through
the Founder host, and never gives the frontend direct PostgreSQL access. It
also does not expose controls for policy changes, retries, the kill switch or
deployment.

## Read-model semantics

The endpoints `GET /api/founder/overview` and
`GET /api/founder/prospection` compose existing Kivou truth. They do not call
an external provider while rendering the console.

### Acquisition status

One `FounderAcquisitionStatus` projection is the displayed source of truth on
**Aujourd’hui**, **Prospection** and **Système**. The same contract reports:

- the acquisition mode;
- whether acquisition is active, stopped or unavailable, with the time since
  that activity state began when known;
- the last observed cycle reference and timestamp;
- the last cycle result and its durable reason when available.

The mode and last-cycle fields come from the production runtime observation;
activity and its start time come from the acquisition systemd timer. Missing
or unstable evidence remains explicitly unknown rather than being inferred
from another timestamp. The detailed health and readiness diagnostics in
**Système** remain separate and do not create a second acquisition summary.

### À traiter

The queue contains only:

- operational incidents whose state is not `RESOLVED`;
- acquisition dead letters whose status is `OPEN`.

Rows are whitelisted into a PII-minimal contract. No raw provider payload, email body, customer note or secret is returned.

### Tunnel commercial

**Tunnel commercial** replaces the former visible weekly analytics panel. It
shows six stages: sent, opened, clicked, landed, profile confirmed and paid.
The read model includes both regular acquisition and assisted-prospection
delivery evidence.

The default **Période** view offers `Aujourd’hui` and `7 derniers jours`:

- `Aujourd’hui` runs from midnight in `Europe/Zurich` to the request time;
- `7 derniers jours` runs from midnight six calendar days earlier to the
  request time;
- every stage is counted by its own event timestamp inside the selected
  interval, whose exact bounds are returned to the UI.

The **Par cohorte** view selects one of the 52 completed send weeks. Its cohort
contains the targets sent during that week, while every later stage is counted
from each send through the current request time, including stages reached
after the selected week ended.

MRR by currency and churn are shown separately under **Situation actuelle**.
They form a current, timestamped snapshot independent of both the period and
the cohort; they are not attributed to the selected interval.

### Prospection

The page starts with the same acquisition-status projection, then always puts
**File du jour** before **Annuaire**. The queue combines `pending_review`
targets awaiting a decision with already `approved` targets awaiting the
operator's explicit send. Prepared targets use a professional address whose MX
verification succeeded. Mail contents can be opened before validation.

**Valider** transitions one current target to `approved`. **Corriger** accepts
only the address, director and company name fields from the public contract.
**Écarter** requires one closed reason and a comment for `other`. **Envoyer** is
disabled when no target is approved or when the acquisition kill switch is
active; clicking it opens a second confirmation and performs no request until
the operator clicks **Envoyer maintenant**. Each confirmed batch contains at
most 25 targets, then the queue is reloaded from its authoritative versions.
Loading the page never sends mail.

**Annuaire** reads the active real supplier directory and returns pages of 25
rows. Search, supplier-family, French-department and qualification filters are
applied before pagination while the summary and facets remain global.

A raw domain or website candidate is never exposed unless its validation
method confirms it. Each row carries a `qualification_status` that distinguishes
`confirmed_domain`, `without_website`, `reverification_required` and
`to_qualify`. Department names come from the French reference and are displayed
with their code, for example `Rhône (69)`. Verified MX states are rendered as
`MX vérifié`.

### Qualité

The first quality panel is intentionally modest. It counts the **current feedback rows whose last update falls inside the trailing 30-day window**. It is not a complete append-only history of every opinion ever submitted.

It reports:

- current feedback updated in the window;
- relevant and not-relevant states;
- contacts declared during the window;
- negative share among feedback updated in the window;
- structured negative reasons.

Customer feedback remains separate from public facts and engine inferences. The console never rewrites the Need Graph, scoring or ICP from a negative click.

### Système

The system panel reuses `OperationsReadService`:

- API and database health;
- supervisor-loop health;
- Policy Gateway;
- campaign execution;
- dead-letter queue;
- circuit breakers;
- readiness gates and blockers.

The same acquisition-status component appears at the top of this section. The
remaining component health, reasons and readiness gates are detailed diagnostic
evidence, not another global acquisition state.

## PostgreSQL roles

### Read-model role

Create a dedicated credential. Never reuse the Kivou application or migration writer.

Run as a PostgreSQL administrator, replacing the password and database name:

```sql
CREATE ROLE kivou_founder_ro
  LOGIN
  PASSWORD 'REPLACE_WITH_A_RANDOM_PASSWORD'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOREPLICATION;

ALTER ROLE kivou_founder_ro SET default_transaction_read_only = on;
ALTER ROLE kivou_founder_ro SET statement_timeout = '10s';

GRANT CONNECT ON DATABASE kivou TO kivou_founder_ro;
```

Then connect to the Kivou database:

```sql
GRANT USAGE ON SCHEMA public TO kivou_founder_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO kivou_founder_ro;
REVOKE CREATE ON SCHEMA public FROM kivou_founder_ro;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM kivou_founder_ro;
```

Future tables must also become readable. `ALTER DEFAULT PRIVILEGES` must be executed **for the role that owns or creates Kivou tables**, not merely for the administrator running the command:

```sql
ALTER DEFAULT PRIVILEGES FOR ROLE KIVOU_MIGRATION_ROLE IN SCHEMA public
  GRANT SELECT ON TABLES TO kivou_founder_ro;
```

After every migration, the deploy runbook must verify that the new tables are covered. The Founder service never runs Alembic and owns no migration permission.

Expected production URL:

```dotenv
KIVOU_FOUNDER_DATABASE_URL=postgresql+psycopg://kivou_founder_ro:REPLACE@127.0.0.1:5432/kivou
```

### Assisted-action role

The assisted-prospection actions use a second credential. Create it before the
`0051_assisted_prospection` migration so that the migration can grant only the
review queue, send audit, suppression lookup, and the explicitly mutable
supplier-directory fields:

```sql
CREATE ROLE kivou_founder_rw
  LOGIN PASSWORD 'REPLACE_WITH_A_RANDOM_PASSWORD'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
ALTER ROLE kivou_founder_rw SET statement_timeout = '10s';
GRANT CONNECT ON DATABASE kivou TO kivou_founder_rw;
```

Set the distinct URL in `/etc/kivou/founder.env`:

```dotenv
KIVOU_FOUNDER_WRITE_DATABASE_URL=postgresql+psycopg://kivou_founder_rw:REPLACE@127.0.0.1:5432/kivou
```

The Founder process verifies `current_user=kivou_founder_rw` and a writable
transaction mode on every new action connection. The migration grants no
access to customer, billing, or general application writes.

Both database URLs must use PostgreSQL. The production Founder entrypoint also
refuses an action connection whose database user is not `kivou_founder_rw`.

## DNS handoff

Rodrigue creates this record at the current registrar:

| Name | Type | Value |
| --- | --- | --- |
| `control.kivou.eu` | `A` | `179.237.105.52` |

This is a direct DNS handoff, with no DNS proxy (`sans proxy DNS`).

Wait until public DNS resolves `control.kivou.eu` to `179.237.105.52` before
requesting the certificate. Ports 80 and 443 must reach nginx directly.

## Basic Auth credential

Install `apache2-utils` if `htpasswd` is not already present. Generate one
strong password, display it once for immediate transfer to Rodrigue through the
agreed secure channel, feed it to `htpasswd` over standard input, then unset it:

```bash
sudo apt-get install apache2-utils
sudo install -d -o root -g root -m 0755 /etc/kivou
sudo -v
FOUNDER_BASIC_PASSWORD="$(openssl rand -base64 32)"
printf 'Founder password (transfer once now): %s\n' "$FOUNDER_BASIC_PASSWORD"
printf '%s\n' "$FOUNDER_BASIC_PASSWORD" \
  | sudo htpasswd -i -B -c /etc/kivou/founder.htpasswd rodrigue
unset FOUNDER_BASIC_PASSWORD
sudo chown root:www-data /etc/kivou/founder.htpasswd
sudo chmod 0640 /etc/kivou/founder.htpasswd
```

The `-B` option stores a bcrypt hash; the cleartext is never written to the
password file.

Do not paste the cleartext password into a command, file, shell history, ticket
or repository. The generated value must not be recorded after the one-time
transfer. Create this file before installing or testing the complete HTTPS
vhost.

## Founder environment and origin secret

From the root of the checked-out Kivou release, install the complete versioned
example first, then edit every placeholder locally:

```bash
sudo install -o root -g kivou -m 0640 \
  ops/examples/founder-console.env.example /etc/kivou/founder.env
sudoedit /etc/kivou/founder.env
```

The resulting file remains complete and contains all of these settings:

```dotenv
KIVOU_FOUNDER_HOSTNAME=control.kivou.eu
KIVOU_FOUNDER_ENVIRONMENT=PRODUCTION
KIVOU_FOUNDER_ALLOWED_EMAIL=rodrigue.bruppacher@gmail.com
KIVOU_FOUNDER_ALLOWED_USER=rodrigue
KIVOU_FOUNDER_ORIGIN_SECRET=<random-value-from-openssl-rand-hex-32>
KIVOU_FOUNDER_DATABASE_URL=postgresql+psycopg://kivou_founder_ro:REPLACE@127.0.0.1:5432/kivou
KIVOU_FOUNDER_WRITE_DATABASE_URL=postgresql+psycopg://kivou_founder_rw:REPLACE@127.0.0.1:5432/kivou
```

Generate the origin secret with `openssl rand -hex 32`. Put that same generated
value in `KIVOU_FOUNDER_ORIGIN_SECRET` and create
`/etc/kivou/founder-origin-secret.conf` as root:

```bash
sudoedit /etc/kivou/founder-origin-secret.conf
```

```nginx
set $kivou_founder_origin_secret "<same-random-value>";
```

Permissions:

```bash
sudo chown root:kivou /etc/kivou/founder.env
sudo chmod 0640 /etc/kivou/founder.env
sudo chown root:www-data /etc/kivou/founder-origin-secret.conf
sudo chmod 0640 /etc/kivou/founder-origin-secret.conf
```

Never commit the generated value. Both the complete environment file and the
origin-secret include must exist with these permissions before the complete
HTTPS vhost is installed or tested.

Verify the database session before starting the Founder service. This transient
unit runs as `kivou` from the deployed application directory and loads
`/etc/kivou/founder.env` with the same `EnvironmentFile=` semantics as the
systemd service. The database URL is never placed in a command argument or
printed:

```bash
sudo -v
sudo systemd-run --wait --pipe --collect \
  --property=Type=exec \
  --property=User=kivou \
  --property=WorkingDirectory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/founder.env \
  /srv/kivou/app/.venv/bin/python - <<'PY'
from signals.founder_api.database import create_founder_database_engine

engine = create_founder_database_engine()
with engine.connect() as connection:
    assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
    print("Founder database session: read-only")
PY
```

Do not source the environment file as shell code. `--pipe` forwards the here-doc
to Python, `--wait` returns the assertion's exit status, and `--collect` removes
the completed transient unit.

## First-certificate bootstrap

The versioned nginx vhost references certificate files that do not exist on a
first installation. With DNS already resolving, and the environment,
origin-secret include and password file already installed, bootstrap safely in
this order.

Install nginx and Certbot if needed, then create the webroot and an exact
temporary HTTP-only vhost:

```bash
sudo install -d -o root -g www-data -m 0755 /var/www/certbot
sudo install -d -o root -g www-data -m 0755 \
  /var/www/certbot/.well-known/acme-challenge
sudo tee /etc/nginx/sites-available/kivou-founder-bootstrap.conf >/dev/null <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name control.kivou.eu;

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type text/plain;
    }

    location / {
        return 301 https://control.kivou.eu$request_uri;
    }
}
NGINX
sudo ln -s /etc/nginx/sites-available/kivou-founder-bootstrap.conf \
  /etc/nginx/sites-enabled/kivou-founder-bootstrap.conf
sudo nginx -t
sudo systemctl reload nginx
```

Confirm the public challenge path returns both a successful status and the
exact expected body. A redirect or an unexpected body fails this check:

```bash
printf 'ready\n' \
  | sudo tee /var/www/certbot/.well-known/acme-challenge/bootstrap-check >/dev/null
ACME_RESPONSE="$(curl --fail --silent --show-error --write-out '%{http_code}' \
  http://control.kivou.eu/.well-known/acme-challenge/bootstrap-check)"
test "$ACME_RESPONSE" = "$(printf 'ready\n200')"
unset ACME_RESPONSE
sudo rm -- /var/www/certbot/.well-known/acme-challenge/bootstrap-check
```

Obtain the first certificate without allowing Certbot to rewrite nginx:

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d control.kivou.eu
```

Remove only the temporary vhost, then deploy the explicit production SHA. The
deployment's nginx transaction installs `ops/nginx/kivou-founder-control.conf`,
validates it with `nginx -t` and reloads nginx only after validation succeeds.
If nginx validation or reload fails, it restores the prior available and
enabled nginx state:

```bash
sudo rm -- /etc/nginx/sites-enabled/kivou-founder-bootstrap.conf
sudo rm -- /etc/nginx/sites-available/kivou-founder-bootstrap.conf
KIVOU_RELEASE_SHA="$(git rev-parse HEAD)"
sudo systemd-run --wait --collect --pipe \
  --property=Type=exec \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/source/ops/bin/kivou-deploy.sh production "$KIVOU_RELEASE_SHA"
unset KIVOU_RELEASE_SHA
```

Never activate the complete HTTPS vhost before the certificate, complete
environment, origin-secret include and htpasswd file all exist.

## Build and deploy contract

PRs never deploy.

Founder frontend build:

```bash
cd frontend
npm ci
npm test -- --run
npm run build:founder
```

Deployment is performed by `ops/bin/kivou-deploy.sh`. In production it builds
`frontend/dist-founder/`, atomically switches `/srv/kivou-founder/frontend` to
that build and preserves the former target as
`/srv/kivou-founder/frontend.previous`. The `.previous` link is a recovery
reference, not an automatic frontend rollback.

The script then installs the versioned `kivou-founder-api.service`, reloads
systemd, enables and restarts the unit, and performs bounded local health
checks. It does not automatically roll back the frontend or unit if this phase
fails.

Separately, the script installs the nginx site, validates the candidate with
`nginx -t`, and reloads nginx. That nginx transaction snapshots and restores
the prior available and enabled site state if validation or reload fails.

Backend gate:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
```

## Blocked-domain audit in production

The blocked-domain audit is an operations command, not a Founder Console
action. It reads `KIVOU_DATABASE_URL` from the protected production environment
and must run with the normal Kivou application database role. Do not use
`KIVOU_FOUNDER_DATABASE_URL` or `kivou_founder_ro`: the application pass needs
`UPDATE` permission to mark affected directory rows for reverification. The
command never prints the database URL or other configuration values.

After deploying the audited release, run these three passes in order. The first
pass is the default dry-run and performs no write:

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.supplier_directory.domain_audit
```

Inspect the JSON before continuing. For the 11 September snapshot, it should
report one affected row: SIREN `402274716`, legal name `AJEBAT`, domain
`neyron.localbiz.fr`, and `modified_count` equal to zero. Stop if the affected
set is unexpected. Apply exactly that audit:

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.supplier_directory.domain_audit --apply
```

The application pass must report `modified_count` equal to the prior
`affected_count`. It clears the untrusted domain and contact evidence and sets
the reason `blocked_domain_audit`. Finally, rerun the dry-run:

If the command reports `domain_audit_failed`, no row from that pass is
quarantined. In particular, the audit refuses to race a target whose send
request is still `started`. Let that request reach a terminal state, investigate
any other concurrent directory change, then restart from the dry-run; never
assume a partial application succeeded.

```bash
sudo systemd-run --wait --collect --pipe \
  --uid=kivou --gid=kivou \
  --working-directory=/srv/kivou/app \
  --property=EnvironmentFile=/etc/kivou/production.env \
  /srv/kivou/app/.venv/bin/python -m signals.supplier_directory.domain_audit
```

The final JSON must report `affected_count: 0` and `modified_count: 0`. A
non-zero affected count means the quarantine is incomplete; do not treat the
operation as finished.

Before publication:

```bash
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl restart kivou-founder-api
curl --fail http://127.0.0.1:8011/healthz
```

`/healthz` proves only that the Founder process is alive. The authenticated overview smoke test proves that the production read models and read-only database connection work.

Public smoke tests must confirm:

```bash
# No credential: authentication challenge.
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://control.kivou.eu/)" = 401

# curl prompts for the password; the cleartext is not a command-line argument.
curl --fail --user rodrigue https://control.kivou.eu/
curl --fail --user rodrigue https://control.kivou.eu/api/founder/overview

# The Founder host must not expose a customer route.
test "$(curl -sS --user rodrigue -o /dev/null -w '%{http_code}' \
  https://control.kivou.eu/app/)" = 404

# The customer host must not expose a Founder route.
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://kivou.eu/api/founder/overview)" = 404

# Inspect the installed certificate hostname and expiry, then test renewal.
sudo certbot certificates
sudo certbot renew --dry-run
```

Also confirm in the authenticated console that:

- the console says `Production`; `Consultation` remains visible on the
  read-only pages and is absent from Prospection;
- customer login cookies are neither required nor accepted as Founder authorization;
- customer routes are not reachable through the Founder host;
- no `/internal/*` route is exposed by the Founder vhost;
- Aujourd’hui, Prospection and Système show the same acquisition mode,
  activity-since value and last-cycle result;
- Tunnel commercial opens on `7 derniers jours`, switches to `Aujourd’hui`,
  and shows exact bounds ending at the observation time;
- the selected send cohort follows its stages through the observation time,
  while MRR and churn remain a separately timestamped current snapshot;
- File du jour precedes Annuaire and contains the `pending_review` and
  `approved` review states;
- Annuaire is paginated by 25, names French departments, hides unconfirmed
  domains, exposes their qualification state and labels verified mail as
  `MX vérifié`;
- validation, correction and rejection send the target UUID and displayed
  `expected_version` only after an operator click;
- send opens an explicit confirmation, uses a stable UUID `request_id`, and
  makes no request before **Envoyer maintenant** is clicked;
- `409`, `422` and `502` errors are readable and restore optimistic state.

## Delivered surface

- independent frontend build;
- independent FastAPI process;
- direct HTTPS boundary with nginx Basic Auth;
- one production hostname;
- French-only console with bounded writes on Prospection and read-only
  authority everywhere else;
- versioned nginx, systemd and runbook;
- removal of the cockpit route from the customer SaaS;
- no customer route mounted in the Founder API;
- read models through the dedicated `kivou_founder_ro` role;
- bounded assisted-prospection routes through the dedicated
  `kivou_founder_rw` role;
- Aujourd’hui, Prospection, À traiter, Tunnel commercial, Qualité and Système
  views;
- one shared acquisition status across Aujourd’hui, Prospection and Système;
- no fabricated metrics;
- optimistic assisted decisions and explicit, idempotent batch confirmation.

## Non-goals

- a staging console;
- a second customer dashboard;
- a generic admin panel;
- a multi-user back office;
- LangGraph or a new agent framework;
- a command center with decorative agent cards;
- direct VPS deployment from a pull request.
