# Kivou Production Host Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden `kivou-production` and install the maintained OS/runtime foundation required by the Kivou SaaS, Signal Engine and Acquisition Engine without deploying application code or activating production traffic.

**Architecture:** Keep one Ubuntu 24.04 VPS with nginx as the future public edge, PostgreSQL bound to loopback, a non-login `kivou` service identity, and key-only SSH administration. Version the host policy fragments in `ops/host`, test their fail-closed content, install them with timestamped server-side rollback copies, and prove persistence through a reboot.

**Tech Stack:** Ubuntu 24.04, OpenSSH, UFW, fail2ban, systemd-journald, sysctl, unattended-upgrades, Python 3.12, uv 0.12.5, Node.js 24, PostgreSQL 16, nginx 1.24, Certbot, restic.

---

## Scope and file map

This plan modifies only the following repository files:

- Create `ops/host/sshd-kivou-production.conf`: production SSH policy fragment.
- Create `ops/host/journald-kivou-production.conf`: bounded persistent journal policy.
- Create `ops/host/fail2ban-kivou-sshd.local`: SSH jail configuration.
- Create `ops/host/sysctl-kivou-production.conf`: conservative host kernel policy.
- Create `ops/host/20auto-upgrades-kivou`: automatic security-update schedule.
- Create `ops/host/52unattended-upgrades-kivou-local`: disable implicit reboots and remove unused dependencies.
- Create `ops/host/README.md`: exact installation, validation and rollback contract.
- Create `tests/test_ops_host_runtime.py`: static tests for security boundaries and secret-free assets.

The plan changes these remote files after making root-only timestamped copies:

- `/etc/hostname`
- `/etc/hosts`
- `/etc/cloud/cloud.cfg.d/99-kivou-hostname.cfg`
- `/etc/ssh/sshd_config.d/60-kivou-production.conf`
- `/etc/fail2ban/jail.d/kivou-sshd.local`
- `/etc/systemd/journald.conf.d/60-kivou-production.conf`
- `/etc/sysctl.d/60-kivou-production.conf`
- `/etc/apt/apt.conf.d/20auto-upgrades`
- `/etc/apt/apt.conf.d/52unattended-upgrades-kivou-local`
- `/etc/apt/sources.list.d/nodesource.list`
- `/usr/share/keyrings/nodesource.gpg`
- `/usr/local/bin/uv` and `/usr/local/bin/uvx`
- `/etc/fstab` for `/swapfile`

It creates `/etc/kivou`, `/srv/kivou`, `/var/lib/kivou/host-baseline` and a
timestamped `/root/kivou-rollbacks/host-baseline-*` directory. It does not
create application secrets, a Kivou database, a release, a certificate or a
public nginx site.

### Task 1: Version and test host policy fragments

**Files:**
- Create: `tests/test_ops_host_runtime.py`
- Create: `ops/host/sshd-kivou-production.conf`
- Create: `ops/host/journald-kivou-production.conf`
- Create: `ops/host/fail2ban-kivou-sshd.local`
- Create: `ops/host/sysctl-kivou-production.conf`
- Create: `ops/host/20auto-upgrades-kivou`
- Create: `ops/host/52unattended-upgrades-kivou-local`
- Create: `ops/host/README.md`

- [ ] **Step 1: Write the failing static policy tests**

Create `tests/test_ops_host_runtime.py` with tests that require:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]
HOST = ROOT / "ops" / "host"


def text(name: str) -> str:
    return (HOST / name).read_text(encoding="utf-8")


def test_ssh_policy_is_key_only_and_disables_forwarding() -> None:
    policy = text("sshd-kivou-production.conf")
    required = {
        "PermitRootLogin no",
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "PubkeyAuthentication yes",
        "X11Forwarding no",
        "AllowAgentForwarding no",
        "PermitTunnel no",
        "MaxAuthTries 3",
        "LoginGraceTime 30",
        "AllowUsers ubuntu",
    }
    assert required <= set(policy.splitlines())


