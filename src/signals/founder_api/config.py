"""Fail-closed configuration for the separate Kivou Founder Console."""

from __future__ import annotations

import dataclasses
import os
import re
from typing import Literal

FOUNDER_ALLOWED_EMAIL_ENV = "KIVOU_FOUNDER_ALLOWED_EMAIL"
FOUNDER_ORIGIN_SECRET_ENV = "KIVOU_FOUNDER_ORIGIN_SECRET"
FOUNDER_HOSTNAME_ENV = "KIVOU_FOUNDER_HOSTNAME"
FOUNDER_ENVIRONMENT_ENV = "KIVOU_FOUNDER_ENVIRONMENT"

DEFAULT_FOUNDER_HOSTNAME = "control.kivou.eu"
FOUNDER_ENVIRONMENT: Literal["PRODUCTION"] = "PRODUCTION"
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


@dataclasses.dataclass(frozen=True)
class FounderApiConfig:
    """The founder surface has one operator, one host and no unsafe defaults."""

    allowed_email: str
    origin_secret: str = dataclasses.field(repr=False)
    hostname: str = DEFAULT_FOUNDER_HOSTNAME
    environment: Literal["PRODUCTION"] = FOUNDER_ENVIRONMENT

    def __post_init__(self) -> None:
        email = self.allowed_email.strip().lower()
        hostname = self.hostname.strip().lower().rstrip(".")
        if not _EMAIL_RE.fullmatch(email):
            raise ValueError(f"{FOUNDER_ALLOWED_EMAIL_ENV} n'est pas une adresse e-mail valide")
        if len(self.origin_secret.encode()) < 32:
            raise ValueError(f"{FOUNDER_ORIGIN_SECRET_ENV} doit contenir au moins 32 octets")
        if not _HOST_RE.fullmatch(hostname) or hostname != DEFAULT_FOUNDER_HOSTNAME:
            raise ValueError(
                f"{FOUNDER_HOSTNAME_ENV} doit être exactement {DEFAULT_FOUNDER_HOSTNAME}"
            )
        if self.environment != FOUNDER_ENVIRONMENT:
            raise ValueError(
                f"{FOUNDER_ENVIRONMENT_ENV} doit valoir {FOUNDER_ENVIRONMENT}"
            )
        object.__setattr__(self, "allowed_email", email)
        object.__setattr__(self, "hostname", hostname)

    @classmethod
    def from_environment(cls) -> FounderApiConfig:
        allowed_email = (os.environ.get(FOUNDER_ALLOWED_EMAIL_ENV) or "").strip()
        origin_secret = os.environ.get(FOUNDER_ORIGIN_SECRET_ENV) or ""
        hostname = os.environ.get(FOUNDER_HOSTNAME_ENV) or DEFAULT_FOUNDER_HOSTNAME
        environment = os.environ.get(FOUNDER_ENVIRONMENT_ENV) or ""
        missing = [
            name
            for name, value in (
                (FOUNDER_ALLOWED_EMAIL_ENV, allowed_email),
                (FOUNDER_ORIGIN_SECRET_ENV, origin_secret),
                (FOUNDER_ENVIRONMENT_ENV, environment),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "configuration Founder Console incomplète : " + ", ".join(missing)
            )
        return cls(
            allowed_email=allowed_email,
            origin_secret=origin_secret,
            hostname=hostname,
            environment=environment,  # type: ignore[arg-type]
        )


__all__ = [
    "DEFAULT_FOUNDER_HOSTNAME",
    "FOUNDER_ALLOWED_EMAIL_ENV",
    "FOUNDER_ENVIRONMENT",
    "FOUNDER_ENVIRONMENT_ENV",
    "FOUNDER_HOSTNAME_ENV",
    "FOUNDER_ORIGIN_SECRET_ENV",
    "FounderApiConfig",
]
