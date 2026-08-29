"""Defense-in-depth boundary behind Cloudflare Access and Cloudflare Tunnel."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from signals.founder_api.config import FounderApiConfig

ACCESS_EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"
ACCESS_ASSERTION_HEADER = "Cf-Access-Jwt-Assertion"
ORIGIN_SECRET_HEADER = "X-Kivou-Founder-Origin-Secret"


@dataclass(frozen=True)
class FounderIdentity:
    email: str


def require_founder_identity(request: Request) -> FounderIdentity:
    """Accept only the configured operator through the trusted local proxy.

    Cloudflare Access performs the user authentication. The API additionally
    requires a secret injected by the localhost-only nginx vhost, so a caller
    cannot reach the process directly and merely forge Cloudflare headers.
    """

    config: FounderApiConfig = request.app.state.config
    supplied_secret = request.headers.get(ORIGIN_SECRET_HEADER, "")
    if not supplied_secret or not hmac.compare_digest(
        supplied_secret.encode(), config.origin_secret.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="accès Founder refusé",
        )

    assertion = request.headers.get(ACCESS_ASSERTION_HEADER, "")
    email = request.headers.get(ACCESS_EMAIL_HEADER, "").strip().lower()
    if not assertion or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentification Cloudflare Access requise",
        )
    if not hmac.compare_digest(email.encode(), config.allowed_email.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="accès Founder refusé",
        )
    return FounderIdentity(email=email)


FounderIdentityDependency = Annotated[FounderIdentity, Depends(require_founder_identity)]

__all__ = [
    "ACCESS_ASSERTION_HEADER",
    "ACCESS_EMAIL_HEADER",
    "ORIGIN_SECRET_HEADER",
    "FounderIdentity",
    "FounderIdentityDependency",
    "require_founder_identity",
]
