"""Narrow, read-only Instantly Email API V2 adapter for exact reply resolution."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import deque
from collections.abc import Callable
from typing import Annotated, Literal, Protocol

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from signals.campaigns.instantly import (
    INSTANTLY_V2_BASE_URL,
    MAX_PROVIDER_RESPONSE_BYTES,
    InstantlyErrorCode,
    InstantlyProviderError,
)

INSTANTLY_EMAIL_SCOPE = "emails:read"
KIVOU_EMAIL_REQUESTS_PER_WORKSPACE_MINUTE = 10

BoundedEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)
]


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("email timestamp must be timezone-aware")
    return value


def _uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("provider Email identity must be a UUID") from exc


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ListEmailsQuery(_StrictModel):
    campaign_id: str
    lead: BoundedEmail
    eaccount: BoundedEmail | None = None
    email_type: Literal["received"] = "received"
    min_timestamp_created: dt.datetime
    max_timestamp_created: dt.datetime
    sort_order: Literal["asc"] = "asc"
    limit: int = Field(default=100, ge=1, le=100)
    starting_after: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ] | None = None

    _campaign = field_validator("campaign_id")(_uuid)
    _timestamps = field_validator(
        "min_timestamp_created", "max_timestamp_created"
    )(_aware)

    @model_validator(mode="after")
    def bounded_resolution_interval(self) -> ListEmailsQuery:
        duration = self.max_timestamp_created - self.min_timestamp_created
        if duration <= dt.timedelta(0) or duration > dt.timedelta(minutes=20):
            raise ValueError("email resolution interval must be within 20 minutes")
        return self

    def query_params(self) -> dict[str, object]:
        def instant(value: dt.datetime) -> str:
            return value.astimezone(dt.UTC).isoformat(timespec="seconds").replace(
                "+00:00", "Z"
            )

        values: dict[str, object] = {
            "campaign_id": self.campaign_id,
            "lead": self.lead,
            "email_type": self.email_type,
            "min_timestamp_created": instant(self.min_timestamp_created),
            "max_timestamp_created": instant(self.max_timestamp_created),
            "sort_order": self.sort_order,
            "limit": self.limit,
        }
        if self.eaccount is not None:
            values["eaccount"] = self.eaccount
        if self.starting_after is not None:
            values["starting_after"] = self.starting_after
        return values


class InstantlyEmailBody(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    text: str | None = Field(default=None, max_length=65_536, repr=False)
    html: str | None = Field(default=None, max_length=65_536, repr=False)


class InstantlyEmail(BaseModel):
    """Allowlisted Email fields; provider enrichment and attachment metadata are discarded."""

    model_config = ConfigDict(extra="ignore", frozen=True, str_strip_whitespace=True)

    id: str
    timestamp_created: dt.datetime
    timestamp_email: dt.datetime
    message_id: str = Field(min_length=1, max_length=998, repr=False)
    subject: str = Field(max_length=998, repr=False)
    body: InstantlyEmailBody = Field(repr=False)
    organization_id: str
    eaccount: str = Field(min_length=1, max_length=320, repr=False)
    from_address_email: str | None = Field(default=None, max_length=320, repr=False)
    campaign_id: str | None = None
    lead: str | None = Field(default=None, max_length=320, repr=False)
    lead_id: str | None = None
    ue_type: Literal[1, 2, 3, 4] | None = None
    step: str | None = Field(default=None, max_length=128)
    is_auto_reply: bool | None = None
    thread_id: str | None = None

    _id = field_validator("id")(_uuid)
    _organization = field_validator("organization_id")(_uuid)
    _campaign = field_validator("campaign_id")(_uuid)
    _lead_id = field_validator("lead_id")(_uuid)
    _thread = field_validator("thread_id")(_uuid)
    _times = field_validator("timestamp_created", "timestamp_email")(_aware)

    @field_validator("is_auto_reply", mode="before")
    @classmethod
    def provider_boolean(cls, value: object) -> bool | None:
        if value is None:
            return None
        if value in (0, False):
            return False
        if value in (1, True):
            return True
        raise ValueError("provider auto-reply value is malformed")


class InstantlyEmailPage(_StrictModel):
    items: tuple[InstantlyEmail, ...] = Field(max_length=100)
    next_starting_after: str | None = Field(default=None, max_length=128)


class InstantlyEmailReader(Protocol):
    def list_emails(self, query: ListEmailsQuery) -> InstantlyEmailPage: ...
    def get_email(self, provider_email_id: str) -> InstantlyEmail: ...


class UnconfiguredInstantlyEmailReader:
    """Fail-closed repository default. It never constructs an HTTP client."""

    @staticmethod
    def _error() -> InstantlyProviderError:
        return InstantlyProviderError(InstantlyErrorCode.AUTH)

    def list_emails(self, query: ListEmailsQuery) -> InstantlyEmailPage:
        del query
        raise self._error()

    def get_email(self, provider_email_id: str) -> InstantlyEmail:
        del provider_email_id
        raise self._error()


class HttpInstantlyEmailReader:
    """Only list/get Email reads; no arbitrary method/path or mutation surface."""

    def __init__(
        self,
        *,
        api_key: str,
        workspace_ref: str,
        client: httpx.Client,
        clock: Callable[[], dt.datetime],
        base_url: str = INSTANTLY_V2_BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError("Instantly Email API key is required")
        if not workspace_ref or len(workspace_ref) > 128:
            raise ValueError("bounded Instantly workspace reference is required")
        if base_url.rstrip("/") != INSTANTLY_V2_BASE_URL:
            raise ValueError("only the official Instantly API V2 base URL is supported")
        self._api_key = api_key
        self._workspace_ref = workspace_ref
        self._client = client
        self._clock = clock
        self._base_url = base_url.rstrip("/")
        self._requests: deque[dt.datetime] = deque()

    def _acquire_rate_budget(self) -> None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Email reader clock must be timezone-aware")
        boundary = now - dt.timedelta(minutes=1)
        while self._requests and self._requests[0] <= boundary:
            self._requests.popleft()
        if len(self._requests) >= KIVOU_EMAIL_REQUESTS_PER_WORKSPACE_MINUTE:
            raise InstantlyProviderError(
                InstantlyErrorCode.RATE_LIMITED,
                retry_after_seconds=1,
            )
        self._requests.append(now)

    def _get(self, path: str, *, params: dict[str, object] | None = None) -> object:
        self._acquire_rate_budget()
        try:
            response = self._client.request(
                "GET",
                f"{self._base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise InstantlyProviderError(InstantlyErrorCode.TIMEOUT) from exc
        except httpx.NetworkError as exc:
            raise InstantlyProviderError(InstantlyErrorCode.NETWORK) from exc
        status_map = {
            401: InstantlyErrorCode.AUTH,
            402: InstantlyErrorCode.PLAN_REQUIRED,
            403: InstantlyErrorCode.PERMISSION,
            404: InstantlyErrorCode.CLIENT_CONTRACT_ERROR,
            429: InstantlyErrorCode.RATE_LIMITED,
        }
        code = status_map.get(response.status_code)
        if code is None and response.status_code >= 500:
            code = InstantlyErrorCode.SERVER_ERROR
        if code is None and response.status_code >= 400:
            code = InstantlyErrorCode.CLIENT_CONTRACT_ERROR
        if code is not None:
            retry_after: int | None = None
            raw_retry = response.headers.get("Retry-After")
            if raw_retry and raw_retry.isdigit():
                retry_after = min(int(raw_retry), 3600)
            raise InstantlyProviderError(code, retry_after_seconds=retry_after)
        if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE)
        try:
            return response.json()
        except ValueError as exc:
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE) from exc

    def list_emails(self, query: ListEmailsQuery) -> InstantlyEmailPage:
        try:
            return InstantlyEmailPage.model_validate(
                self._get("/emails", params=query.query_params())
            )
        except ValidationError as exc:
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE) from exc

    def get_email(self, provider_email_id: str) -> InstantlyEmail:
        provider_email_id = _uuid(provider_email_id) or ""
        try:
            return InstantlyEmail.model_validate(
                self._get(f"/emails/{provider_email_id}")
            )
        except ValidationError as exc:
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE) from exc


__all__ = [
    "INSTANTLY_EMAIL_SCOPE",
    "KIVOU_EMAIL_REQUESTS_PER_WORKSPACE_MINUTE",
    "HttpInstantlyEmailReader",
    "InstantlyEmail",
    "InstantlyEmailBody",
    "InstantlyEmailPage",
    "InstantlyEmailReader",
    "ListEmailsQuery",
    "UnconfiguredInstantlyEmailReader",
]
