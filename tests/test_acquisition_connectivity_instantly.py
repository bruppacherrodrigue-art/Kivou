from __future__ import annotations

import datetime as dt

import httpx
import pytest

from signals.acquisition_connectivity.contracts import (
    ConnectivityErrorCode,
    ConnectivityFailure,
    ShadowConnectivityDocument,
)
from signals.acquisition_connectivity.instantly import InstantlyConnectivityProbe
from signals.campaigns.contracts import MailboxReadinessState
from signals.campaigns.instantly import (
    HttpInstantlyProvider,
    InstantlyMailboxReadinessSource,
    normalize_mailbox_readiness,
)

NOW = dt.datetime(2026, 8, 24, 12, tzinfo=dt.UTC)


def _document(workspace: str = "workspace-staging-ref") -> ShadowConnectivityDocument:
    return ShadowConnectivityDocument.model_validate(
        {
            "schema_version": "acquisition-shadow-connectivity-v1",
            "instantly_workspace_ref": workspace,
            "mailboxes": [
                {
                    "mailbox_ref": "mailbox-staging-01",
                    "provider_account_id": "one+staging@example.com",
                },
                {
                    "mailbox_ref": "mailbox-staging-02",
                    "provider_account_id": "two@example.com",
                },
                {
                    "mailbox_ref": "mailbox-staging-03",
                    "provider_account_id": "three@example.com",
                },
            ],
        }
    )


def _ready_account(**updates: object) -> dict[str, object]:
    account: dict[str, object] = {
        "status": 1,
        "warmup_status": 1,
        "setup_pending": False,
        "daily_limit": 3,
        "sending_gap": 10,
        "tracking_domain_status": "active",
        "email": "must-never-leave-provider-boundary@example.com",
        "signature": "must-never-leave-provider-boundary",
    }
    account.update(updates)
    return account


def _probe(handler) -> InstantlyConnectivityProbe:
    provider = HttpInstantlyProvider(
        api_key="synthetic-instantly-value",
        client=httpx.Client(transport=httpx.MockTransport(handler), timeout=10),
    )
    return InstantlyConnectivityProbe(
        provider=provider,
        mailbox_readiness=InstantlyMailboxReadinessSource(provider),
    )


def test_probe_reuses_provider_and_normalizer_for_four_official_gets() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/workspaces/current"):
            return httpx.Response(200, json={"id": "workspace-staging-ref"})
        return httpx.Response(200, json=_ready_account())

    evidence = _probe(handler).check(_document(), observed_at=NOW)

    assert [request.method for request in requests] == ["GET"] * 4
    assert [request.url.raw_path.decode() for request in requests] == [
        "/api/v2/workspaces/current",
        "/api/v2/accounts/one%2Bstaging%40example.com",
        "/api/v2/accounts/two%40example.com",
        "/api/v2/accounts/three%40example.com",
    ]
    assert all(
        request.headers["authorization"] == "Bearer synthetic-instantly-value"
        for request in requests
    )
    assert all(request.content == b"" for request in requests)
    assert evidence.workspace == "BOUND"
    assert evidence.mailboxes_ready == 3
    assert evidence.mailboxes_total == 3
    assert "@" not in repr(evidence)


def test_official_numeric_account_statuses_use_the_existing_normalizer() -> None:
    readiness = normalize_mailbox_readiness(_ready_account(), observed_at=NOW)

    assert readiness.state is MailboxReadinessState.READY
    assert readiness.sending_gap_seconds == 600


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"status": 2}, MailboxReadinessState.TEMPORARILY_UNAVAILABLE),
        ({"status": 3}, MailboxReadinessState.TEMPORARILY_UNAVAILABLE),
        ({"status": -1}, MailboxReadinessState.UNHEALTHY),
        ({"status": -2}, MailboxReadinessState.UNHEALTHY),
        ({"status": -3}, MailboxReadinessState.UNHEALTHY),
        ({"warmup_status": 0}, MailboxReadinessState.TEMPORARILY_UNAVAILABLE),
        ({"warmup_status": -1}, MailboxReadinessState.UNHEALTHY),
        ({"warmup_status": -2}, MailboxReadinessState.UNHEALTHY),
        ({"warmup_status": -3}, MailboxReadinessState.UNHEALTHY),
        ({"status": 99}, MailboxReadinessState.UNKNOWN),
    ],
)
def test_non_ready_official_states_fail_closed(
    updates: dict[str, object], expected: MailboxReadinessState
) -> None:
    assert normalize_mailbox_readiness(
        _ready_account(**updates), observed_at=NOW
    ).state is expected

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/workspaces/current"):
            return httpx.Response(200, json={"id": "workspace-staging-ref"})
        return httpx.Response(200, json=_ready_account(**updates))

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check(_document(), observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.MAILBOX_NOT_READY
    assert "@" not in str(caught.value)


def test_workspace_mismatch_stops_before_any_mailbox_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "other-workspace"})

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check(_document(), observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.WORKSPACE_MISMATCH
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": 12}, [], None])
def test_workspace_response_requires_one_bounded_identity(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check(_document(), observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ConnectivityErrorCode.AUTH),
        (402, ConnectivityErrorCode.PLAN_REQUIRED),
        (403, ConnectivityErrorCode.PERMISSION),
        (429, ConnectivityErrorCode.RATE_LIMITED),
        (500, ConnectivityErrorCode.SERVER_ERROR),
    ],
)
def test_existing_provider_errors_map_without_retry(
    status: int, code: ConnectivityErrorCode
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Retry-After": "11"})

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check(_document(), observed_at=NOW)

    assert caught.value.code is code
    assert calls == 1
    assert caught.value.retry_after_seconds == (11 if status == 429 else None)


def test_existing_provider_response_bound_is_preserved() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 1_048_577)

    with pytest.raises(ConnectivityFailure) as caught:
        _probe(handler).check(_document(), observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.MALFORMED_RESPONSE
