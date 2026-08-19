from __future__ import annotations

from typing import Literal

FailureCategory = Literal[
    "timeout", "rate_limited", "server_error", "unauthorized", "client_error", "network", "malformed"
]


class BoampError(Exception):
    """Base class for operational BOAMP failures."""


class BoampMalformedPayload(BoampError):
    """A response that may become processable after a source or code repair."""

    category: FailureCategory = "malformed"


class BoampHttpError(BoampError):
    def __init__(
        self,
        message: str,
        *,
        category: FailureCategory,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.url = url
