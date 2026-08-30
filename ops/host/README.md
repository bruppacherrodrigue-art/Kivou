# Kivou production host policy

These fragments define the versioned operating-system baseline for the Kivou
production VPS. They contain policy only: application configuration and
credentials must stay outside the repository.

## Backup

Before installation, create one explicit timestamped directory below
`/root/kivou-rollbacks`, set it to mode `0700`, and copy the destination files
with `cp -a`. Record the selected directory in the root-only host-baseline
report. Never overwrite a prior rollback directory.

SSH and firewall changes require a scheduled, short-lived rollback before the
new policy is installed. Cancel that rollback only after a second independent
SSH connection succeeds.

## Installation and validation

Install the files under these destinations:

| Repository file | Destination |
| --- | --- |
| `sshd-kivou-production.conf` | `/etc/ssh/sshd_config.d/60-kivou-production.conf` |
| `journald-kivou-production.conf` | `/etc/systemd/journald.conf.d/60-kivou-production.conf` |
| `fail2ban-kivou-sshd.local` | `/etc/fail2ban/jail.d/kivou-sshd.local` |
| `sysctl-kivou-production.conf` | `/etc/sysctl.d/60-kivou-production.conf` |
| `20auto-upgrades-kivou` | `/etc/apt/apt.conf.d/20auto-upgrades` |
| `52unattended-upgrades-kivou-local` | `/etc/apt/apt.conf.d/52unattended-upgrades-kivou-local` |

Validate syntax before reloading a service:

```sh
sshd -t
sshd -T
fail2ban-client -t
systemd-analyze cat-config systemd/journald.conf
sysctl --system
apt-config dump
unattended-upgrade --dry-run --debug
```

Reload SSH rather than restarting it. Restart fail2ban and journald only after
their configuration checks pass. Apply sysctl only after retaining a known-good
copy of the previous policy tree.

## Rollback

Restore the affected file or directory from the recorded timestamped backup,
validate its syntax, and reload the corresponding service. For SSH, the
scheduled rollback must restore the full saved `/etc/ssh` tree, run `sshd -t`,
and reload `ssh`. For UFW, the emergency rollback disables UFW so that SSH
access is not lost; restore the saved `/etc/ufw` tree only from an active
administrative session.

Do not delete a rollback directory after validation. Keep the exact path in the
host-baseline evidence report.

## Reboot verification

After a controlled reboot, verify hostname, CPU and memory, swap, listening
sockets, effective SSH policy, UFW, fail2ban, unattended upgrades, PostgreSQL
loopback binding, nginx disabled state, failed systemd units, and installed
runtime versions. The host baseline alone does not prove that Kivou application
services or engines are deployed or ready.
