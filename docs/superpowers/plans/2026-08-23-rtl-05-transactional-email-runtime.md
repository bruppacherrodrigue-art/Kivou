# RTL-05 Transactional Email Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Kivou password-reset emails and account signal alerts reproducible, securely configured, durably retried, concurrency-safe, and installable as a versioned staging runtime.

**Architecture:** Keep password resets as one-shot post-response deliveries so no usable reset secret enters an outbox. Add strict public-origin and SMTP configuration, a shared link builder and hardened SMTP transport. For alerts, add an additive delivery schema plus a database lease, persist a stable logical batch before network I/O, revalidate access before every attempt, and apply bounded retries with an honest SMTP ambiguity boundary.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Alembic, SQLite/PostgreSQL dialects, `smtplib`, pytest, aiosmtpd/trustme test fixtures, systemd, util-linux `flock`, Ruff, React/Vite regression checks.

---

## File map

### New files

- `src/signals/transactional_email/__init__.py` — narrow shared boundary for transactional links.
- `src/signals/transactional_email/links.py` — validated origin and reset/signal/preference URL construction.
- `src/signals/alerts/lease.py` — database-backed singleton job lease.
- `src/signals/alerts/delivery.py` — durable alert batch state transitions and retry scheduling.
- `src/signals/persistence/migrations/versions/0023_transactional_email_runtime.py` — additive lease and alert-delivery migration.
- `tests/test_transactional_email_config.py` — URL and SMTP environment contract.
- `tests/test_smtp_gateway.py` — SMTP classification, TLS and loopback-server integration.
- `tests/test_transactional_email_migration.py` — SQLite roundtrip and offline PostgreSQL SQL.
- `tests/test_alert_job_lease.py` — sequential, concurrent and expired lease behavior.
- `tests/test_alert_delivery_runtime.py` — retries, stale attempts, suppression and ambiguity.
- `tests/test_alerts_cli.py` — environment-only CLI and current-run exit codes.
- `tests/test_ops_alerts_runtime.py` — versioned service/timer and host lock semantics.
- `ops/systemd/kivou-alerts.service` — versioned one-shot service.
- `ops/systemd/kivou-alerts.timer` — persistent hourly timer.
- `docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md` — redacted technical delivery report and staging/rollback runbook.

### Modified files

- `pyproject.toml`, `uv.lock` — local SMTP/TLS test dependencies only.
- `.env.example` — exact non-secret public-origin, SMTP and retry variables.
- `src/signals/api/config.py` — strict environment parsing and bounded runtime settings.
- `src/signals/api/asgi.py` — pass the validated SMTP configuration to reset delivery.
- `src/signals/accounts/reset_delivery.py` — shared reset link builder and optional safe `Reply-To` transport behavior.
- `src/signals/alerts/gateway.py` — explicit TLS modes, timeout and safe error classification.
- `src/signals/alerts/job.py` — lease orchestration, durable batch selection, revalidation and current-run reporting.
- `src/signals/alerts/cli.py` — database URL from environment and meaningful exit codes.
- `src/signals/alerts/__init__.py` — export the closed runtime contracts.
- `src/signals/engagement/schema.py` — SQLAlchemy metadata matching migration `0023`.
- `tests/engagement_helpers.py` — root-origin fixture and failure-aware fake mailer.
- `tests/test_alerts_cycle.py` — adapt established alert behavior to durable retries and `/app` deep links.
- `tests/test_api_runtime.py` — reset wiring and strict SMTP configuration.
- `tests/test_accounts_security.py` — preserve reset enumeration, expiry and single-use protections.
- `tests/test_engagement_secrets.py` — enforce new persisted-field and log privacy constraints.
- `tests/test_persistence_migrations.py` — expect the new Alembic head if this aggregate test pins it.
- `ops/README.md` — install, manual execution, observability and rollback.
- `docs/ROAD_TO_LIVE.md` — RTL-05 only, and only after the draft PR exists.
- `docs/superpowers/specs/2026-08-23-rtl-05-transactional-email-runtime-design.md` — implementation evidence/status only after validation.

No frontend source file is expected to change: `/reset-password`,
`/app/signals/:signalKey` and `/app/notifications` already exist. Their existing
tests remain regression gates.

---

### Task 1: Strict public origin and SMTP configuration

**Files:**
- Create: `src/signals/transactional_email/__init__.py`
- Create: `src/signals/transactional_email/links.py`
- Create: `tests/test_transactional_email_config.py`
- Modify: `src/signals/api/config.py`
- Modify: `.env.example`
- Modify: `tests/engagement_helpers.py`

- [ ] **Step 1: Write failing public-origin and link tests**

Add tests that pin an origin-only contract and never use request data:

```python
def configure_complete_smtp(monkeypatch) -> None:
    values = {
        "KIVOU_ALLOWED_ORIGIN": "https://staging.kivou.test",
        "KIVOU_PUBLIC_APP_URL": "https://staging.kivou.test",
        "SMTP_HOST": "smtp.kivou.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "sender@kivou.test",
        "SMTP_PASSWORD": "smtp-secret",
        "SMTP_FROM_EMAIL": "no-reply@kivou.test",
        "SMTP_FROM_NAME": "Kivou",
        "SMTP_TLS_MODE": "starttls",
        "SMTP_TIMEOUT_SECONDS": "12",
        "SMTP_REPLY_TO_EMAIL": "support@kivou.test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "value",
    [
        "http://staging.kivou.eu",
        "https://user:secret@staging.kivou.eu",
        "https://staging.kivou.eu/app",
        "https://staging.kivou.eu?next=https://evil.example",
        "https://staging.kivou.eu#fragment",
    ],
)
def test_public_origin_rejects_unsafe_values(monkeypatch, value):
    monkeypatch.setenv("KIVOU_ALLOWED_ORIGIN", "https://staging.kivou.eu")
    monkeypatch.setenv("KIVOU_PUBLIC_APP_URL", value)
    with pytest.raises(ValueError, match="KIVOU_PUBLIC_APP_URL"):
        ApiConfig.from_environment()


def test_public_origin_must_match_the_allowed_deployment_origin(monkeypatch):
    monkeypatch.setenv("KIVOU_ALLOWED_ORIGIN", "https://kivou.eu")
    monkeypatch.setenv("KIVOU_PUBLIC_APP_URL", "https://staging.kivou.eu")
    with pytest.raises(ValueError, match="origine autorisée"):
        ApiConfig.from_environment()


def test_transactional_links_add_their_own_routes():
    origin = "https://staging.kivou.eu"
    assert reset_url(origin, "a+b") == (
        "https://staging.kivou.eu/reset-password?token=a%2Bb"
    )
    assert signal_url(origin, "sig_opaque") == (
        "https://staging.kivou.eu/app/signals/sig_opaque"
    )
    assert preferences_url(origin) == "https://staging.kivou.eu/app/notifications"
```