def test_journal_is_persistent_and_bounded() -> None:
    policy = text("journald-kivou-production.conf")
    assert "Storage=persistent" in policy
    assert "SystemMaxUse=512M" in policy
    assert "SystemKeepFree=2G" in policy
    assert "MaxRetentionSec=30day" in policy


def test_fail2ban_enables_only_bounded_sshd_jail() -> None:
    policy = text("fail2ban-kivou-sshd.local")
    assert "[sshd]" in policy
    assert "enabled = true" in policy
    assert "backend = systemd" in policy
    assert "maxretry = 5" in policy
    assert "findtime = 10m" in policy
    assert "bantime = 1h" in policy


def test_sysctl_keeps_forwarding_disabled() -> None:
    policy = text("sysctl-kivou-production.conf")
    assert "net.ipv4.ip_forward = 0" in policy
    assert "net.ipv6.conf.all.forwarding = 0" in policy
    assert "kernel.dmesg_restrict = 1" in policy
    assert "kernel.kptr_restrict = 2" in policy
    assert "vm.swappiness = 10" in policy


def test_automatic_updates_never_reboot_implicitly() -> None:
    periodic = text("20auto-upgrades-kivou")
    unattended = text("52unattended-upgrades-kivou-local")
    assert 'APT::Periodic::Update-Package-Lists "1";' in periodic
    assert 'APT::Periodic::Unattended-Upgrade "1";' in periodic
    assert 'Unattended-Upgrade::Automatic-Reboot "false";' in unattended


def test_host_assets_contain_no_environment_secrets_or_staging_paths() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in HOST.iterdir())
    forbidden = (
        "staging.env",
        "sk_test_",
        "sk_live_",
        "SMTP_PASSWORD=",
        "KIVOU_APOLLO_API_KEY=",
        "KIVOU_INSTANTLY_API_KEY=",
    )
    assert all(value not in combined for value in forbidden)
