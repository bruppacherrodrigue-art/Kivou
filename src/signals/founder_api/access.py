"""Defense-in-depth boundary behind the Founder reverse proxy."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from signals.founder_api.config import FounderApiConfig

FOUNDER_USER_HEADER = "X-Kivou-Founder-User"
ORIGIN_SECRET_HEADER = "X-Kivou-Founder-Origin-Secret"


@dataclass(frozen=True)
class FounderIdentity:
    email: str


def require_founder_identity(request: Request) -> FounderIdentity:
    """Accept only the configured operator through the trusted local proxy.

    The API requires both the authenticated username and a secret injected by
    the localhost-only nginx vhost, so direct callers fail closed.
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

    user = request.headers.get(FOUNDER_USER_HEADER, "")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentification Founder requise",
        )
    if not hmac.compare_digest(user.encode(), config.allowed_user.encode()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="accès Founder refusé",
        )
    return FounderIdentity(email=config.allowed_email)


FounderIdentityDependency = Annotated[FounderIdentity, Depends(require_founder_identity)]

__all__ = [
    "FOUNDER_USER_HEADER",
    "ORIGIN_SECRET_HEADER",
    "FounderIdentity",
    "FounderIdentityDependency",
    "require_founder_identity",
]
