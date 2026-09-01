from __future__ import annotations

import pathlib

from signals.acquisition_runtime.contracts import AcquisitionRuntimeDeployment

ROOT = pathlib.Path(__file__).parents[1]
SERVICE = ROOT / "ops/systemd/kivou-acquisition.service"
TIMER = ROOT / "ops/systemd/kivou-acquisition.timer"
RUNBOOK = ROOT / "docs/runbooks/10-acquisition-runtime.md"
RUNTIME_ENV = ROOT / "ops/examples/acquisition-runtime.env.example"
RUNTIME_CONFIG = ROOT / "ops/examples/acquisition-runtime.json.example"
ENV_EXAMPLE = ROOT / ".env.example"
OPS_README = ROOT / "ops/README.md"


def test_acquisition_service_is_one_bounded_shadow_orchestrator() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "User=kivou" in service
    assert "Group=kivou" in service
    assert "WorkingDirectory=/srv/kivou/app" in service
    assert "EnvironmentFile=/etc/kivou/staging.env" in service
    assert "EnvironmentFile=/etc/kivou/acquisition-shadow.env" in service
    assert "EnvironmentFile=/etc/kivou/acquisition-runtime.env" in service
    assert service.count("ExecStart=") == 1
    assert (
        "ExecStart=/usr/bin/flock --verbose --nonblock --conflict-exit-code 0 "
        "/run/kivou/acquisition.lock /srv/kivou/app/.venv/bin/python -m "
        "signals.acquisition_runtime run-once"
    ) in service
    assert "RuntimeDirectory=kivou" in service
    assert "TimeoutStartSec=25min" in service
    assert "TimeoutStopSec=90s" in service
    assert "UMask=0077" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=true" in service
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in service
    assert "ReadWritePaths=/run/kivou /var/lib/kivou/hermes-shadow" in service
    assert "--allow-qa-provider-mutations" not in service


def test_acquisition_timer_is_persistent_and_non_overlapping() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnCalendar=hourly" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=300" in timer
    assert "AccuracySec=60" in timer
    assert "Unit=kivou-acquisition.service" in timer
    assert "WantedBy=timers.target" in timer


def test_runtime_examples_are_redacted_closed_and_schema_valid() -> None:
    environment = RUNTIME_ENV.read_text(encoding="utf-8")
    document = RUNTIME_CONFIG.read_text(encoding="utf-8")
    repository_environment = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "KIVOU_ACQUISITION_RUNTIME_CONFIG=/etc/kivou/acquisition-runtime.json" in environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT=" in environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT_KEY=" in environment
    assert "KIVOU_ACQUISITION_RUNTIME_CONFIG=" in repository_environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT=" in repository_environment
    assert "KIVOU_ACQUISITION_QA_RECIPIENT_KEY=" in repository_environment
    assert "@" not in environment
    deployment = AcquisitionRuntimeDeployment.model_validate_json(document)
    assert deployment.qa_only is True
    assert deployment.mode.value == "SHADOW"
    assert deployment.limits.maximum_suppliers == 1
    assert deployment.limits.maximum_contacts == 1
    assert deployment.limits.maximum_provider_operations <= 3


def test_runbook_keeps_timer_non_mutating_and_manual_provider_gate_explicit() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "python -m signals.acquisition_runtime run-once" in runbook
    assert "--allow-qa-provider-mutations" in runbook
    assert "list-runtime-approvals" in runbook
    assert "approve-runtime-approval" in runbook
    assert "open-runtime-qa-policy-window" in runbook
    assert "close-runtime-qa-policy-window" in runbook
    assert "--duration-seconds 1800" in runbook
    assert "--expires-at" not in runbook
    assert "refusent tout remplacement en ligne de commande de la base" in runbook
    assert "--database-url" not in runbook
    assert "python -m signals.operations health" in runbook
    assert "python -m signals.operations readiness" in runbook
    assert "activate-kill-switch" in runbook
    assert runbook.count("--property=RuntimeMaxSec=20min") >= 2
    assert runbook.count("/usr/bin/flock --verbose --nonblock") >= 2
    assert "journalctl -u kivou-acquisition.service" in runbook
    assert "from alembic import command" in runbook
    assert "alembic_config" in runbook
    assert "create_database_engine" in runbook
    assert 'command.downgrade(config, "0025_alert_recipient_context")' in runbook
    assert "/srv/kivou/app/.venv/bin/alembic" not in runbook
    assert runbook.index("command.downgrade") < runbook.index(
        "Restaurer ensuite l’artefact applicatif précédent"
    )
    assert runbook.count("--property=EnvironmentFile=/etc/kivou/acquisition-shadow.env") >= 2
    assert "systemctl disable --now kivou-acquisition.timer" in runbook
    assert runbook.count("systemctl enable --now kivou-acquisition.timer") == 1
    assert "0026_acquisition_runtime" in runbook
    assert "client" not in runbook.casefold()
    assert "prospect" in runbook.casefold()