```

- [ ] **Step 2: Run the tests and verify the missing files fail**

Run:

```bash
uv run pytest -q tests/test_ops_host_runtime.py
```

Expected: failure with `FileNotFoundError` for `ops/host` policy files.

- [ ] **Step 3: Create the minimal policy files and operations README**

Create the seven files with the exact settings asserted above. The SSH policy
also sets `AuthenticationMethods publickey`, `AllowTcpForwarding local`,
`ClientAliveInterval 300`, `ClientAliveCountMax 2` and `PermitUserEnvironment no`.
The sysctl policy also disables redirects and source routing for IPv4/IPv6,
enables TCP syncookies and protected links, and sets `vm.vfs_cache_pressure=50`.
The README documents backup, syntax validation, install, rollback and reboot
verification commands without any credential value.

- [ ] **Step 4: Run focused tests and formatting checks**

Run:

```bash
uv run pytest -q tests/test_ops_host_runtime.py
uv run ruff check tests/test_ops_host_runtime.py
git diff --check
```

Expected: all host tests pass, Ruff passes, and `git diff --check` prints nothing.

- [ ] **Step 5: Commit the versioned host policy**

```bash
git add ops/host tests/test_ops_host_runtime.py
git commit -m "ops: add production host baseline policy"
```

Expected: one focused commit containing only the host policy and its tests.

### Task 2: Capture a rollback-safe remote baseline

**Files:**
- Create remotely: `/root/kivou-rollbacks/host-baseline-<UTC>/`
- Create remotely: `/var/lib/kivou/host-baseline/pre-change.txt`

- [ ] **Step 1: Reconfirm exact host identity and expected empty state**

Run from the operator host:

```bash
ssh kivou-production 'hostname; nproc; free -h; df -hT /; ss -lntup; cloud-init status --long || true'
```

Expected: current hostname `ov-a63062`, 4 CPUs, about 8 GiB RAM, about 160 GB
root disk, only SSH publicly listening, and the known optional-data-disk
cloud-init failure.

- [ ] **Step 2: Create an explicit root-only rollback directory**

Use a validated UTC timestamp and create mode `0700`. Copy `/etc/ssh`,
`/etc/ufw`, `/etc/fail2ban`, `/etc/systemd/journald.conf`, `/etc/sysctl.conf`,
`/etc/sysctl.d`, `/etc/apt/apt.conf.d`, `/etc/hostname`, `/etc/hosts` and
`/etc/fstab` with `cp -a`. Record SHA-256 hashes of the cloud-init user script
and host key public files, not their contents.

Expected: every copied tree exists below one explicit rollback directory and
the directory is not group/world accessible.

- [ ] **Step 3: Save a secret-free pre-change report**

Write only hostname, OS, kernel, CPU count, memory totals, block devices,
listening socket addresses, enabled services, failed units, UFW status and
package versions to `/var/lib/kivou/host-baseline/pre-change.txt` mode `0600`.

Expected: the report contains no environment file, command line containing a
credential, authorized key body or cloud-init script body.

### Task 3: Update Ubuntu and install maintained base packages

**Files:**
- Modify remotely: dpkg database and Ubuntu packages
- Create remotely: `/usr/share/keyrings/nodesource.gpg`
- Create remotely: `/etc/apt/sources.list.d/nodesource.list`
- Create remotely: `/usr/local/bin/uv`, `/usr/local/bin/uvx`

- [ ] **Step 1: Refresh and apply Ubuntu updates non-interactively**

Run `apt-get update`, then `DEBIAN_FRONTEND=noninteractive apt-get -y
dist-upgrade`. Do not allow an automatic reboot.

Expected: both commands exit zero; `/var/run/reboot-required` is recorded for
the final controlled reboot if present.

- [ ] **Step 2: Install Ubuntu-supported runtime and operations packages**

Install:

```text
acl build-essential ca-certificates certbot curl fail2ban git gnupg jq
libpq-dev logrotate lsof nginx postgresql postgresql-client
postgresql-contrib python3.12 python3.12-venv python3-certbot-nginx
restic rsync unzip
```

Immediately stop and disable nginx so the Ubuntu default site is never served.
Keep PostgreSQL enabled, and verify port 5432 is bound only to loopback.

- [ ] **Step 3: Install Node.js 24 from the signed NodeSource repository**

Download `nodesource-repo.gpg.key` to a temporary file, verify primary
fingerprint `6F71F525282841EEDAF851B42F59B5F99B1BE0B4`, dearmor it to
`/usr/share/keyrings/nodesource.gpg`, add only the signed `node_24.x nodistro`
repository and install `nodejs`.

Expected: `node --version` starts with `v24.`, npm is present, the keyring is
root-owned mode `0644`, and `apt-cache policy nodejs` shows the signed NodeSource
repository.

- [ ] **Step 4: Install uv 0.12.5 from its checksummed release archive**

Download both official assets from
`https://github.com/astral-sh/uv/releases/download/0.12.5/`:

```text
uv-x86_64-unknown-linux-gnu.tar.gz
uv-x86_64-unknown-linux-gnu.tar.gz.sha256
```

Verify with `sha256sum --check`, extract to a temporary directory, then install
`uv` and `uvx` root-owned mode `0755` under `/usr/local/bin`.

Expected: `uv --version` prints exactly `uv 0.12.5`.

- [ ] **Step 5: Verify package provenance and public listeners**

Run version commands, `apt-cache policy`, `systemctl is-enabled`, and
`ss -lntup`.

Expected: nginx is disabled/inactive, PostgreSQL is enabled/active on loopback,
and no new wildcard listener exists.

### Task 4: Create the service identity and filesystem layout

**Files:**
- Create remotely: `/etc/kivou`
- Create remotely: `/srv/kivou/{releases,rollbacks,backups,run,validation}`
- Create remotely: `/var/lib/kivou/{host-baseline,hermes-production}`

- [ ] **Step 1: Create a non-login `kivou` system account**

Use `adduser --system --group --home /srv/kivou --shell /usr/sbin/nologin
kivou` only if the identity does not exist.

Expected: the account is a system UID, owns `/srv/kivou`, has no password and
cannot obtain an interactive shell.

- [ ] **Step 2: Create directories with explicit ownership and modes**

