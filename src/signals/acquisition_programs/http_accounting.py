"""Minimal, injectable accounting for public legal-page HTTP attempts.

An HTTP attempt emits STARTED before the request and one terminal event using
the same identifier. A durable sink may insert on STARTED and update on the
terminal event. Sink failures stop the resolver; they must never be ignored.
No response body, full URL, exception text, address or credential is included.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

RequestType = Literal["CACHE", "DNS", "ROBOTS", "ROBOTS_POLICY", "HOMEPAGE", "LEGAL_PAGE",
                      "OFFICIAL_API"]
Outcome = Literal[
    "STARTED", "CACHE_HIT", "CACHE_MISS", "DNS_PUBLIC", "DNS_REJECTED", "DNS_ERROR",
    "ROBOTS_ALLOWED", "ROBOTS_BLOCKED", "ROBOTS_UNAVAILABLE", "HTTP_OK",
    "HTTP_STATUS", "REDIRECT_BLOCKED", "CONTENT_TYPE_REJECTED", "SIZE_LIMIT",
    "TIMEOUT", "TLS_ERROR", "CONNECT_ERROR", "NETWORK_ERROR",
]


@dataclass(frozen=True, slots=True)
class LegalHttpAttempt:
    """A content-free accounting record; ``attempt_id`` links start and finish."""

    attempt_id: str
    run_id: str | None
    company_id: str | None
    domain: str
    request_type: RequestType
    occurred_at: dt.datetime
    outcome: Outcome
    http_status: int | None = None


LegalHttpAttemptSink = Callable[[LegalHttpAttempt], None]


class AttemptAccountingError(RuntimeError):
    """A sink could not account for an attempted request; stop before continuing."""