def test_manual_policy_window_commands_load_the_staging_acquisition_environment() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert runbook.count(
        "--property=EnvironmentFile=/etc/kivou/acquisition-shadow.env"
    ) >= 4


def test_manual_runtime_commands_create_the_host_lock_directory() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert runbook.count("--property=RuntimeDirectory=kivou") >= 2
    assert runbook.count("--property=RuntimeDirectoryMode=0700") >= 2


def test_operations_runbook_documents_the_full_atomic_webhook_bundle() -> None:
    section = OPS_README.read_text(encoding="utf-8").split(
        "## Reverse proxy public de staging (#84)", 1
    )[1]
    required = {
        "KIVOU_INSTANTLY_WEBHOOK_SECRET",
        "KIVOU_INSTANTLY_WORKSPACE_REF",
        "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY",
        "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION",
        "KIVOU_SUPPRESSION_HMAC_KEY",
        "KIVOU_SUPPRESSION_HMAC_KEY_VERSION",
        "KIVOU_RESPONSE_SOURCE_HMAC_KEY",
        "KIVOU_RESPONSE_SOURCE_HMAC_KEY_VERSION",
        "KIVOU_RESPONSE_CONTENT_HMAC_KEY",
        "KIVOU_RESPONSE_CONTENT_HMAC_KEY_VERSION",
    }
    retained = {
        "KIVOU_INSTANTLY_WEBHOOK_RETAINED_FINGERPRINT_KEYS_JSON",
        "KIVOU_SUPPRESSION_RETAINED_KEYS_JSON",
        "KIVOU_RESPONSE_SOURCE_RETAINED_KEYS_JSON",
        "KIVOU_RESPONSE_CONTENT_RETAINED_KEYS_JSON",
    }
    normalized_section = " ".join(section.split())

    assert all(name in section for name in required)
    assert all(name in section for name in retained)
    assert "huit versions par keyring, clé courante comprise" in normalized_section
    assert "conserver son secret dans le keyring correspondant" in normalized_section
    assert "KIVOU_SUPPRESSION_IDENTITY_KEY" not in section


def test_the_production_unit_never_reads_a_staging_environment_file() -> None:
    from pathlib import Path

    unit = Path("ops/systemd/kivou-acquisition-production.service").read_text(
        encoding="utf-8"
    )
    assert "EnvironmentFile=/etc/kivou/production.env" in unit
    assert "EnvironmentFile=/etc/kivou/acquisition-production.env" in unit
    for forbidden in (
        "staging.env",
        "acquisition-shadow.env",
        "acquisition-runtime.env",
        "--allow-qa-provider-mutations",
    ):
        assert forbidden not in unit
    for hardening in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "PrivateTmp=true",
        "RestrictSUIDSGID=true",
        "UMask=0077",
    ):
        assert hardening in unit


def test_the_production_example_declares_production_and_no_fallback_recipient() -> None:
    from pathlib import Path

    example = Path("ops/examples/acquisition-production.env.example").read_text(
        encoding="utf-8"
    )
    assert "KIVOU_ACQUISITION_ENVIRONMENT=PRODUCTION" in example
    assert "QA_RECIPIENT" not in example


def test_the_production_document_example_carries_no_qa_binding() -> None:
    import json
    from pathlib import Path

    document = json.loads(
        Path("ops/examples/acquisition-production.json.example").read_text(
            encoding="utf-8"
        )
    )
    assert document["schema_version"] == "acquisition-production-v1"
    for forbidden in (
        "qa_only",
        "qa_recipient_identity_hmac",
        "qa_recipient_key_version",
        "qa_provider_mutations_capable",
        "allowed_opportunity_keys",
    ):
        assert forbidden not in document