```text
/etc/kivou                         root:kivou 0750
/srv/kivou                        kivou:kivou 0755
/srv/kivou/releases               kivou:kivou 0755
/srv/kivou/rollbacks              kivou:kivou 0755
/srv/kivou/backups                kivou:kivou 0700
/srv/kivou/run                    kivou:kivou 0750
/srv/kivou/validation             root:kivou 0750
/var/lib/kivou                    root:kivou 0750
/var/lib/kivou/host-baseline      root:root  0700
/var/lib/kivou/hermes-production  kivou:kivou 0700
```

Expected: `namei -l` and `stat` match every owner/group/mode above.

### Task 5: Configure swap and kernel policy

**Files:**
- Create remotely: `/swapfile`
- Modify remotely: `/etc/fstab`
- Create remotely: `/etc/sysctl.d/60-kivou-production.conf`

- [ ] **Step 1: Create the 4 GiB swap file atomically**

Use `fallocate -l 4G /swapfile`, mode `0600`, `mkswap`, append exactly one
`/swapfile none swap sw 0 0` entry to `/etc/fstab`, then `swapon /swapfile`.

Expected: `swapon --show --bytes` reports 4 GiB and `findmnt --verify` succeeds.

- [ ] **Step 2: Install and validate the versioned sysctl fragment**

Copy `ops/host/sysctl-kivou-production.conf` through a root-owned temporary
candidate, install it mode `0644`, then run `sysctl --system`.

Expected: all settings load without error; IP forwarding remains zero and
swappiness equals 10.

### Task 6: Persist the production hostname and close the cloud-init alert

**Files:**
- Modify remotely: `/etc/hostname`, `/etc/hosts`
- Create remotely: `/etc/cloud/cloud.cfg.d/99-kivou-hostname.cfg`
- Create remotely: `/var/lib/kivou/host-baseline/cloud-init-known-error.txt`

- [ ] **Step 1: Record the cloud-init defect without replaying user data**

Record its status, the SHA-256 of `/var/lib/cloud/instance/scripts/part-001`,
and the confirmed cause: the optional data-disk discovery pipeline returns one
under `set -e -o pipefail` when there is no extra disk. Do not copy or execute
the script.

- [ ] **Step 2: Set and persist hostname `kivou-production-01`**

Use `hostnamectl set-hostname`, replace the previous `127.0.1.1` hostname entry
without changing localhost or IPv6 rows, and install:

```yaml
preserve_hostname: true
```

Expected: `hostnamectl --static`, `hostname -f` and `getent hosts
kivou-production-01` resolve locally without warnings.

- [ ] **Step 3: Reset only the historical failed unit state**

Run `systemctl reset-failed cloud-final.service`; do not run `cloud-init clean`,
replay cloud-init modules or delete its evidence.

Expected: `systemctl --failed` no longer contains the historical one-shot;
`cloud-init status --long` may retain the documented historical error.

### Task 7: Harden SSH with an automatic rollback

**Files:**
- Create remotely: `/etc/ssh/sshd_config.d/60-kivou-production.conf`
- Create remotely: `<rollback-dir>/rollback-ssh.sh`

- [ ] **Step 1: Install a five-minute rollback script and timer**

The root-only script restores the prior SSH tree, validates it with `sshd -t`
and reloads `ssh`. Schedule it with a transient `systemd-run --on-active=5m`
timer before changing the active policy.

- [ ] **Step 2: Install and validate the SSH candidate**

Install `ops/host/sshd-kivou-production.conf` mode `0644`, run `sshd -t`, inspect
effective values with `sshd -T`, then reload rather than restart SSH.

Expected: key-only authentication, root/X11/agent/tunnel disabled, three auth
tries, 30-second grace, and only `ubuntu` allowed interactively.

- [ ] **Step 3: Prove a fresh independent SSH connection**

From the operator host, run a new batch-mode connection through
`ssh kivou-production` and verify hostname, user, sudo non-interactive access
and host fingerprint.

Expected: login as `ubuntu` succeeds with the existing pinned key.

