"""B1 account checks consume only Apollo's free credit ledger endpoint."""

import httpx

from signals.acquisition_programs.apollo_account import ApolloAccountProbe


def test_b1_credit_probe_reads_only_credit_usage_and_never_exposes_key() -> None:
    paths = []

    def answer(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["x-api-key"] == "test-secret"
        return httpx.Response(200, json={"credit_usage_stats": {
            "lead_credit": {"left_over": 1500},
        }})

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        state = ApolloAccountProbe(api_key="test-secret", client=client).inspect_credits_free()
    assert paths == ["/api/v1/usage_stats/credit_usage_stats"]
    assert state.credential_valid
    assert state.credit_balance == 1500
    assert "test-secret" not in repr(state)


def test_b1_credit_probe_fails_closed_on_rate_limit() -> None:
    with httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"retry-after": "120"}),
    )) as client:
        state = ApolloAccountProbe(api_key="test-secret", client=client).inspect_credits_free()
    assert state.credit_balance is None
    assert not state.credential_valid
    assert state.retry_after_seconds == 120
