from __future__ import annotations

from time import perf_counter

import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_prospection_actions_send import Suppressions, _seed_second_target
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.contracts import ApproveCommand
from signals.prospection_actions.service import ProspectionActions

ORIGIN_SECRET = "s" * 40


def headers() -> dict[str, str]:
    return {FOUNDER_USER_HEADER: "rodrigue", ORIGIN_SECRET_HEADER: ORIGIN_SECRET}


class ProviderMustNotBeTouched:
    def deliver(self, **_kwargs):
        raise AssertionError("the HTTP request must not deliver prospects")


def _send_client(migrated_sqlite_engine, tmp_path):
    seed(migrated_sqlite_engine)
    second_target_id = _seed_second_target(migrated_sqlite_engine)
    provider = ProviderMustNotBeTouched()
    actions = ProspectionActions(
        migrated_sqlite_engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
        suppression_checker=Suppressions(),
        delivery_provider=provider,
        kill_switch_path=tmp_path / "acquisition.disabled",
        clock=lambda: NOW,
    )
    actions.approve(
        ApproveCommand(target_id=TARGET_ID, expected_version=1), actor="rodrigue@kivou.eu"
    )
    actions.approve(
        ApproveCommand(target_id=second_target_id, expected_version=1),
        actor="rodrigue@kivou.eu",
    )
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret=ORIGIN_SECRET,
        ),
        prospection_actions=actions,
        now_override=lambda: NOW,
    )
    return TestClient(app), migrated_sqlite_engine, second_target_id


def _command_payload(
    second_target_id: str, *, request_id: str = "484be03d-fbe4-46b1-9900-b99b4068fcbd"
):
    return {
        "request_id": request_id,
        "targets": [
            {"target_id": TARGET_ID, "expected_version": 2},
            {"target_id": second_target_id, "expected_version": 2},
        ],
    }


def _row_counts(engine) -> tuple[int, int]:
    with engine.connect() as connection:
        return (
            int(
                connection.scalar(sa.select(sa.func.count()).select_from(prospect_send_request))
                or 0
            ),
            int(connection.scalar(sa.select(sa.func.count()).select_from(prospect_send_item)) or 0),
        )


def test_send_queues_without_touching_provider_and_progress_is_durable(
    migrated_sqlite_engine, tmp_path
) -> None:
    client, _engine, second_target_id = _send_client(migrated_sqlite_engine, tmp_path)
    command_payload = _command_payload(second_target_id)
    expected_items = [
        {
            "target_id": TARGET_ID,
            "email_address": "contact@beton-bourbonnais.fr",
            "status": "queued",
            "error_code": None,
            "error_message": None,
        },
        {
            "target_id": second_target_id,
            "email_address": "contact@alpha-beton.fr",
            "status": "queued",
            "error_code": None,
            "error_message": None,
        },
    ]

    with client:
        started_at = perf_counter()
        response = client.post(
            "/api/founder/actions/prospection/send",
            headers=headers(),
            json=command_payload,
        )
        elapsed = perf_counter() - started_at

        assert response.status_code == 202
        assert elapsed < 1
        assert response.json() == {
            "version": "founder-prospection-send-v2",
            "request_id": command_payload["request_id"],
            "status": "queued",
            "total_count": 2,
            "processed_count": 0,
            "sent_count": 0,
            "failed_count": 0,
            "status_url": f"/api/founder/actions/prospection/send/{command_payload['request_id']}",
            "items": expected_items,
        }

        progress = client.get(response.json()["status_url"], headers=headers())

    assert progress.status_code == 200
    assert progress.json()["request_id"] == command_payload["request_id"]
    assert progress.json()["items"] == expected_items


def test_send_replay_returns_existing_progress_without_new_rows_or_mutations(
    migrated_sqlite_engine, tmp_path
) -> None:
    client, engine, second_target_id = _send_client(migrated_sqlite_engine, tmp_path)
    command_payload = _command_payload(second_target_id)

    with client:
        first = client.post(
            "/api/founder/actions/prospection/send", headers=headers(), json=command_payload
        )
        counts_before_replay = _row_counts(engine)
        with engine.connect() as connection:
            targets_before_replay = tuple(
                connection.execute(
                    sa.select(
                        prospect_target.c.target_id,
                        prospect_target.c.status,
                        prospect_target.c.version,
                        prospect_target.c.send_request_id,
                    ).order_by(prospect_target.c.target_id)
                ).all()
            )
        replay = client.post(
            "/api/founder/actions/prospection/send", headers=headers(), json=command_payload
        )

    with engine.connect() as connection:
        targets_after_replay = tuple(
            connection.execute(
                sa.select(
                    prospect_target.c.target_id,
                    prospect_target.c.status,
                    prospect_target.c.version,
                    prospect_target.c.send_request_id,
                ).order_by(prospect_target.c.target_id)
            ).all()
        )
    assert first.status_code == replay.status_code == 202
    assert replay.json() == first.json()
    assert _row_counts(engine) == counts_before_replay == (1, 2)
    assert targets_after_replay == targets_before_replay