def test_the_production_connectivity_example_is_schema_valid_and_redacted() -> None:
    from pathlib import Path

    from signals.acquisition_connectivity.contracts import ShadowConnectivityDocument

    path = Path("ops/examples/acquisition-production-connectivity.json.example")
    document = ShadowConnectivityDocument.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    assert len(document.mailboxes) == 3
    assert len({item.mailbox_ref for item in document.mailboxes}) == 3


def test_the_production_runbook_covers_the_full_bring_up_sequence() -> None:
    from pathlib import Path

    runbook = Path("docs/runbooks/12-acquisition-production-shadow.md").read_text(
        encoding="utf-8"
    )
    assert "0029_production_observation" in runbook
    assert "command.upgrade" in runbook
    assert "command.downgrade" in runbook
    assert "signals.operations" in runbook
    assert "bootstrap-policy-control" in runbook
    assert "--reason-code ACQUISITION_PRODUCTION_SHADOW" in runbook
    assert "--daily-cost-cap 30.00" in runbook
    assert "--country FR --language fr --wedge" in runbook
    assert "--database-url" not in runbook
    assert "python -m signals.acquisition_runtime check-dependencies" in runbook
    assert "python -m signals.acquisition_runtime run-once" in runbook
    assert "kivou-acquisition-production.service" in runbook
    assert "kivou-acquisition-production.timer" in runbook
    assert "EnvironmentFile=/etc/kivou/production.env" in runbook
    assert "EnvironmentFile=/etc/kivou/acquisition-production.env" in runbook
    assert "EnvironmentFile=/etc/kivou/staging.env" not in runbook
    assert "acquisition-runtime.env" not in runbook


def test_the_runbooks_multi_command_blocks_fail_fast() -> None:
    """Pin `set -euo pipefail` on the runbook's known multi-command blocks.

    A general "does this fenced ```bash block contain more than one
    command" check was considered and rejected as brittle: several blocks
    in this runbook pass a multi-line ``python -c '...'`` argument (a
    single quoted string spanning many physical lines) to one command. A
    naive line- or backslash-continuation-based counter misreads each
    Python line inside that quoted argument as a separate shell command,
    which would either demand a pointless ``set -euo pipefail`` on blocks
    that are genuinely one command, or require bespoke exceptions that
    silently drift out of sync with the prose. A real fix would need an
    actual shell parser (e.g. `bashlex`), which is disproportionate for a
    documentation-linting property.

    Instead, this anchors on a unique, stable substring from each block
    that this task's review identified as safety-critical and
    multi-command, and asserts that block starts with `set -euo pipefail`
    — precise for the known set, not a general claim about every block.
    """
    from pathlib import Path

    runbook = Path("docs/runbooks/12-acquisition-production-shadow.md").read_text(
        encoding="utf-8"
    )
    fenced_blocks = [
        block.split("\n```", 1)[0]
        for block in runbook.split("```bash\n")[1:]
    ]
    # Each anchor identifies one specific multi-command block that must be
    # fail-fast: a `test` (or `install`/`systemd-analyze`) in the middle of
    # the block failing silently must not let later commands run anyway.
    multi_command_anchors = (
        "kivou-backup-pre-0029",  # backup, then apply migration 0029
        "kivou_credential_isolation_check",  # Apollo/Instantly isolation gate
        "git clone --no-checkout",  # Hermes pin: clone, checkout, verify commit/tag
        "hermes-shadow-config.yaml",  # provision env/JSON/Hermes HOME files
        "sudo systemd-analyze verify",  # install units, verify, then reload
        "systemctl list-timers",  # enable timer, then inspect it
        "sudo systemctl stop kivou-acquisition-production.service",  # rollback teardown
    )
    for anchor in multi_command_anchors:
        matches = [block for block in fenced_blocks if anchor in block]
        assert len(matches) == 1, f"expected exactly one block containing {anchor!r}"
        first_line = matches[0].split("\n", 1)[0]
        assert first_line == "set -euo pipefail", (
            f"block containing {anchor!r} must start with 'set -euo pipefail', "
            f"got {first_line!r}"
        )
