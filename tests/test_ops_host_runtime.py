from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HOST = ROOT / "ops" / "host"


def text(name: str) -> str:
    return (HOST / name).read_text(encoding="utf-8")


SSH_POLICY = {
    "permitrootlogin": "no",
    "passwordauthentication": "no",
    "kbdinteractiveauthentication": "no",
    "pubkeyauthentication": "yes",
    "authenticationmethods": "publickey",
    "x11forwarding": "no",
    "allowagentforwarding": "no",
    "allowtcpforwarding": "local",
    "permittunnel": "no",
    "permituserenvironment": "no",
    "maxauthtries": "3",
    "logingracetime": "30",
    "clientaliveinterval": "300",
    "clientalivecountmax": "2",
    "allowusers": "ubuntu",
}


def assert_effective_ssh_policy(policy: str) -> None:
    effective: dict[str, str] = {}
    seen: set[str] = set()
    for raw_line in policy.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, separator, value = line.partition(" ")
        assert separator
        normalized = key.casefold()
        assert normalized != "match"
        assert normalized not in seen
        seen.add(normalized)
        if normalized in SSH_POLICY:
            effective[normalized] = value.strip()
    assert effective == SSH_POLICY


def test_ssh_policy_is_key_only_and_disables_forwarding() -> None:
    policy = text("sshd-kivou-production.conf")
    assert_effective_ssh_policy(policy)


@pytest.mark.parametrize(
    "duplicate",
    ("PasswordAuthentication no", "PasswordAuthentication yes"),
)
def test_ssh_policy_rejects_duplicate_or_contradictory_directives(duplicate: str) -> None:
    policy = text("sshd-kivou-production.conf")
    with pytest.raises(AssertionError):
        assert_effective_ssh_policy(f"{policy}\n{duplicate}\n")


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
