from __future__ import annotations

import json

from signals.documents.portals.policy import PortalPolicy


def test_default_policy_blocks_the_three_reviewed_portals(tmp_path) -> None:
    policy = PortalPolicy(tmp_path / "missing.json")

    assert policy.decision("https://www.marches-publics.info/dce").status == (
        "portal_blocked"
    )
    assert policy.decision("https://www.marches-publics.info/dce").reason == "captcha"
    assert policy.decision("https://www.marches-securises.fr/dce").status == (
        "cgu_restricted"
    )
    assert policy.decision("https://www.achatpublic.com/dce").reason == (
        "robots_disallowed"
    )


def test_policy_override_is_reloaded_without_restarting(tmp_path) -> None:
    path = tmp_path / "portal-policy.json"
    policy = PortalPolicy(path)
    url = "https://www.achatpublic.com/dce"
    assert policy.decision(url).status == "portal_blocked"

    path.write_text(
        json.dumps({"hosts": {"achatpublic.com": {"enabled": True}}}),
        encoding="utf-8",
    )

    assert policy.decision(url) is None


def test_invalid_override_fails_closed_to_reviewed_defaults(tmp_path) -> None:
    path = tmp_path / "portal-policy.json"
    path.write_text("not-json", encoding="utf-8")

    decision = PortalPolicy(path).decision("https://marches-publics.info/dce")

    assert decision is not None
    assert (decision.status, decision.reason) == ("portal_blocked", "captcha")
