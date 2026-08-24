"""Apollo deployment composition plus the two missing zero-credit identity GETs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import httpx

from signals.acquisition_connectivity.contracts import (
    ApolloIdentityEvidence,
    ConnectivityErrorCode,
    ConnectivityFailure,
)
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient

APOLLO_HEALTH_URL = "https://api.apollo.io/api/v1/auth/health"
APOLLO_PROFILE_URL = "https://api.apollo.io/api/v1/users/api_profile"
APOLLO_IDENTITY_TIMEOUT_SECONDS = 10.0
MAX_APOLLO_IDENTITY_RESPONSE_BYTES = 65_536


class ApolloIdentityProbe:
    """Permit only Apollo's documented authentication and acting-profile reads."""

    def __init__(self, *, api_key: str, client: httpx.Client) -> None:
        if not api_key.strip():
            raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED)
        self._api_key = api_key
        self._client = client

    def check(self) -> ApolloIdentityEvidence:
        health = self._get(APOLLO_HEALTH_URL)
        if not isinstance(health, dict):
            raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)
        healthy = health.get("healthy")
        logged_in = health.get("is_logged_in")
        if not isinstance(healthy, bool) or not isinstance(logged_in, bool):
            raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)
        if not healthy or not logged_in:
            raise ConnectivityFailure(ConnectivityErrorCode.AUTH)

        profile = self._get(APOLLO_PROFILE_URL)
        if not isinstance(profile, dict):
            raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)
        acting_user_id = profile.get("id")
        if (
            not isinstance(acting_user_id, str)
            or not acting_user_id.strip()
            or len(acting_user_id.strip()) > 256
        ):
            raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)
        fingerprint = hashlib.sha256(
            b"apollo-acting-user:v1\0" + acting_user_id.strip().encode("utf-8")
        ).hexdigest()
        return ApolloIdentityEvidence(acting_profile_fingerprint=fingerprint)

    def _get(self, url: str) -> object:
        try:
            with self._client.stream(
                "GET",
                url,
                headers={"x-api-key": self._api_key, "accept": "application/json"},
                timeout=APOLLO_IDENTITY_TIMEOUT_SECONDS,
            ) as response:
                self._raise_for_status(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > MAX_APOLLO_IDENTITY_RESPONSE_BYTES:
                        raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)
                    body.extend(chunk)
        except ConnectivityFailure:
            raise
        except httpx.TimeoutException:
            raise ConnectivityFailure(ConnectivityErrorCode.TIMEOUT) from None
        except httpx.RequestError:
            raise ConnectivityFailure(ConnectivityErrorCode.NETWORK) from None
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE) from None

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        code = {
            401: ConnectivityErrorCode.AUTH,
            402: ConnectivityErrorCode.PLAN_REQUIRED,
            403: ConnectivityErrorCode.PERMISSION,
            429: ConnectivityErrorCode.RATE_LIMITED,
        }.get(response.status_code)
        if code is None and response.status_code >= 500:
            code = ConnectivityErrorCode.SERVER_ERROR
        if code is None and response.status_code >= 400:
            code = ConnectivityErrorCode.MALFORMED_RESPONSE
        if code is None:
            return
        retry_after = response.headers.get("Retry-After")
        raise ConnectivityFailure(
            code,
            retry_after_seconds=(
                int(retry_after) if code is ConnectivityErrorCode.RATE_LIMITED and retry_after
                and retry_after.isdigit() else None
            ),
        )


@dataclass(frozen=True)
class ApolloComponents:
    """Existing Apollo clients plus the deployment-only identity probe."""

    organization_search: ApolloOrganizationSearchClient
    contact_discovery: ApolloContactDiscoveryClient
    company_research: ApolloCompanyResearchClient
    identity: ApolloIdentityProbe


def build_apollo_components(
    *, api_key: str, client: httpx.Client
) -> ApolloComponents:
    """Wire one protected key into the three existing clients and identity probe."""
    return ApolloComponents(
        organization_search=ApolloOrganizationSearchClient(api_key=api_key, client=client),
        contact_discovery=ApolloContactDiscoveryClient(api_key=api_key, client=client),
        company_research=ApolloCompanyResearchClient(api_key=api_key, client=client),
        identity=ApolloIdentityProbe(api_key=api_key, client=client),
    )
