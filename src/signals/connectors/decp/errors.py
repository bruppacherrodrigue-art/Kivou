from __future__ import annotations

from typing import Literal

FailureCategory = Literal[
    "timeout",
    "rate_limited",
    "server_error",
    "unauthorized",
    "client_error",
    "network",
    "malformed",
    "source_limit",
]


class DecpError(Exception):
    """Base class for operational DECP failures."""


class DecpWindowLimitError(DecpError):
    """A bounded source window cannot be proven complete safely."""

    category: FailureCategory = "source_limit"


class DecpHttpError(DecpError):
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
