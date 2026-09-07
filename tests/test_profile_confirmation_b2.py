"""B2: a materializable QA profile still requires explicit confirmation."""
from __future__ import annotations

from test_qa_attribution import issue

pytest_plugins = ("test_qa_attribution",)


def test_qa_confirmation_state_is_shared_and_confirmation_keeps_signals(prepared_qa):
    _, client, opportunity = prepared_qa
    landed = client.get(f"/a/{issue(opportunity)}", follow_redirects=False)
    assert landed.status_code == 303
    assert client.get("/me").json()["provisional_profile"] is True
    profiles = client.get("/target-icps").json()
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["provisional"] is True
    path = f"/target-icps/{profile['target_icp_id']}"
    assert client.get(path).json()["provisional"] is True
    changed = client.patch(path, headers={"Origin": "https://kivou.test"}, json={
        "label": profile["label"],
        "customer_input": {**profile["customer_input"], "offer_summary": "Panneaux et accessoires sur mesure"},
    })
    assert changed.status_code == 200, changed.text
    me = client.get("/me").json()
    assert me["onboarding_status"] == "ready_for_signals"
    assert me["provisional_profile"] is False
    confirmed = client.get("/target-icps").json()
    assert len(confirmed) == 1
    assert confirmed[0]["target_icp_id"] == profile["target_icp_id"]
    assert confirmed[0]["provisional"] is False
    assert client.get(path).json()["provisional"] is False
    assert len(client.get("/dashboard").json()["top3"]) >= 1