- [ ] **Step 2: Run the link tests and verify RED**

Run:

```bash
uv run pytest tests/test_transactional_email_config.py -q
```

Expected: failures because the shared link module and strict validation do not
exist and the current configuration accepts an `/app` path.

- [ ] **Step 3: Implement the shared link boundary and origin normalization**

Create a link module with this closed interface:

```python
from urllib.parse import quote, urlsplit


def normalize_public_origin(value: str, *, allowed_origin: str | None) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("KIVOU_PUBLIC_APP_URL doit être une origine https sans chemin")
    normalized = f"https://{parsed.netloc}"
    if allowed_origin is None or normalized != allowed_origin.rstrip("/"):
        raise ValueError("KIVOU_PUBLIC_APP_URL doit correspondre à l'origine autorisée")
    return normalized


def reset_url(origin: str, token: str) -> str:
    return f"{origin}/reset-password?token={quote(token, safe='')}"


def signal_url(origin: str, signal_key: str) -> str:
    return f"{origin}/app/signals/{quote(signal_key, safe='')}"


def preferences_url(origin: str) -> str:
    return f"{origin}/app/notifications"
```

Wire the helper from `ApiConfig.from_environment()` after parsing
`KIVOU_ALLOWED_ORIGIN`. Keep `public_app_url` as the existing Python field name
but change its documented meaning to the normalized origin. Make
`public_site_url` a compatibility property returning that same origin.

- [ ] **Step 4: Write failing SMTP-contract tests**

Cover complete, absent and partial configuration, credential pairing, timeout,
port, TLS mode, sender validation and secret-safe representation:

```python
def test_complete_smtp_configuration(monkeypatch):
    configure_complete_smtp(monkeypatch)
    config = ApiConfig.from_environment()
    assert config.smtp_tls_mode == "starttls"
    assert config.smtp_timeout_seconds == 12
    assert config.smtp_reply_to_email == "support@kivou.test"
    assert "smtp-secret" not in repr(config)


@pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_FROM_EMAIL", "SMTP_TLS_MODE"])
def test_partial_smtp_configuration_fails_closed(monkeypatch, missing):
    configure_complete_smtp(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match="configuration SMTP incomplète"):
        ApiConfig.from_environment()


def test_username_and_password_are_required_as_a_pair(monkeypatch):
    configure_complete_smtp(monkeypatch)
    monkeypatch.delenv("SMTP_PASSWORD")
    with pytest.raises(ValueError, match="ensemble"):
        ApiConfig.from_environment()


@pytest.mark.parametrize("mode", ["none", "tls", "false", ""])
def test_deployed_smtp_has_no_unencrypted_mode(monkeypatch, mode):
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_TLS_MODE", mode)
    with pytest.raises(ValueError, match="SMTP_TLS_MODE"):
        ApiConfig.from_environment()
```

- [ ] **Step 5: Run the SMTP configuration tests and verify RED**

Run the same test file. Expected: missing fields and validators.

- [ ] **Step 6: Implement the exact environment contract**

Replace `SMTP_USE_TLS` with:

```python
SMTP_TLS_MODE_ENV = "SMTP_TLS_MODE"
SMTP_TIMEOUT_ENV = "SMTP_TIMEOUT_SECONDS"
SMTP_REPLY_TO_ENV = "SMTP_REPLY_TO_EMAIL"
ALERT_LEASE_SECONDS_ENV = "KIVOU_ALERT_LEASE_SECONDS"
ALERT_MAX_ATTEMPTS_ENV = "KIVOU_ALERT_MAX_ATTEMPTS"
ALERT_RETRY_BASE_SECONDS_ENV = "KIVOU_ALERT_RETRY_BASE_SECONDS"
```

Add fields with bounded defaults:

```python
smtp_tls_mode: str = "starttls"
smtp_timeout_seconds: float = 30.0
smtp_reply_to_email: str | None = None
alert_lease_ttl: dt.timedelta = dt.timedelta(minutes=30)
alert_max_attempts: int = 5
alert_retry_base: dt.timedelta = dt.timedelta(minutes=15)
```

Mark `smtp_password` as `dataclasses.field(default=None, repr=False)`. Validate
port `1..65535`, timeout `1..60`, lease `60..3600`, attempts `1..10`, retry base
`60..86400`, `starttls|implicit_tls`, email syntax and the username/password
pair. If every SMTP variable is absent, leave delivery disabled. If any SMTP
variable is present, require the complete contract including the public origin.

- [ ] **Step 7: Update `.env.example` and the shared test origin**

Document non-secret examples only:

```dotenv
KIVOU_PUBLIC_APP_URL=https://kivou.eu
SMTP_HOST=smtp.example.test
SMTP_PORT=587
SMTP_USERNAME=transactional@example.test
SMTP_PASSWORD=replace_outside_git
SMTP_FROM_EMAIL=transactional@example.test
SMTP_FROM_NAME=Kivou
SMTP_TLS_MODE=starttls
SMTP_TIMEOUT_SECONDS=30
SMTP_REPLY_TO_EMAIL=
KIVOU_ALERT_LEASE_SECONDS=1800
KIVOU_ALERT_MAX_ATTEMPTS=5
KIVOU_ALERT_RETRY_BASE_SECONDS=900
```

Change `tests/engagement_helpers.py::PUBLIC_APP_URL` to
`https://kivou.test`; link tests must expect `/app/signals/{signal_key}` from
the builder.

- [ ] **Step 8: Run focused tests and commit**

```bash
uv run pytest tests/test_transactional_email_config.py tests/test_api_runtime.py -q
uv run ruff check src/signals/api/config.py src/signals/transactional_email tests/test_transactional_email_config.py
git add .env.example src/signals/api/config.py src/signals/transactional_email tests/test_transactional_email_config.py tests/engagement_helpers.py tests/test_api_runtime.py
git commit -m "feat(email): validate transactional delivery configuration"
```

Expected: all focused tests pass; no secret value appears in the diff.

---

