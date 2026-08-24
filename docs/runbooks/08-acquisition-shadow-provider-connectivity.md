# Acquisition provider SHADOW connectivity on staging

This runbook installs and manually invokes the disabled-by-default connectivity
smoke on `kivou-staging`. It does not authorize deployment from a feature branch,
production use, campaign startup, lead creation, webhook creation, or email sending.

The operator must use an approved merge SHA from `main` whose GitHub CI is green.
The implementation and this runbook introduce no migration.

## Official read-only contracts

The contracts revalidated on 2026-08-24 are:

- Apollo authentication and acting profile:
  <https://docs.apollo.io/reference/authentication>. The smoke permits only
  `GET /api/v1/auth/health` and `GET /api/v1/users/api_profile`; Apollo documents
  the profile read as consuming no credits.
- Instantly current workspace:
  <https://developer.instantly.ai/api-reference/workspace/get-workspace>. The
  documented `GET /api/v2/workspaces/current` returns the workspace selected by
  the API key and requires a read scope.
- Instantly account:
  <https://developer.instantly.ai/api-reference/account/get-account>. The smoke
  uses only `GET /api/v2/accounts/{email}`. Current account and warmup status
  fields are numeric; Kivou's existing mailbox normalizer owns their mapping.

No other provider route belongs to this smoke.

## 1. Preconditions

Record the approved Kivou merge SHA. Confirm that `/srv/kivou/app` resolves to
that SHA, `kivou-api.service` is healthy, the database migration head is current,
and the deployed tree is clean. Do not continue from a feature-branch artifact.

The explicit Policy operator action must establish `SHADOW`, READ ONLY, kill
switch active, and daily autonomous volume zero before the connectivity unit is
started. The smoke only reads that authority and never creates a Policy revision.

## 2. Install the immutable Hermes runtime

Hermes is pinned to repository
`https://github.com/NousResearch/hermes-agent.git`, tag `v2026.8.18`, commit
`e624e9fde561e1add9388384012b295fde669ade`, package version `0.20.4`, and Python
contract `>=3.11,<3.14`.

Run these commands in a protected root session. They use the upstream locked uv
installation path and do not invoke the interactive Hermes setup, a gateway, a
dashboard, a listener, MCP, shell tools, messaging, cron, or delegation.

```bash
sudo install -d -m 0755 -o root -g root /opt/kivou/hermes-agent
sudo git clone --no-checkout https://github.com/NousResearch/hermes-agent.git \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade \
  fetch --depth=1 origin tag v2026.8.18
sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade \
  checkout --detach e624e9fde561e1add9388384012b295fde669ade
test "$(sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade rev-parse HEAD)" = \
  e624e9fde561e1add9388384012b295fde669ade
test "$(sudo git -C /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade rev-list -n1 v2026.8.18)" = \
  e624e9fde561e1add9388384012b295fde669ade
sudo env UV_PROJECT_ENVIRONMENT=/opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv \
  uv sync --locked --python 3.12 --extra all \
  --directory /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo chown -R root:root \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade
sudo -u kivou \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python \
  -c 'import importlib.metadata; assert importlib.metadata.version("hermes-agent") == "0.20.4"'
```

Any mismatch stops installation. Do not substitute a newer tag, branch, package,
or fallback model.

## 3. Provision protected configuration

Create the mutable runtime directories and copy only the tracked, non-secret
model configuration. JSON syntax is intentional: it is valid YAML and lets the
Kivou stdlib validator compare the whole closed document exactly.

```bash
sudo install -d -m 0700 -o kivou -g kivou /var/lib/kivou/hermes-shadow
sudo install -d -m 0700 -o kivou -g kivou /var/lib/kivou/hermes-shadow/work
sudo install -m 0600 -o kivou -g kivou ops/examples/hermes-shadow-config.yaml \
  /var/lib/kivou/hermes-shadow/config.yaml
sudo install -m 0600 -o kivou -g kivou /dev/null \
  /var/lib/kivou/hermes-shadow/.env
sudoedit /var/lib/kivou/hermes-shadow/.env
```

Enter only the OpenRouter credential under the variable name
`OPENROUTER_API_KEY`. Do not paste it into chat, command arguments, shell
history, Git, logs, or CI.

Provision the Kivou deployment files from the redacted examples, then replace
the blank provider values and example workspace/mailbox bindings inside the
protected editor session:

