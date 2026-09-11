from __future__ import annotations

from fastapi.testclient import TestClient
from test_prospection_actions_service import NOW, TARGET_ID, LinkIssuer, MxVerifier, seed

from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.prospection_actions.service import ProspectionActions

ORIGIN_SECRET = "s" * 40


def headers() -> dict[str, str]:
    return {FOUNDER_USER_HEADER: "rodrigue", ORIGIN_SECRET_HEADER: ORIGIN_SECRET}


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
