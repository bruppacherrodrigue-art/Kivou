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