```bash
sudo install -m 0600 -o root -g kivou ops/examples/acquisition-shadow.env.example \
  /etc/kivou/acquisition-shadow.env
sudo install -m 0640 -o root -g kivou ops/examples/acquisition-shadow.json.example \
  /etc/kivou/acquisition-shadow.json
sudoedit /etc/kivou/acquisition-shadow.env
sudoedit /etc/kivou/acquisition-shadow.json
```

The JSON must retain its exact schema version, exactly three distinct opaque
mailbox refs, and exactly three distinct provider account email bindings. The
tracked examples are not deployable credentials.

## 4. Verify ownership and permissions

```bash
namei -l /etc/kivou/acquisition-shadow.env
namei -l /etc/kivou/acquisition-shadow.json
namei -l /var/lib/kivou/hermes-shadow/config.yaml
namei -l /var/lib/kivou/hermes-shadow/.env
namei -l /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python
sudo stat -c '%a %U %G %n' \
  /etc/kivou/acquisition-shadow.env \
  /etc/kivou/acquisition-shadow.json \
  /var/lib/kivou/hermes-shadow \
  /var/lib/kivou/hermes-shadow/.env
sudo -u kivou test -r /etc/kivou/acquisition-shadow.json
sudo -u kivou test -x \
  /opt/kivou/hermes-agent/e624e9fde561e1add9388384012b295fde669ade/.venv/bin/python
```

Expected modes are `0600 root:kivou` for the acquisition environment,
`0640 root:kivou` for the deployment JSON, `0700 kivou:kivou` for Hermes HOME,
and `0600 kivou:kivou` for the Hermes secret file.

## 5. Establish and verify Policy authority

Use the existing explicit SPEC-031 operator CLI under the staging environment.
This action is separate from the smoke and must be recorded in the operator
change log.

```bash
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --working-directory=/srv/kivou/app \
  /srv/kivou/app/.venv/bin/python -m signals.operations \
  activate-kill-switch --reason-code ACQUISITION_SHADOW_CONNECTIVITY
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/kivou/staging.env \
  --working-directory=/srv/kivou/app \
  /srv/kivou/app/.venv/bin/python -m signals.operations readiness
```

Confirm the effective durable control is exactly STAGING, SHADOW, READ ONLY,
kill-switched, and at volume cap zero. An ambiguous or missing control blocks the
smoke.

## 6. Install the static oneshot

```bash
sudo install -m 0644 -o root -g root \
  ops/systemd/kivou-acquisition-shadow-smoke.service \
  /etc/systemd/system/kivou-acquisition-shadow-smoke.service
sudo systemctl daemon-reload
systemctl is-enabled kivou-acquisition-shadow-smoke.service
systemctl list-timers --all | rg 'kivou-acquisition-shadow-smoke' || true
systemctl show kivou-acquisition-shadow-smoke.service \
  -p Type -p User -p Group -p FragmentPath
```

The unit must report `static`, have no timer, and remain absent from startup
targets. It opens no listener and has no restart loop.

## 7. Manual smoke

The unit is the only supported live staging entry point. The underlying command
is `python -m signals.acquisition_connectivity check`. Run it once:

```bash
sudo systemctl start kivou-acquisition-shadow-smoke.service
systemctl show kivou-acquisition-shadow-smoke.service \
  -p Result -p ExecMainCode -p ExecMainStatus
sudo journalctl -u kivou-acquisition-shadow-smoke.service -n 30 --no-pager
```

Accept only `result=PASS` with Apollo READY/BOUND, Instantly BOUND and `3/3`,
Hermes `0.20.4` with zero executable tools and the exact model, an advisory
plan within CHF 1, and all four mutation deltas equal to zero. The journal must
contain no key, email address, raw provider object, prompt, reasoning, or raw
model response.

Recheck `kivou-api.service`, the deployed SHA, and the durable Policy authority.
The oneshot remains static and unscheduled after success.

## Rollback

On any failure, stop the oneshot if it is still active, leave SHADOW, READ ONLY,
the kill switch, and volume zero in force, and restore the previously approved
Kivou application artifact through the normal release procedure. Leave database
truth intact; this change has no migration or database downgrade.

Keep the unit static or move its unit file out of `/etc/systemd/system` during a
controlled maintenance window, followed by `systemctl daemon-reload`. Do not
downgrade Hermes or select a fallback model. If credential exposure is suspected,
rotate the affected provider credential through that provider's console and
re-provision it through the protected editor procedure before any new smoke.