- [ ] **Step 4: Cancel rollback only after the new session succeeds**

Stop the transient rollback timer/service and prove they no longer have a
pending activation. Retain the script and backup files for manual recovery.

### Task 8: Enable UFW and fail2ban with rollback

**Files:**
- Create remotely: `/etc/fail2ban/jail.d/kivou-sshd.local`
- Create remotely: `<rollback-dir>/rollback-firewall.sh`

- [ ] **Step 1: Schedule firewall rollback**

The root-only rollback script disables UFW, restoring the known pre-change
reachable state. Schedule it for five minutes before enabling UFW.

- [ ] **Step 2: Apply explicit UFW policy**

Reset UFW only after its original directory is archived. Set default deny
incoming, allow outgoing, deny routed, enable IPv6, allow TCP ports 22, 80 and
443 with comments, enable low logging, then enable non-interactively.

Expected: exactly those six IPv4/IPv6 allow rows and no other public ingress.

- [ ] **Step 3: Install and validate fail2ban**

Install the versioned jail file, run `fail2ban-client -t`, restart fail2ban and
verify the `sshd` jail is active.

- [ ] **Step 4: Prove SSH and cancel the firewall rollback**

Open another batch-mode SSH session, then cancel the transient rollback. Verify
UFW remains enabled and SSH remains reachable.

### Task 9: Bound journals and automatic updates

**Files:**
- Create remotely: `/etc/systemd/journald.conf.d/60-kivou-production.conf`
- Modify remotely: `/etc/apt/apt.conf.d/20auto-upgrades`
- Create remotely: `/etc/apt/apt.conf.d/52unattended-upgrades-kivou-local`

- [ ] **Step 1: Install and validate journald policy**

Install the versioned fragment, run `systemd-analyze cat-config
systemd/journald.conf`, create `/var/log/journal` with systemd-tmpfiles and
restart journald.

Expected: persistent storage, 512 MiB cap, 2 GiB free-space reserve, 30-day
retention and compression are effective.

- [ ] **Step 2: Install and dry-run automatic update policy**

Install both versioned apt fragments and run `unattended-upgrade --dry-run
--debug` with output captured to a root-only file.

Expected: security updates are enabled, no implicit reboot is configured, and
the dry run exits zero without leaking environment secrets.

### Task 10: Reboot and verify the complete host baseline

**Files:**
- Create remotely: `/var/lib/kivou/host-baseline/post-reboot.txt`

- [ ] **Step 1: Capture pre-reboot state and reboot intentionally**

Verify `sshd -t`, UFW, fail2ban, swap, filesystems and package manager health.
Then run `systemctl reboot` and wait for SSH to disconnect.

- [ ] **Step 2: Wait for the pinned host to return**

Poll `ssh kivou-production true` with bounded attempts for at most five minutes.

Expected: the same ED25519 host fingerprint returns and key-only login works.

- [ ] **Step 3: Run the post-reboot acceptance probe**

Verify:

```text
hostname=kivou-production-01
CPU=4
RAM about 8 GiB
swap=4 GiB
UFW active with only 22/80/443
fail2ban active with sshd jail
SSH hardening effective
unattended-upgrades active
PostgreSQL active on loopback only
nginx disabled and inactive
no failed systemd units
Node 24, uv 0.12.5, Python 3.12, PostgreSQL 16, nginx 1.24, restic and Certbot installed
```

Write the secret-free evidence to
`/var/lib/kivou/host-baseline/post-reboot.txt` mode `0600`.

- [ ] **Step 4: Run repository verification and commit the plan state**

Run:

```bash
uv run pytest -q tests/test_ops_host_runtime.py tests/test_ops_backup_runtime.py
uv run ruff check tests/test_ops_host_runtime.py
git diff --check
git status --short
```

Expected: tests and Ruff pass; only the planned documentation state remains.

Record exact package versions, rollback directory, host fingerprint, applied
files and all acceptance results in the execution report. Do not claim the SaaS
or engines are deployed; this plan delivers only the secure host foundation.