### Task 2: Hardened SMTP gateway and local integration server

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/signals/alerts/gateway.py`
- Modify: `src/signals/api/asgi.py`
- Modify: `src/signals/accounts/reset_delivery.py`
- Create: `tests/test_smtp_gateway.py`
- Modify: `tests/test_api_runtime.py`

- [ ] **Step 1: Add local-only SMTP test dependencies**

Run:

```bash
uv add --dev "aiosmtpd>=1.4.6" "trustme>=1.2"
```

These packages are test-only. No production mail provider SDK is added.

- [ ] **Step 2: Write RED tests for STARTTLS, implicit TLS and headers**

Build a loopback fixture using `aiosmtpd.controller.Controller` and a
`trustme` CA. It must bind only to `127.0.0.1`, capture bytes in memory, and
never use a public recipient:

```python
class CapturingHandler:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope.content)
        return "250 accepted"


@pytest.fixture
def starttls_server():
    ca = trustme.CA()
    certificate = ca.issue_cert("127.0.0.1")
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(server_context)
    client_context = ssl.create_default_context()
    ca.configure_trust(client_context)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    handler = CapturingHandler()
    controller = Controller(
        handler,
        hostname="127.0.0.1",
        port=port,
        tls_context=server_context,
        require_starttls=True,
    )
    controller.start()
    try:
        yield types.SimpleNamespace(
            port=port,
            messages=handler.messages,
            client_context=client_context,
        )
    finally:
        controller.stop()


def sample_message() -> AlertMessage:
    return AlertMessage(
        to_email="recipient@kivou.test",
        subject="Test transactionnel",
        text_body="Message synthétique",
        message_id="<test-transactional@kivou.test>",
        language="fr",
    )


def configuration(**overrides) -> SmtpConfiguration:
    values = {
        "host": "smtp.kivou.test",
        "port": 587,
        "from_email": "no-reply@kivou.test",
        "tls_mode": "starttls",
        "timeout_seconds": 3.0,
    }
    values.update(overrides)
    return SmtpConfiguration(**values)


class RecordingSmtp:
    def __init__(self, host, port, *, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, *, context):
        return 220, b"ready"

    def login(self, username, password):
        raise AssertionError("ce test n'active pas l'authentification")

    def send_message(self, message):
        return {}


class RecordingSmtpSsl:
    calls: list[tuple[str, int, float]] = []

    def __init__(self, host, port, *, timeout, context):
        self.calls.append((host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, username, password):
        raise AssertionError("ce test n'active pas l'authentification")

    def send_message(self, message):
        return {}


def test_starttls_delivers_once_to_the_loopback_server(starttls_server):
    gateway = SmtpAlertGateway(
        SmtpConfiguration(
            host="127.0.0.1",
            port=starttls_server.port,
            from_email="no-reply@kivou.test",
            tls_mode="starttls",
            timeout_seconds=2,
            reply_to_email="support@kivou.test",
        ),
        ssl_context=starttls_server.client_context,
    )
    gateway.send(sample_message())
    assert len(starttls_server.messages) == 1
    parsed = email.message_from_bytes(starttls_server.messages[0])
    assert parsed["Reply-To"] == "support@kivou.test"
    assert parsed["Message-ID"] == sample_message().message_id


def test_implicit_tls_uses_smtp_ssl(monkeypatch):
    RecordingSmtpSsl.calls.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSmtpSsl)
    gateway = SmtpAlertGateway(configuration(tls_mode="implicit_tls"))
    gateway.send(sample_message())
    assert RecordingSmtpSsl.calls == [("smtp.kivou.test", 465, 3.0)]
```

- [ ] **Step 3: Write RED classification and privacy tests**

```python
@pytest.mark.parametrize("code,retryable", [(451, True), (550, False)])
def test_smtp_response_classification(code, retryable, monkeypatch):
    class FailingSmtp(RecordingSmtp):
        def send_message(self, message):
            raise smtplib.SMTPDataError(code, b"private response")

    monkeypatch.setattr(smtplib, "SMTP", FailingSmtp)
    with pytest.raises(AlertDeliveryError) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())
    assert raised.value.retryable is retryable
    assert "private" not in str(raised.value)


def test_disconnect_during_message_submission_is_ambiguous(monkeypatch):
    class DisconnectingSmtp(RecordingSmtp):
        def send_message(self, message):
            raise smtplib.SMTPServerDisconnected("private")

    monkeypatch.setattr(smtplib, "SMTP", DisconnectingSmtp)
    with pytest.raises(UncertainDelivery):
        SmtpAlertGateway(configuration()).send(sample_message())


def test_smtp_configuration_repr_never_contains_the_password():
    configured = configuration(password="smtp-secret-never-log")
    assert "smtp-secret-never-log" not in repr(configured)
```

- [ ] **Step 4: Run gateway tests and verify RED**

```bash
uv run pytest tests/test_smtp_gateway.py -q
```

Expected: failures for the new constructor, TLS modes, timeout and error
classification.

- [ ] **Step 5: Implement the minimal hardened gateway**

Change the transport configuration to:

```python
@dataclasses.dataclass(frozen=True)
class SmtpConfiguration:
    host: str
    port: int
    from_email: str
    from_name: str = "Kivou"
    username: str | None = None
    password: str | None = dataclasses.field(default=None, repr=False)
    tls_mode: Literal["starttls", "implicit_tls"] = "starttls"
    timeout_seconds: float = 30.0
    reply_to_email: str | None = None
```

Open `smtplib.SMTP_SSL` for implicit TLS and `smtplib.SMTP` followed by
`starttls(context=self._ssl_context)` for STARTTLS. Catch authentication, recipient, TLS,
4xx/5xx and connection errors separately. Connection failures before
`send_message` are retryable; disconnect/timeout during `send_message` raises
`UncertainDelivery`. Persist/log only fixed error codes.

Set `Reply-To` only when configured and preserve `Auto-Submitted` and the
deterministic `Message-ID`.

- [ ] **Step 6: Wire reset delivery to the validated configuration**

Update `src/signals/api/asgi.py::_password_reset_delivery` to pass TLS mode,
timeout and Reply-To. Replace reset URL construction in
`src/signals/accounts/reset_delivery.py` with `transactional_email.links.reset_url`.
Keep `deliver()` exception-neutral so known and unknown accounts remain
indistinguishable.

- [ ] **Step 7: Run focused tests and commit**

```bash
uv run pytest tests/test_smtp_gateway.py tests/test_api_runtime.py tests/test_accounts_security.py -q
uv run ruff check src/signals/alerts/gateway.py src/signals/accounts/reset_delivery.py src/signals/api/asgi.py tests/test_smtp_gateway.py
git add pyproject.toml uv.lock src/signals/alerts/gateway.py src/signals/accounts/reset_delivery.py src/signals/api/asgi.py tests/test_smtp_gateway.py tests/test_api_runtime.py
git commit -m "feat(email): harden SMTP transactional transport"
```

---

### Task 3: Additive `0023` delivery runtime migration

**Files:**
- Create: `src/signals/persistence/migrations/versions/0023_transactional_email_runtime.py`
- Modify: `src/signals/engagement/schema.py`
- Create: `tests/test_transactional_email_migration.py`
- Modify: `tests/test_persistence_migrations.py`
- Modify: `tests/test_engagement_secrets.py`

- [ ] **Step 1: Write RED migration shape and roundtrip tests**

```python
PREVIOUS = "0022_saas_company_profile"
HEAD = "0023_transactional_email_runtime"


