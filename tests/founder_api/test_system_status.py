from __future__ import annotations

import datetime as dt
import os
import subprocess
from collections import namedtuple
from decimal import Decimal

import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.acquisition_status import FounderAcquisitionActivity
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.read_models import FounderReadService
from signals.founder_api.system_status import FounderSystemHostReader
from signals.persistence.schema import METADATA, supplier_directory

NOW = dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC)
SHA = "a" * 40
DiskUsage = namedtuple("DiskUsage", "total used free")


def _engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(engine)
    return engine


def _stopped(_: dt.datetime) -> FounderAcquisitionActivity:
    return FounderAcquisitionActivity(activity="STOPPED", activity_since=NOW)


def _run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[str]:
    if "kivou-backup-local.service" in command:
        output = (
            "Id=kivou-backup-local.service\nLoadState=loaded\nActiveState=inactive\n"
            "Result=success\nExecMainExitTimestamp=Sat 2026-09-12 03:18:00 UTC\n\n"
            "Id=kivou-backup.service\nLoadState=loaded\nActiveState=inactive\n"
            "Result=success\nExecMainExitTimestamp=Sat 2026-09-12 03:24:00 UTC\n"
        )
    else:
        output = (
            "Id=kivou-alerts.timer\nLoadState=loaded\nActiveState=active\n"
            "LastTriggerUSec=Sat 2026-09-12 07:00:01 UTC\n"
            "NextElapseUSecRealtime=Sat 2026-09-12 09:00:00 UTC\n\n"
            "Id=kivou-disk-alert.timer\nLoadState=not-found\nActiveState=inactive\n"
            "LastTriggerUSec=n/a\nNextElapseUSecRealtime=n/a\n"
        )
    return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


def test_host_reader_reports_timers_readiness_disk_backups_and_release(tmp_path) -> None:
    release = tmp_path / f"production-{SHA}"
    release.mkdir()
    app_link = tmp_path / "app"
    app_link.symlink_to(release, target_is_directory=True)
    local_marker = tmp_path / "local-success"
    offsite_marker = tmp_path / "offsite-success"
    local_marker.touch()
    offsite_marker.touch()
    local_time = NOW - dt.timedelta(hours=5)
    offsite_time = NOW - dt.timedelta(hours=4)
    os.utime(local_marker, (local_time.timestamp(), local_time.timestamp()))
    os.utime(offsite_marker, (offsite_time.timestamp(), offsite_time.timestamp()))

    snapshot = FounderSystemHostReader(
        run=_run,
        http_probe=lambda url: 200 if url.endswith(":8000/openapi.json") else None,
        disk_usage=lambda _: DiskUsage(1_000, 720, 280),
        disk_path=tmp_path,
        app_link=app_link,
        local_backup_marker=local_marker,
        offsite_backup_marker=offsite_marker,
        timer_units=("kivou-alerts.timer", "kivou-disk-alert.timer"),
    )(NOW)

    assert [(item.name, item.state) for item in snapshot.timers] == [
        ("kivou-alerts.timer", "active"),
        ("kivou-disk-alert.timer", "absent"),
    ]
    assert snapshot.timers[0].last_run_at == dt.datetime(2026, 9, 12, 7, 0, 1, tzinfo=dt.UTC)
    assert snapshot.timers[0].next_run_at == dt.datetime(2026, 9, 12, 9, tzinfo=dt.UTC)
    assert [(item.name, item.status, item.http_status) for item in snapshot.readiness] == [
        ("API", "ready", 200),
        ("Founder", "unavailable", None),
    ]
    assert snapshot.disk.used_percent == Decimal("72.0")
    assert snapshot.backups[0].last_success_at == local_time
    assert snapshot.backups[1].last_success_at == offsite_time
    assert snapshot.deployed_sha == SHA


def test_system_route_is_read_only_and_aggregates_provider_costs(tmp_path) -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [
                {
                    "siren": "123456789",
                    "legal_name": "Entreprise du jour",
                    "legal_name_observed_at": NOW,
                    "family_keys": ["timber_carpentry"],
                    "families_observed_at": NOW,
                    "directors": [],
                    "enrichment_model_id": "anthropic/claude-sonnet-4.6",
                    "enrichment_cost_usd": Decimal("0.004200"),
                    "enrichment_evidence": {"query": "Entreprise du jour Lyon"},
                    "enrichment_observed_at": NOW - dt.timedelta(hours=1),
                    "created_at": NOW,
                    "updated_at": NOW,
                },
                {
                    "siren": "987654321",
                    "legal_name": "Entreprise du mois",
                    "legal_name_observed_at": NOW,
                    "family_keys": ["insulation"],
                    "families_observed_at": NOW,
                    "directors": [],
                    "enrichment_model_id": "anthropic/claude-sonnet-4.6",
                    "enrichment_cost_usd": Decimal("0.003000"),
                    "enrichment_evidence": {"query": "Entreprise du mois Annecy"},
                    "enrichment_observed_at": NOW - dt.timedelta(days=3),
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            ],
        )

    host = FounderSystemHostReader(
        run=_run,
        http_probe=lambda _: 200,
        disk_usage=lambda _: DiskUsage(1_000, 720, 280),
        disk_path=tmp_path,
        app_link=tmp_path / "missing-app",
        local_backup_marker=tmp_path / "missing-local",
        offsite_backup_marker=tmp_path / "missing-offsite",
        timer_units=("kivou-alerts.timer",),
    )
    service = FounderReadService(engine, timer_reader=_stopped, system_host_reader=host)
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret="s" * 40,
        ),
        now_override=lambda: NOW,
        read_service=service,
    )
    headers = {
        FOUNDER_USER_HEADER: "rodrigue",
        ORIGIN_SECRET_HEADER: "s" * 40,
    }

    with TestClient(app) as client:
        response = client.get("/api/founder/system", headers=headers)
        forbidden = client.post("/api/founder/system", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "founder-system-v1"
    assert payload["read_only"] is True
    assert payload["database_access"] == "READ_ONLY"
    assert payload["provider_costs"] == [
        {
            "provider": "OpenRouter",
            "unit": "USD",
            "today": "0.004200",
            "month": "0.007200",
        },
        {"provider": "Serper", "unit": "request", "today": "1", "month": "2"},
        {"provider": "Apollo", "unit": "credit", "today": "0", "month": "0"},
        {"provider": "Instantly", "unit": "credit", "today": "0", "month": "0"},
    ]
    assert forbidden.status_code == 405
