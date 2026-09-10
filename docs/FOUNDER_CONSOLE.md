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
  -> production read models through a PostgreSQL read-only role
```

Defense in depth:

1. only the dedicated `control.kivou.eu` nginx vhost serves the console over HTTPS;
2. nginx requires Basic Auth from the root-managed password file;
3. nginx overwrites `X-Kivou-Founder-Origin-Secret` with a local root-managed secret;
4. nginx overwrites `X-Kivou-Founder-User` with the authenticated Basic Auth username;
5. the API requires the proxy secret and the configured username must exactly match `rodrigue`;
6. the Founder API mounts no customer route and no write route;
7. PostgreSQL sessions start with `default_transaction_read_only=on`;
8. the database user receives CONNECT, USAGE and SELECT only;
9. each session verifies `SHOW transaction_read_only = on` before serving reads;
10. the Founder connection has a bounded statement timeout.

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

## V1 authority boundary

V1 is read-only. It may:

- load summaries and read models;
- filter or change a completed reporting week;
- display incidents and dead letters;
- display commercial, quality and operations metrics;
- show the current Hermes and Policy Gateway evidence;
- refresh the current snapshot.

V1 may not:

- approve or reject a campaign;
- pause or resume execution;
- change a policy;
- trigger a retry;
- operate the kill switch;
- edit a signal;
- write directly to PostgreSQL;
- call a customer mutation route;
- deploy code.

A future command layer must use an explicit Founder Command API, the Policy Gateway, idempotent commands and an audit trail. It must never grant the frontend direct database writes.

## Read-model semantics

The endpoint `GET /api/founder/overview` composes existing Kivou truth. It does not call Apollo, Instantly, Stripe, Hermes or any other provider while rendering the console.

### Vue du moment

Current operational health, unresolved attention count, current Hermes evidence and highest safe autonomy mode are evaluated at request time from durable local state.

Positive replies and paid accounts shown in the same summary are explicitly labelled as belonging to the selected **last completed business week**. They are not presented as same-day values.

### À traiter

The queue contains only:

- operational incidents whose state is not `RESOLVED`;
- acquisition dead letters whose status is `OPEN`.

Rows are whitelisted into a PII-minimal contract. No raw provider payload, email body, customer note or secret is returned.

### Business

The commercial panel reuses `WeeklyCommercialCockpitService` and its existing immutable contract:

- sent-minus-bounce remains labelled as a delivery proxy;
- MRR is kept per currency;
- incomplete revenue journeys remain visible as incomplete;
- M2 efficiency is shown only when the bounded evidence says `READY`;
- historical selection is limited to 52 completed weeks.

### Qualité

The first quality panel is intentionally modest. It counts the **current feedback rows whose last update falls inside the trailing 30-day window**. It is not a complete append-only history of every opinion ever submitted.

It reports:

- current feedback updated in the window;
- relevant and not-relevant states;
- contacts declared during the window;
- negative share among feedback updated in the window;
- structured negative reasons;
- unresolved commercial sectors and incomplete MRR journeys.

Customer feedback remains separate from public facts and engine inferences. The console never rewrites the Need Graph, scoring or ICP from a negative click.

### Système

The system panel reuses `OperationsReadService`:

- API and database health;
- Hermes runtime and supervisor loop;
- Policy Gateway;
- campaign execution;
- dead-letter queue;
- circuit breakers;
- readiness gates and blockers;
- highest safe autonomy mode.

The UI shows only the agent actually implemented: **Hermes Acquisition Supervisor**. Future agent cards are added only when a real read model exists behind them.

## PostgreSQL read-only role

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

Verification before service start:

```bash
sudo -u kivou /srv/kivou/app/.venv/bin/python - <<'PY'
from signals.founder_api.database import create_founder_database_engine

engine = create_founder_database_engine()
with engine.connect() as connection:
    assert connection.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
    print("Founder database session: read-only")
PY
```

A non-PostgreSQL URL is refused by the production Founder entrypoint.

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
ACME_RESPONSE="$(curl --fail --silent --show-error --write-out '\n%{http_code}' \
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
deployment candidate installs `ops/nginx/kivou-founder-control.conf`, validates
it with `nginx -t` and reloads nginx only after validation succeeds:

```bash
sudo rm -- /etc/nginx/sites-enabled/kivou-founder-bootstrap.conf
sudo rm -- /etc/nginx/sites-available/kivou-founder-bootstrap.conf
KIVOU_RELEASE_SHA="$(git rev-parse HEAD)"
sudo /srv/kivou/source/ops/bin/kivou-deploy.sh production "$KIVOU_RELEASE_SHA"
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

Deployment is performed by `ops/bin/kivou-deploy.sh`. It copies
`frontend/dist-founder/` atomically to `/srv/kivou-founder/frontend/` and
installs the versioned systemd and nginx files through a candidate, validation
and rollback procedure.

Backend gate:

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
```

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

- the console says `Production` and `Lecture seule`;
- customer login cookies are neither required nor accepted as Founder authorization;
- customer routes are not reachable through the Founder host;
- no `/internal/*` route is exposed by the Founder vhost;
- the completed-week labels match the returned business period;
- no action button capable of changing Kivou exists.

## Two-PR delivery

### PR 1 — Foundation

- independent frontend build;
- independent FastAPI process;
- direct HTTPS boundary with nginx Basic Auth;
- one production hostname;
- French-only foundation UI;
- read-only session contract;
- versioned nginx, systemd and runbook;
- removal of the cockpit route from the customer SaaS;
- no data read model and no command.

### PR 2 — Production read models

- production database connection through a dedicated read-only role;
- Vue du moment, À traiter, Business, Qualité and Système views;
- Hermes and Policy Gateway status derived from durable evidence;
- no fabricated metrics;
- no write action.

## Non-goals

- a staging console;
- a second customer dashboard;
- a generic admin panel;
- a multi-user back office;
- LangGraph or a new agent framework;
- a command center with decorative agent cards;
- direct VPS deployment from a pull request.