def sqlite_engine(tmp_path):
    return create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'transactional-email.db'}"
    )


def seeded_previous_schema(tmp_path, *, status: str, error: str | None = None):
    engine = sqlite_engine(tmp_path)
    command.upgrade(alembic_config(engine), PREVIOUS)
    now = dt.datetime(2026, 8, 23, 10, 0, tzinfo=dt.UTC)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(account).values(
                account_id="acc_migration",
                display_name="Migration",
                locale="fr",
                onboarding_status="ready_for_signals",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            sa.insert(signal_alert_delivery).values(
                account_id="acc_migration",
                signal_key="sig_migration",
                status=status,
                cadence="daily",
                queued_at=now,
                sent_at=now if status == "sent" else None,
                failed_at=now if status != "sent" else None,
                attempt_count=1,
                provider_message_id=None,
                last_error_code=error,
                created_at=now,
                updated_at=now,
            )
        )
    return engine


def read_delivery(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(signal_alert_delivery)).one()


def read_status(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT status FROM signal_alert_delivery")
        ).scalar_one()


def test_transactional_email_migration_is_the_single_head(tmp_path):
    engine = sqlite_engine(tmp_path)
    config = alembic_config(engine)
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, HEAD)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [HEAD]
    assert "signal_alert_job_lease" in sa.inspect(engine).get_table_names()


def test_historical_failures_become_terminal_without_parsing_error_text(tmp_path):
    engine = seeded_previous_schema(tmp_path, status="failed", error="smtp_451")
    command.upgrade(alembic_config(engine), HEAD)
    row = read_delivery(engine)
    assert row.retryable is False
    assert row.next_attempt_at is None


