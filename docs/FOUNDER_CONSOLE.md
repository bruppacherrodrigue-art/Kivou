# Kivou Founder Console

## Decision

Kivou has **one and only one** founder control surface:

`https://control.kivou.eu`

There is no permanent `control.staging.kivou.eu` console. Validation happens in tests, CI and local or ephemeral review before deployment. When production is ready, this single console is connected directly to production read models.

The console is not a route, skin or internal twin of the customer dashboard. It has its own frontend build, its own FastAPI process, its own hostname, its own access boundary and its own deployment directory.

## Operator

Cloudflare Access policy allows only:

`rodrigue.bruppacher@gmail.com`

No signup, invitation, customer session or local Founder password exists in V1.

## Security model

```text
Google identity
  -> Cloudflare Access policy
  -> Cloudflare Tunnel
  -> nginx on 127.0.0.1:8081
  -> Founder API on 127.0.0.1:8011
  -> production read models through a PostgreSQL read-only role
```

Defense in depth:

1. the hostname is behind Cloudflare Access;
2. the tunnel is the only external path to the loopback-only nginx vhost;
3. nginx overwrites `X-Kivou-Founder-Origin-Secret` with a local root-managed secret;
4. the API requires the Cloudflare assertion header, the authenticated email header and the proxy secret;
5. the configured email must exactly match the single operator;
6. the Founder API mounts no customer route and no write route;
7. PostgreSQL sessions start with `default_transaction_read_only=on`;
8. the database user receives CONNECT, USAGE and SELECT only;
9. each session verifies `SHOW transaction_read_only = on` before serving reads;
10. the Founder connection has a bounded statement timeout.

The origin secret is not a replacement for Cloudflare Access. It prevents direct calls to the local API from succeeding with forged Cloudflare headers.

## Repository layout

```text
frontend/founder/                 standalone React entrypoint
frontend/vite.founder.config.ts   separate Vite build -> frontend/dist-founder
src/signals/founder_api/          separate FastAPI application and read models
ops/nginx/kivou-founder-control.conf
ops/systemd/kivou-founder-api.service
ops/examples/founder-console.env.example
ops/examples/cloudflared-founder.yml.example
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

## Cloudflare setup

The domain can remain registered at Infomaniak while Cloudflare becomes the authoritative DNS provider.

Before enabling the route:

1. add `kivou.eu` to Cloudflare and copy all existing DNS and mail records;
2. change the authoritative nameservers at Infomaniak to the Cloudflare nameservers;
3. configure Google as a Cloudflare Access identity provider;
4. create a self-hosted Access application for `control.kivou.eu`;
5. create an Allow policy containing only `rodrigue.bruppacher@gmail.com`;
6. create a Cloudflare Tunnel and route `control.kivou.eu` to `http://127.0.0.1:8081`;
7. verify that an unauthenticated browser is stopped by Access before the VPS is reached.

Do not publish the nginx listener on `0.0.0.0`. It must remain bound to `127.0.0.1`.

## Origin secret

Generate one random value:

```bash
openssl rand -hex 32
```

Put it in `/etc/kivou/founder.env`:

```dotenv
KIVOU_FOUNDER_ORIGIN_SECRET=<same-random-value>
```

Create `/etc/kivou/founder-origin-secret.conf` as root:

```nginx
set $kivou_founder_origin_secret "<same-random-value>";
```

Permissions:

```bash
sudo chown root:kivou /etc/kivou/founder.env /etc/kivou/founder-origin-secret.conf
sudo chmod 0640 /etc/kivou/founder.env /etc/kivou/founder-origin-secret.conf
```

Never commit the generated value.

## Build and deploy contract

PRs never deploy.

Founder frontend build:

```bash
cd frontend
npm ci
npm test -- --run
npm run build:founder
```

The deployment copies `frontend/dist-founder/` atomically to `/srv/kivou-founder/frontend/` and installs the versioned systemd and nginx files through a candidate, validation and rollback procedure.

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
curl --fail -H 'Host: control.kivou.eu' http://127.0.0.1:8081/healthz
```

`/healthz` proves only that the Founder process is alive. The authenticated overview smoke test proves that the production read models and read-only database connection work.

The public smoke test must confirm:

- Cloudflare Access blocks every non-allowed identity;
- the allowed Google identity reaches the console;
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
- Cloudflare and Tunnel boundary;
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
