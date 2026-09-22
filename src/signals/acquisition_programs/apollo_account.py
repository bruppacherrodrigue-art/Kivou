"""Apollo account probes restricted to officially documented zero-credit endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from signals.supplier_discovery.apollo import APOLLO_BASE_URL

_MAX_BYTES = 1_048_576


@dataclass(frozen=True)
class ApolloAccountState:
    credential_valid: bool
    credit_balance: int | None
    usage_stats_available: bool
    rate_stats_available: bool
    credit_balances: dict[str, int] = field(default_factory=dict)
    organization_search_day_consumed: int | None = None
    organization_search_day_limit: int | None = None


class ApolloAccountProbe:
    """No account data or key appears in errors or returned state."""

    def __init__(self, *, api_key: str, client: httpx.Client) -> None:
        if not api_key:
            raise ValueError("dedicated Apollo key missing")
        self._api_key = api_key
        self._client = client

    def _get_json(self, method: str, path: str) -> dict | None:
        try:
            response = self._client.request(
                method, APOLLO_BASE_URL + path,
                headers={"x-api-key": self._api_key, "accept": "application/json"},
                timeout=5.0, follow_redirects=False,
            )
            if response.status_code != 200 or len(response.content) > _MAX_BYTES:
                return None
            body = response.json()
            return body if isinstance(body, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    def inspect_free(self) -> ApolloAccountState:
        health = self._get_json("GET", "/api/v1/auth/health")
        if (health is None or health.get("healthy") is not True or
                health.get("is_logged_in") is not True):
            return ApolloAccountState(False, None, False, False)
        credits = self._get_json("POST", "/api/v1/usage_stats/credit_usage_stats")
        rates = self._get_json("POST", "/api/v1/usage_stats/api_usage_stats")
        stats = (credits or {}).get("credit_usage_stats")
        balances: dict[str, int] = {}
        if isinstance(stats, dict):
            for name, item in stats.items():
                value = item.get("left_over") if isinstance(item, dict) else None
                if (isinstance(name, str) and isinstance(value, int) and
                        not isinstance(value, bool) and value >= 0):
                    balances[name] = value
        org = (rates or {}).get('["api/v1/mixed_companies", "search"]')
        day = org.get("day") if isinstance(org, dict) else None
        consumed = day.get("consumed") if isinstance(day, dict) else None
        limit = day.get("limit") if isinstance(day, dict) else None
        if not isinstance(consumed, int) or isinstance(consumed, bool) or consumed < 0:
            consumed = None
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            limit = None
        return ApolloAccountState(True, balances.get("lead_credit"), credits is not None,
                                  rates is not None, balances, consumed, limit)