def test_migration_roundtrip_preserves_existing_delivery_history(tmp_path):
    engine = seeded_previous_schema(tmp_path, status="sent")
    config = alembic_config(engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    assert read_status(engine) == "sent"
    command.upgrade(config, HEAD)
    assert current_revision(engine) == HEAD
```

- [ ] **Step 2: Write RED offline PostgreSQL assertions**

Render `0022:0023` with `sql=True` and assert one lease table, additive columns,
indexes, status check including `suppressed`, and no private payload columns.

- [ ] **Step 3: Run migration tests and verify RED**

```bash
uv run pytest tests/test_transactional_email_migration.py tests/test_persistence_migrations.py -q
```

Expected: missing revision/table/columns.

- [ ] **Step 4: Add matching SQLAlchemy schema**

Add `signal_alert_job_lease`:

```python
signal_alert_job_lease = sa.Table(
    "signal_alert_job_lease",
    METADATA,
    sa.Column("job_name", sa.String(64), primary_key=True),
    sa.Column("owner_token", sa.String(64), nullable=False),
    sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
```

Extend `signal_alert_delivery` with nullable migration-safe columns:
`batch_key`, `delivery_message_id`, `retryable`, `attempt_started_at`,
`lease_expires_at`, `next_attempt_at`, `suppressed_at`, and
`suppression_reason_code`. Add the closed status check:

```sql
status IN ('queued','sending','sent','failed','unknown_delivery_state','suppressed')
```

- [ ] **Step 5: Implement upgrade/downgrade and historical backfill**

The upgrade adds columns/indexes/table, sets `retryable = false` and
`next_attempt_at = NULL` for every pre-existing `failed` or
`unknown_delivery_state` row, regardless of `last_error_code`, then creates the
status check using Alembic batch operations where SQLite requires table
recreation. Downgrade drops only new columns/indexes/check/table and retains the
original delivery rows and columns.

- [ ] **Step 6: Extend privacy schema tests**

Assert that neither table has columns named `password`, `token`, `recipient`,
`email`, `payload`, `body`, `trace` or `credential` and that migration SQL
contains no acquisition/provider surface.

- [ ] **Step 7: Run migration tests and commit**

```bash
uv run pytest tests/test_transactional_email_migration.py tests/test_persistence_migrations.py tests/test_engagement_secrets.py -q
uv run ruff check src/signals/engagement/schema.py src/signals/persistence/migrations/versions/0023_transactional_email_runtime.py tests/test_transactional_email_migration.py
git add src/signals/engagement/schema.py src/signals/persistence/migrations/versions/0023_transactional_email_runtime.py tests/test_transactional_email_migration.py tests/test_persistence_migrations.py tests/test_engagement_secrets.py
git commit -m "feat(email): persist transactional alert runtime state"
```

---

### Task 4: Database job lease

**Files:**
- Create: `src/signals/alerts/lease.py`
- Create: `tests/test_alert_job_lease.py`
- Modify: `src/signals/alerts/__init__.py`

- [ ] **Step 1: Write RED sequential and expired-lease tests**

```python
def test_second_owner_observes_normal_contention(engine):
    with engine.begin() as connection:
        first = acquire(connection, owner_token="one", now=NOW, ttl=TTL)
    with engine.begin() as connection:
        second = acquire(connection, owner_token="two", now=NOW, ttl=TTL)
    assert first is LeaseAcquisition.ACQUIRED
    assert second is LeaseAcquisition.ALREADY_RUNNING


def test_expired_lease_is_reclaimed(engine):
    with engine.begin() as connection:
        acquire(connection, owner_token="one", now=NOW, ttl=TTL)
    with engine.begin() as connection:
        result = acquire(connection, owner_token="two", now=NOW + TTL, ttl=TTL)
    assert result is LeaseAcquisition.ACQUIRED
```

- [ ] **Step 2: Write RED concurrent acquisition test**

Use two threads, a barrier and two independent connections. Assert exactly one
`ACQUIRED`, one `ALREADY_RUNNING`, no exception and one persisted lease owner.

- [ ] **Step 3: Run lease tests and verify RED**

```bash
uv run pytest tests/test_alert_job_lease.py -q
```

- [ ] **Step 4: Implement atomic acquire/release**

Expose:

```python
class LeaseAcquisition(enum.StrEnum):
    ACQUIRED = "acquired"
    ALREADY_RUNNING = "already_running"


def acquire(
    connection: sa.Connection,
    *,
    owner_token: str,
    now: dt.datetime,
    ttl: dt.timedelta,
    job_name: str = "signals.alerts",
) -> LeaseAcquisition:
    expires_at = now + ttl
    updated = connection.execute(
        sa.update(signal_alert_job_lease)
        .where(
            signal_alert_job_lease.c.job_name == job_name,
            signal_alert_job_lease.c.lease_expires_at <= now,
        )
        .values(
            owner_token=owner_token,
            acquired_at=now,
            lease_expires_at=expires_at,
            updated_at=now,
        )
    )
    if updated.rowcount == 1:
        return LeaseAcquisition.ACQUIRED
    try:
        with connection.begin_nested():
            connection.execute(
                sa.insert(signal_alert_job_lease).values(
                    job_name=job_name,
                    owner_token=owner_token,
                    acquired_at=now,
                    lease_expires_at=expires_at,
                    updated_at=now,
                )
            )
    except sa.exc.IntegrityError:
        return LeaseAcquisition.ALREADY_RUNNING
    return LeaseAcquisition.ACQUIRED


def release(
    connection: sa.Connection,
    *,
    owner_token: str,
    job_name: str = "signals.alerts",
) -> None:
    connection.execute(
        sa.delete(signal_alert_job_lease).where(
            signal_alert_job_lease.c.job_name == job_name,
            signal_alert_job_lease.c.owner_token == owner_token,
        )
    )
```

Acquire first updates an expired row with a compare-and-set. If no row updates,
attempt an insert inside a nested transaction; unique conflict means
`ALREADY_RUNNING`, not an error. Unexpected database errors propagate. Release
deletes only the row owned by the current process. Generate owner tokens with
`secrets.token_hex(16)`; never log them.

- [ ] **Step 5: Run tests and commit**

```bash
uv run pytest tests/test_alert_job_lease.py -q
uv run ruff check src/signals/alerts/lease.py tests/test_alert_job_lease.py
git add src/signals/alerts/lease.py src/signals/alerts/__init__.py tests/test_alert_job_lease.py
git commit -m "feat(email): serialize alert jobs with database leases"
```

---

### Task 5: Durable batches, retries and SMTP ambiguity

**Files:**
- Create: `src/signals/alerts/delivery.py`
- Create: `tests/test_alert_delivery_runtime.py`
- Modify: `src/signals/alerts/job.py`
- Modify: `src/signals/alerts/policy.py`
- Modify: `src/signals/alerts/__init__.py`
- Modify: `tests/test_alerts_cycle.py`
- Modify: `tests/engagement_helpers.py`

- [ ] **Step 1: Write RED deterministic retry tests**

```python
def test_retryable_failure_uses_backoff_and_the_same_message_id(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = AlertDeliveryError("smtp_451", retryable=True)
    first = cycle(engine, mailer, now=NOW)
    row = deliveries(engine)[0]
    first_message_id = row.delivery_message_id
    assert first.has_current_incident
    assert row.status == "failed"
    assert row.retryable is True
    assert row.next_attempt_at == NOW + dt.timedelta(minutes=15)

    cycle(engine, mailer, now=NOW + dt.timedelta(minutes=14))
    assert mailer.sent == []
    cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15))
    assert mailer.last.message_id == first_message_id
    assert deliveries(engine)[0].status == "sent"


def test_permanent_failure_is_terminal(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = AlertDeliveryError("smtp_550", retryable=False)
    cycle(engine, mailer, now=NOW)
    cycle(engine, mailer, now=NOW + dt.timedelta(days=1))
    assert mailer.attempts == 1
    assert deliveries(engine)[0].retryable is False
```

- [ ] **Step 2: Write RED stale sending and bounded-attempt tests**

```python
def test_expired_sending_lease_is_reclaimed_with_same_message_id(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = AlertDeliveryError("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(signal_alert_delivery).values(
                status="sending",
                lease_expires_at=NOW,
                next_attempt_at=None,
            )
        )
    expected = deliveries(engine)[0].delivery_message_id
    cycle(engine, mailer, now=NOW)
    assert mailer.last.message_id == expected
    assert deliveries(engine)[0].attempt_count == 2


def test_retry_budget_is_bounded(app, engine, mailer):
    subscriber(app, engine, plan="scale", count=1)
    instants = [
        NOW,
        NOW + dt.timedelta(minutes=15),
        NOW + dt.timedelta(minutes=45),
        NOW + dt.timedelta(minutes=105),
        NOW + dt.timedelta(minutes=225),
    ]
    for instant in instants:
        mailer.fail_with = AlertDeliveryError("smtp_451", retryable=True)
        cycle(engine, mailer, now=instant)
    row = deliveries(engine)[0]
    assert row.attempt_count == 5
    assert row.retryable is False
    assert row.next_attempt_at is None
```

- [ ] **Step 3: Write RED post-accept persistence-failure test**

Patch `signals.alerts.delivery.mark_sent` to raise
`sa.exc.OperationalError("UPDATE", {}, RuntimeError("synthetic"))` after the
fake gateway records the message. Assert the row remains `sending`; after lease
expiry, restore `mark_sent`, retry and assert both recorded calls use the same
`Message-ID`. The assertion names the two accepted calls as the documented
possible duplicate and never labels the behavior exactly-once.

- [ ] **Step 4: Run focused tests and verify RED**

```bash
uv run pytest tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py -q
```

- [ ] **Step 5: Implement batch identity and state transitions**

`delivery.py` owns these operations:

```python
@dataclasses.dataclass(frozen=True)
class DeliveryBatch:
    account_id: str
    signal_keys: tuple[str, ...]
    batch_key: str
    message_id: str
    attempt_count: int


def logical_batch_key(account_id: str, signal_keys: Iterable[str]) -> str:
    canonical = ":".join(sorted(signal_keys))
    return hashlib.sha256(f"{account_id}:{canonical}".encode()).hexdigest()[:40]


def retry_delay(base: dt.timedelta, attempt_count: int) -> dt.timedelta:
    return min(base * (2 ** max(0, attempt_count - 1)), dt.timedelta(days=1))
```

Add `queue_batch`, `next_due_batch`, `mark_sending`, `mark_sent`,
`mark_failed`, `mark_unknown` and `mark_suppressed`. `mark_sending` increments
the attempt before network I/O and commits an attempt lease. Finalizers update
only rows whose batch key and message ID still match.

Prioritize an existing due batch before adding new signals. Never add a new
signal to a retry batch. Queue at most one new batch per account/cycle, using at
most `MAXIMUM_SIGNALS_PER_EMAIL` signals.

Extend `tests/engagement_helpers.py::FakeMailer` with a counter that increments
before either failure or success:

```python
attempts: int = 0

def send(self, message: AlertMessage) -> DeliveryResult:
    self.attempts += 1
    if self.fail_with is not None:
        error, self.fail_with = self.fail_with, None
        raise error
    self.sent.append(message)
    return DeliveryResult(provider_message_id=message.message_id)
```

- [ ] **Step 6: Orchestrate the global lease and current-run report**

Extend the report with closed execution semantics:

```python
@dataclasses.dataclass(frozen=True)
class CycleReport:
    accounts_considered: int
    outcomes: tuple[AlertOutcome, ...]
    execution_status: str = "completed"

    @property
    def already_running(self) -> bool:
        return self.execution_status == "already_running"

    @property
    def has_current_incident(self) -> bool:
        return any(
            item.result in {"failed", "unknown_delivery_state", "persistence_failed"}
            for item in self.outcomes
        )
```

Acquire the job lease before enumerating accounts and release it in `finally`.
Return an empty `already_running` report for normal contention. Let technical
database failures propagate. Historical terminal rows are never converted into
current outcomes.

- [ ] **Step 7: Update existing tests for bounded ambiguity**

Replace the old assertion that uncertain delivery is retried immediately on
every cycle. Assert no retry before `next_attempt_at`, bounded retries after it,
stable Message-ID and terminal exhaustion.

- [ ] **Step 8: Run tests and commit**

```bash
uv run pytest tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py tests/test_alert_job_lease.py -q
uv run ruff check src/signals/alerts tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py
git add src/signals/alerts tests/engagement_helpers.py tests/test_alerts_cycle.py tests/test_alert_delivery_runtime.py
git commit -m "feat(email): add bounded durable alert retries"
```

---

### Task 6: Revalidation and terminal suppression

**Files:**
- Modify: `src/signals/alerts/delivery.py`
- Modify: `src/signals/alerts/job.py`
- Modify: `tests/test_alert_delivery_runtime.py`
- Modify: `tests/test_alerts_cycle.py`

- [ ] **Step 1: Write RED preference and entitlement suppression tests**

```python
def test_retry_is_suppressed_when_notifications_are_disabled(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = AlertDeliveryError("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    attempts = deliveries(engine)[0].attempt_count
    client.patch("/notification-preferences", json={"email_enabled": False})

    report = cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15))
    row = deliveries(engine)[0]
    assert row.status == "suppressed"
    assert row.suppression_reason_code == "notifications_disabled"
    assert row.attempt_count == attempts
    assert not report.has_current_incident


def test_retry_is_suppressed_when_entitlement_is_lost(app, engine, mailer):
    client, _ = subscriber(app, engine, plan="scale", count=1)
    mailer.fail_with = AlertDeliveryError("smtp_451", retryable=True)
    cycle(engine, mailer, now=NOW)
    attempts = deliveries(engine)[0].attempt_count
    pay(engine, client, plan="scale", status="canceled")

    cycle(engine, mailer, now=NOW + dt.timedelta(minutes=15))
    row = deliveries(engine)[0]
    assert row.status == "suppressed"
    assert row.suppression_reason_code == "entitlement_lost"
    assert row.attempt_count == attempts
```

- [ ] **Step 2: Write RED inaccessible and partial-batch tests**

Queue two signals through a controlled pre-accept failure, then set
`materialized_signal.invalidated_at = NOW` and
`invalidation_reason = "synthetic_test"` for one signal. Retry at the persisted
`next_attempt_at`. Assert the invalidated row becomes `suppressed`, the other
becomes `sent`, the email contains only the accessible signal and no
cross-account or locked fact.

- [ ] **Step 3: Run suppression tests and verify RED**

```bash
uv run pytest tests/test_alert_delivery_runtime.py -k suppressed -q
```

- [ ] **Step 4: Implement revalidation immediately before claim/send**

For an existing batch:

1. recompute billing state and notification preference;
2. if the account cannot receive alerts, suppress all batch rows;
3. query the current feed using the active plan allocation and current
   freshness/invalidation rules;
4. intersect by `signal_key` and require `access.is_unlocked(item)`;
5. suppress excluded rows with an allowlisted reason;
6. claim and render only the remaining rows.

`mark_suppressed` sets `status`, `suppressed_at`, `suppression_reason_code`,
`retryable=false`, and clears leases/next attempt. It never changes
`attempt_count`, `failed_at` or `last_error_code` and never records
`alert_failed`; record a distinct aggregate `alert_suppressed` product event.

- [ ] **Step 5: Run access/paywall regressions and commit**

```bash
uv run pytest \
  tests/test_alert_delivery_runtime.py \
  tests/test_alerts_cycle.py \
  tests/test_billing_paywall.py \
  tests/test_feed_ownership.py \
  tests/test_feed_recency.py -q
uv run ruff check src/signals/alerts tests/test_alert_delivery_runtime.py
git add src/signals/alerts/delivery.py src/signals/alerts/job.py tests/test_alert_delivery_runtime.py tests/test_alerts_cycle.py
git commit -m "feat(email): suppress alerts that lose current access"
```

---

### Task 7: CLI exit semantics and versioned systemd runtime

**Files:**
- Modify: `src/signals/alerts/cli.py`
- Create: `tests/test_alerts_cli.py`
- Create: `ops/systemd/kivou-alerts.service`
- Create: `ops/systemd/kivou-alerts.timer`
- Create: `tests/test_ops_alerts_runtime.py`
- Modify: `ops/README.md`

- [ ] **Step 1: Write RED CLI tests**

```python
@pytest.fixture
def migrated_url(tmp_path) -> str:
    url = f"sqlite+pysqlite:///{tmp_path / 'alerts-cli.db'}"
    migrate_to_latest(create_database_engine(url))
    return url


@pytest.fixture
def configured_runtime(monkeypatch, migrated_url) -> None:
    values = {
        "KIVOU_DATABASE_URL": migrated_url,
        "KIVOU_ALLOWED_ORIGIN": "https://staging.kivou.test",
        "KIVOU_PUBLIC_APP_URL": "https://staging.kivou.test",
        "SMTP_HOST": "smtp.kivou.test",
        "SMTP_PORT": "587",
        "SMTP_FROM_EMAIL": "no-reply@kivou.test",
        "SMTP_TLS_MODE": "starttls",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_cli_reads_database_url_only_from_environment(configured_runtime):
    assert main(["--now", NOW.isoformat(), "--dry-run"]) == 0


def test_already_running_is_a_successful_noop(monkeypatch, configured_runtime, capsys):
    report = CycleReport(
        accounts_considered=0,
        outcomes=(),
        execution_status="already_running",
    )
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *a, **k: report)
    assert main(["--now", NOW.isoformat()]) == 0
    assert "already_running" in capsys.readouterr().out


def test_only_current_execution_incidents_return_nonzero(monkeypatch, configured_runtime):
    clean = CycleReport(accounts_considered=1, outcomes=())
    failed = CycleReport(
        accounts_considered=1,
        outcomes=(AlertOutcome("acc_test", "daily", "failed", 1, "smtp_451"),),
    )
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *a, **k: clean)
    assert main(["--now", NOW.isoformat()]) == 0
    monkeypatch.setattr(cli, "run_alert_cycle", lambda *a, **k: failed)
    assert main(["--now", NOW.isoformat()]) != 0
```

Also assert `--database-url` is rejected and neither stdout nor stderr contains
the database URL, SMTP password, recipient or exception text.

- [ ] **Step 2: Run CLI tests and verify RED**

```bash
uv run pytest tests/test_alerts_cli.py -q
```

- [ ] **Step 3: Implement environment-only CLI and exit codes**

Remove `--database-url`; call `create_database_engine()` with no URL argument.
Return:

- `0`: completed with no current incident, dry-run, or `already_running`;
- `2`: invalid/missing configuration;
- `1`: technical persistence/lease failure or current delivery incident.

Catch only at the CLI boundary and print fixed codes. Do not print exception
objects. Summaries contain aggregate counts and result labels only.

- [ ] **Step 4: Write RED unit-file tests**

Assert exact user, group, working directory, environment file, Python command,
no database URL argument, `flock --verbose --nonblock --conflict-exit-code 0`,
hardening, hourly timer, `Persistent=true`, and randomized delay.

Exercise actual local host-lock contention with a temporary lock and assert
return code zero and no child invocation.

- [ ] **Step 5: Add service and timer**

The service core is:

```ini
[Service]
Type=oneshot
User=kivou
Group=kivou
WorkingDirectory=/srv/kivou/app
EnvironmentFile=/etc/kivou/staging.env
ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 /srv/kivou/run/alerts.lock /srv/kivou/app/.venv/bin/python -m signals.alerts
TimeoutStartSec=20min
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kivou-alerts
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true
ReadWritePaths=/srv/kivou/run
```

The timer core is:

```ini
[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=300
Unit=kivou-alerts.service
```

- [ ] **Step 6: Document install/manual/rollback commands**

Add commands that create `/srv/kivou/run` as `kivou`, install both units,
daemon-reload, verify, start manually, inspect safe journals, enable the timer,
and roll back by disabling/restoring prior units. Do not include a real address,
password, token or database URL.

- [ ] **Step 7: Run runtime tests and commit**

```bash
uv run pytest tests/test_alerts_cli.py tests/test_ops_alerts_runtime.py -q
systemd-analyze verify ops/systemd/kivou-alerts.service ops/systemd/kivou-alerts.timer
uv run ruff check src/signals/alerts/cli.py tests/test_alerts_cli.py tests/test_ops_alerts_runtime.py
git add src/signals/alerts/cli.py tests/test_alerts_cli.py ops/systemd/kivou-alerts.service ops/systemd/kivou-alerts.timer tests/test_ops_alerts_runtime.py ops/README.md
git commit -m "feat(email): version the transactional alert runtime"
```

If `systemd-analyze` reports only that staging paths are absent locally,
separate that environment limitation from syntax errors and verify again on
staging before installation. No shell script is added; `shellcheck` is not
applicable. Record that `shellcheck` is not installed locally without claiming
it ran.

---

### Task 8: Reset security and end-to-end offline coverage

**Files:**
- Modify: `tests/test_accounts_security.py`
- Modify: `tests/test_api_runtime.py`
- Modify: `tests/test_smtp_gateway.py`
- Modify: `tests/test_engagement_secrets.py`

- [ ] **Step 1: Add reset-link and enumeration regressions**

Pin FR/EN subjects and bodies, root staging/production link, one-time token,
expired token, old/new password behavior, and identical known/unknown status and
body. Capture logs for SMTP timeout/auth failure and assert absence of address,
token, password and raw exception.

```python
def test_reset_timeout_logs_only_a_safe_code(caplog):
    token = "reset-secret-never-log"

    class FailingGateway:
        def send(self, message):
            raise UncertainDelivery()

    delivery = SmtpPasswordResetDelivery(
        FailingGateway(),
        site_url="https://staging.kivou.test",
        ttl=dt.timedelta(hours=1),
    )
    delivery.deliver(email="user@kivou.test", locale="fr", reset_token=token)
    rendered = caplog.text
    assert "unknown_delivery_state" in rendered
    for forbidden in (token, "user@kivou.test", "smtp-secret"):
        assert forbidden not in rendered
```

- [ ] **Step 2: Add one-shot recovery test**

Submit a reset whose first fake SMTP call fails, submit a second request, then
assert a new token/message ID is generated and only the second token can be
used. Do not add a reset outbox or raw-token persistence.

- [ ] **Step 3: Run security tests and commit**

```bash
uv run pytest tests/test_accounts_security.py tests/test_api_runtime.py tests/test_smtp_gateway.py tests/test_engagement_secrets.py -q
uv run ruff check src/signals/accounts src/signals/alerts/gateway.py tests/test_accounts_security.py tests/test_api_runtime.py tests/test_smtp_gateway.py
git add tests/test_accounts_security.py tests/test_api_runtime.py tests/test_smtp_gateway.py tests/test_engagement_secrets.py
git commit -m "test(email): prove reset delivery security boundaries"
```

---

### Task 9: Technical report and local release validation

**Files:**
- Create: `docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md`
- Modify: `docs/superpowers/specs/2026-08-23-rtl-05-transactional-email-runtime-design.md`

- [ ] **Step 1: Write the redacted technical report**

Document:

- architecture and shared transport boundary;
- exact variable names, never values;
- Infomaniak provider and 587/STARTTLS deployment choice;
- one-shot reset recovery;
- alert batch identity, leases, backoff and `suppressed`;
- current-run exit semantics;
- exact ambiguity guarantee;
- versioned unit/timer;
- read-only DNS evidence: one SPF, DMARC `p=reject`, DKIM pending received-header proof;
- local test evidence;
- staging install/preflight commands;
- redacted real-test checklist;
- rollback;
- remaining production gates.

Do not place the controlled test address in the report.

- [ ] **Step 2: Run migration and targeted integration validation**

```bash
uv run pytest \
  tests/test_transactional_email_config.py \
  tests/test_smtp_gateway.py \
  tests/test_transactional_email_migration.py \
  tests/test_alert_job_lease.py \
  tests/test_alert_delivery_runtime.py \
  tests/test_alerts_cycle.py \
  tests/test_alerts_cli.py \
  tests/test_ops_alerts_runtime.py \
  tests/test_accounts_security.py \
  tests/test_api_runtime.py \
  tests/test_engagement_secrets.py -q
```

Record exact counts and duration in the report.

- [ ] **Step 3: Run complete local validation**

```bash
uv run ruff check .
uv run pytest
cd frontend
npm run typecheck
npm run lint
npm run test -- --run
npm run build
cd ..
systemd-analyze verify ops/systemd/kivou-alerts.service ops/systemd/kivou-alerts.timer
git diff --check
git status --short
```

Also render the migration offline for PostgreSQL through its test and confirm
the SQLite downgrade/re-upgrade test. No real SMTP endpoint is called.

- [ ] **Step 4: Verify scope and secrets**

```bash
git diff --name-only 2481c6e88cd20ca5a78c7d3a8894bcdfdd0b48e4...HEAD
git diff --name-only 2481c6e88cd20ca5a78c7d3a8894bcdfdd0b48e4...HEAD | \
  rg 'src/signals/(acquisition|campaigns|contact_discovery|company_research|supplier_discovery|billing)|checkoutIntent|pricing|stripe'
test -n "${KIVOU_TEST_RECIPIENT:-}"
if git grep -n -F -- "$KIVOU_TEST_RECIPIENT"; then
  exit 1
fi
rg -n 'smtp-secret|reset-secret-never-log' tests
```

`KIVOU_TEST_RECIPIENT` is supplied only in the operator shell and never written
to a file. Expected: the forbidden-scope file list and real-address scan are
empty. Test sentinels may appear only inside their explicit secret-leak tests.

- [ ] **Step 5: Update evidence and commit**

Change the design status to `approved design; implementation locally validated`
only after every required local command succeeds. Commit the report and status:

```bash
git add docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md docs/superpowers/specs/2026-08-23-rtl-05-transactional-email-runtime-design.md
git commit -m "docs(email): document RTL-05 runtime operations"
```

Do not yet mark RTL-05 staging-validated or operational.

---

### Task 10: Synchronize normally, revalidate, and open the draft PR

**Files:**
- Modify if needed after PR creation: `docs/ROAD_TO_LIVE.md` (RTL-05 only)
- Modify if needed after PR creation: `docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md`

- [ ] **Step 1: Merge current `origin/main` normally**

```bash
git fetch origin
git status --short
git merge --no-edit origin/main
```

Never rebase, reset or force-push. Resolve only genuine conflicts in scoped
files and preserve unrelated upstream work.

- [ ] **Step 2: Re-run release validation after the merge**

Run Ruff, the full backend suite, frontend typecheck/lint/tests/build,
`systemd-analyze verify`, `git diff --check` and scope/secret checks again.

- [ ] **Step 3: Push the fully validated implementation branch**

```bash
git push origin feat/operational-transactional-email-runtime
```

- [ ] **Step 4: Open the draft PR only now**

```bash
gh pr create --draft \
  --base main \
  --head feat/operational-transactional-email-runtime \
  --title "feat(email): operationalize transactional delivery and alerts" \
  --body-file /tmp/rtl05-pr-body.md
```

The generated body contains architecture, exact idempotence guarantee, SMTP
ambiguity, provider/cache-free cost posture, privacy boundaries, test evidence,
staging/DNS gates and confirms no production action. The temporary body must not
contain the controlled address or secrets.

- [ ] **Step 5: Mark RTL-05 delivered in the draft PR**

After GitHub returns the PR number, update only RTL-05 in
`docs/ROAD_TO_LIVE.md` to **livré en PR**, add the PR reference to the report,
commit and push normally:

```bash
git add docs/ROAD_TO_LIVE.md docs/reports/2026-08-23-rtl-05-transactional-email-runtime.md
git commit -m "docs(email): mark RTL-05 delivered in draft PR"
git push origin feat/operational-transactional-email-runtime
```

- [ ] **Step 6: Wait for and verify complete PR CI**

Use `gh pr checks --watch` and inspect any GitHub Actions failure. A concurrency
cancellation is not classified as a failing implementation until the successor
run is checked. Do not merge.

- [ ] **Step 7: Stop before staging mutation or send**

Prepare, but do not execute, the staging backup/migration/environment/unit
installation and real reset/alert commands. Ask for separate explicit
authorization before deploying the SHA or sending to the controlled address.
No production or DNS action is permitted.

---

## Definition of locally validated implementation

The implementation may proceed to a draft PR only when:

- strict origin, SMTP and link tests pass;
- reset enumeration, expiry and one-time use remain proven;
- loopback STARTTLS/implicit-TLS tests pass with no external SMTP;
- migration `0023` upgrades/downgrades on SQLite and renders scoped PostgreSQL
  SQL;
- sequential and simultaneous runs are deterministic;
- host and database contention return zero and are observable;
- temporary, permanent, ambiguous and post-accept persistence cases have the
  documented outcome;
- stale leases recover with bounded retries and stable Message-ID;
- lost preference/entitlement/access becomes terminal `suppressed` without an
  SMTP attempt;
- only incidents from the current execution affect its exit code;
- service/timer syntax and hardening validate;
- full backend and frontend CI-equivalent commands pass;
- the diff contains no private address, secret, acquisition/provider campaign,
  Stripe, pricing or signal-engine change.

Staging validation, real messages, received-header SPF/DKIM/DMARC proof, merge
and production readiness remain separate gates after the draft PR.