def test_send_rejects_request_id_fingerprint_conflict_without_new_rows(
    migrated_sqlite_engine, tmp_path
) -> None:
    client, engine, second_target_id = _send_client(migrated_sqlite_engine, tmp_path)
    command_payload = _command_payload(second_target_id)
    conflicting_payload = {
        **command_payload,
        "targets": list(reversed(command_payload["targets"])),
    }

    with client:
        assert (
            client.post(
                "/api/founder/actions/prospection/send", headers=headers(), json=command_payload
            ).status_code
            == 202
        )
        counts_before_conflict = _row_counts(engine)
        response = client.post(
            "/api/founder/actions/prospection/send",
            headers=headers(),
            json=conflicting_payload,
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "SEND_REQUEST_IDEMPOTENCY_CONFLICT",
        "message": "request_id a déjà un autre contenu",
        "target_ids": [],
    }
    assert _row_counts(engine) == counts_before_conflict == (1, 2)


def test_send_progress_hides_request_accounting_and_only_exposes_public_item_errors(
    migrated_sqlite_engine, tmp_path
) -> None:
    client, engine, second_target_id = _send_client(migrated_sqlite_engine, tmp_path)
    command_payload = _command_payload(second_target_id)

    with client:
        assert (
            client.post(
                "/api/founder/actions/prospection/send", headers=headers(), json=command_payload
            ).status_code
            == 202
        )
        with engine.begin() as connection:
            connection.execute(
                sa.update(prospect_send_request)
                .where(prospect_send_request.c.request_id == command_payload["request_id"])
                .values(result={"provider_response": "private", "daily_remaining": 23})
            )
            connection.execute(
                sa.update(prospect_send_item)
                .where(prospect_send_item.c.target_id == TARGET_ID)
                .values(
                    status="failed", error_code="invalid_email", error_message="Adresse invalide"
                )
            )
        progress = client.get(
            f"/api/founder/actions/prospection/send/{command_payload['request_id']}",
            headers=headers(),
        )

    assert progress.status_code == 200
    assert progress.json()["items"][0] == {
        "target_id": TARGET_ID,
        "email_address": "contact@beton-bourbonnais.fr",
        "status": "failed",
        "error_code": "invalid_email",
        "error_message": "Adresse invalide",
    }
    assert "result" not in progress.json()
    assert "provider_response" not in progress.json()


def test_send_progress_returns_structured_not_found_and_keeps_founder_authentication(
    migrated_sqlite_engine, tmp_path
) -> None:
    client, _engine, second_target_id = _send_client(migrated_sqlite_engine, tmp_path)

    with client:
        unknown = client.get(
            "/api/founder/actions/prospection/send/00000000-0000-0000-0000-000000000000",
            headers=headers(),
        )
        unauthenticated = client.get(
            "/api/founder/actions/prospection/send/00000000-0000-0000-0000-000000000000"
        )
        unauthenticated_post = client.post(
            "/api/founder/actions/prospection/send",
            json=_command_payload(second_target_id),
        )

    assert unknown.status_code == 404
    assert unknown.json() == {
        "detail": {
            "code": "SEND_REQUEST_NOT_FOUND",
            "message": "demande d'envoi introuvable",
            "target_ids": [],
        }
    }
    assert unauthenticated.status_code == 403
    assert unauthenticated_post.status_code == 403


def test_founder_action_routes_publish_list_and_closed_rejection(migrated_sqlite_engine) -> None:
    seed(migrated_sqlite_engine)
    actions = ProspectionActions(
        migrated_sqlite_engine,
        email_verifier=MxVerifier(),
        link_issuer=LinkIssuer(),
        clock=lambda: NOW,
    )
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret=ORIGIN_SECRET,
        ),
        prospection_actions=actions,
        now_override=lambda: NOW,
    )

    with TestClient(app) as client:
        listed = client.get(
            "/api/founder/actions/prospection/list?status=pending_review",
            headers=headers(),
        )
        rejected = client.post(
            "/api/founder/actions/prospection/reject",
            headers=headers(),
            json={
                "target_id": TARGET_ID,
                "expected_version": 1,
                "reason": "duplicate",
            },
        )

    assert listed.status_code == 200
    assert listed.json()["version"] == "founder-prospection-actions-v1"
    assert listed.json()["items"][0]["mail"]["text"].startswith("Bonjour,")
    assert rejected.status_code == 422
    assert rejected.json() == {
        "detail": {
            "code": "INVALID_REJECTION_REASON",
            "message": "requête d'action invalide",
            "target_ids": [],
        }
    }
