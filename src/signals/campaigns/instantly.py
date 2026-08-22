"""Narrow Instantly API V2 adapter with typed, reconciliation-safe failures."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from signals.campaigns.contracts import MailboxReadiness, MailboxReadinessState
from signals.decision_engine.policy import semantic_fingerprint

INSTANTLY_V2_BASE_URL = "https://api.instantly.ai/api/v2"
MAX_PROVIDER_RESPONSE_BYTES = 1_048_576


class InstantlyErrorCode(StrEnum):
    AUTH = "AUTH"
    PERMISSION = "PERMISSION"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    SERVER_ERROR = "SERVER_ERROR"
    CLIENT_CONTRACT_ERROR = "CLIENT_CONTRACT_ERROR"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    REMOTE_STATE_CONFLICT = "REMOTE_STATE_CONFLICT"


class InstantlyProviderError(RuntimeError):
    def __init__(
        self,
        code: InstantlyErrorCode,
        *,
        reconciliation_required: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(f"Instantly provider failure: {code.value}")
        self.code = code
        self.reconciliation_required = reconciliation_required
        self.retry_after_seconds = retry_after_seconds


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderCampaign(_ProviderModel):
    provider_campaign_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    status: str | int
    not_sending_status: int | None = None
    normalized_config: dict[str, object] | None = Field(default=None, exclude=True)


class ProviderLead(_ProviderModel):
    provider_lead_id: str = Field(min_length=1, max_length=128)
    status: str | int | None = None


class ProviderMutationResult(_ProviderModel):
    provider_identity: str | None = None
    status: str | int | None = None


class InstantlyProvider(Protocol):
    def list_campaigns(self, *, search: str) -> tuple[ProviderCampaign, ...]: ...
    def get_campaign(self, provider_campaign_id: str) -> ProviderCampaign: ...
    def create_campaign(
        self, *, name: str, provider_config: dict[str, object]
    ) -> ProviderCampaign: ...
    def configure_campaign(
        self, provider_campaign_id: str, *, provider_config: dict[str, object]
    ) -> ProviderCampaign: ...
    def activate_campaign(self, provider_campaign_id: str) -> ProviderMutationResult: ...
    def pause_campaign(self, provider_campaign_id: str) -> ProviderMutationResult: ...
    def get_mailbox_readiness(self, provider_account_email: str) -> dict[str, object]: ...
    def create_lead_or_batch(
        self,
        *,
        provider_campaign_id: str,
        leads: tuple[dict[str, object], ...],
    ) -> object: ...
    def list_leads(self, *, provider_campaign_id: str) -> object: ...
    def get_lead(self, provider_lead_id: str) -> object: ...
    def pause_lead(self, provider_lead_id: str) -> object: ...
    def list_webhooks(self) -> object: ...
    def get_webhook_events(self) -> object: ...


_CAMPAIGN_CONFIG_KEYS = frozenset(
    {
        "campaign_schedule",
        "sequences",
        "daily_limit",
        "email_list",
        "stop_on_reply",
        "stop_on_auto_reply",
        "stop_for_company",
        "open_tracking",
        "link_tracking",
        "text_only",
        "first_email_text_only",
        "insert_unsubscribe_header",
        "allow_risky_contacts",
        "disable_bounce_protect",
        "auto_variant_select",
    }
)

_CAMPAIGN_RESPONSE_KEYS = _CAMPAIGN_CONFIG_KEYS | frozenset(
    {
        "id",
        "name",
        "status",
        "not_sending_status",
        "timestamp_created",
        "timestamp_updated",
        "created_at",
        "updated_at",
        "workspace_id",
        "organization",
        "owned_by",
        "pl_value",
        "is_evergreen",
        "email_gap",
        "random_wait_max",
        "email_tag_list",
        "daily_max_leads",
        "prioritize_new_leads",
        "match_lead_esp",
        "core_variables",
        "custom_variables",
        "limit_emails_per_company_override",
        "cc_list",
        "bcc_list",
        "ai_sdr_id",
        "provider_routing_rules",
        "analytics",
    }
)


def _expected_weekdays(start_date: dt.date, end_date: dt.date) -> dict[str, bool]:
    """Map Python's Monday=0 weekday convention to Instantly's 0..6 keys."""
    active = {start_date.weekday(), end_date.weekday()}
    return {str(index): index in active for index in range(7)}


def _normalize_variants(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("each email step must contain exactly one variant")
    variant = value[0]
    unknown = set(variant) - {"subject", "body", "v_disabled"}
    if unknown or not isinstance(variant.get("subject"), str) or not isinstance(
        variant.get("body"), str
    ):
        raise ValueError("provider email variant shape is unsupported")
    disabled = variant.get("v_disabled", False)
    if disabled is not False:
        raise ValueError("the single deterministic email variant must be active")
    return [
        {
            "subject": variant["subject"],
            "body": variant["body"],
            "v_disabled": False,
        }
    ]


def _normalize_sequences(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("campaign must contain exactly one Instantly sequence")
    sequence = value[0]
    if set(sequence) != {"steps"}:
        raise ValueError("provider sequence shape is unsupported")
    steps = sequence["steps"]
    if not isinstance(steps, list) or len(steps) != 2:
        raise ValueError("campaign must contain exactly two email steps")
    normalized_steps: list[dict[str, object]] = []
    allowed_step_keys = {
        "type",
        "delay",
        "delay_unit",
        "pre_delay",
        "pre_delay_unit",
        "variants",
    }
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) - allowed_step_keys:
            raise ValueError("provider email step shape is unsupported")
        if step.get("type") != "email":
            raise ValueError("Instantly campaign steps must be email steps")
        normalized_step: dict[str, object] = {
            "type": "email",
            "variants": _normalize_variants(step.get("variants")),
        }
        if index == 0:
            # Official V2 defines delay on a step as the wait before the NEXT email.
            normalized_step["delay"] = step.get("delay")
            normalized_step["delay_unit"] = step.get("delay_unit", "days")
        normalized_steps.append(normalized_step)
    return [{"steps": normalized_steps}]


def _normalize_campaign_schedule(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "start_date",
        "end_date",
        "schedules",
    }:
        raise ValueError("campaign_schedule shape violates Instantly V2")
    try:
        start_date = dt.date.fromisoformat(str(value["start_date"]))
        end_date = dt.date.fromisoformat(str(value["end_date"]))
    except ValueError as exc:
        raise ValueError("campaign schedule dates are invalid") from exc
    schedules = value["schedules"]
    if not isinstance(schedules, list) or len(schedules) != 1 or not isinstance(
        schedules[0], dict
    ):
        raise ValueError("campaign must contain exactly one provider schedule")
    schedule = schedules[0]
    if set(schedule) != {"name", "timing", "days", "timezone"}:
        raise ValueError("provider schedule item shape violates Instantly V2")
    normalized = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "schedules": [
            {
                "name": schedule["name"],
                "timing": schedule["timing"],
                "days": schedule["days"],
                "timezone": schedule["timezone"],
            }
        ],
    }
    return normalized


def _guard_provider_execution_fields(value: dict[str, object]) -> None:
    """Fail closed on known response-only fields that can expand execution."""
    if value.get("is_evergreen") not in (None, False):
        raise ValueError("evergreen provider execution is forbidden")
    for key in ("cc_list", "bcc_list"):
        if value.get(key) not in (None, []):
            raise ValueError(f"provider {key} must remain empty")
    if value.get("ai_sdr_id") is not None:
        raise ValueError("provider AI SDR attachment is forbidden")
    if value.get("core_variables") not in (None, {}) or value.get(
        "custom_variables"
    ) not in (None, {}):
        raise ValueError("campaign-level provider variables are forbidden")
    if value.get("prioritize_new_leads") not in (None, False):
        raise ValueError("provider lead-priority execution is forbidden")
    if value.get("match_lead_esp") not in (None, False):
        raise ValueError("provider ESP routing is forbidden")
    routing = value.get("provider_routing_rules")
    safe_default_routing = [
        {
            "action": "send",
            "recipient_esp": ["all"],
            "sender_esp": ["all"],
        }
    ]
    if routing not in (None, [], safe_default_routing):
        raise ValueError("provider routing rules exceed the bounded one-account route")


def normalize_provider_campaign_config(response: object) -> dict[str, object]:
    """Extract the exact comparable V2 subset and validate material read-only guards."""
    if not isinstance(response, dict):
        raise TypeError("provider campaign response must be an object")
    unknown = set(response) - _CAMPAIGN_RESPONSE_KEYS
    if unknown:
        raise ValueError(f"unknown provider campaign response fields: {sorted(unknown)}")
    _guard_provider_execution_fields(response)
    missing = (_CAMPAIGN_CONFIG_KEYS - {"auto_variant_select"}) - set(response)
    if missing:
        raise ValueError(f"provider campaign readback is incomplete: {sorted(missing)}")
    normalized = {
        key: response[key]
        for key in _CAMPAIGN_CONFIG_KEYS
        if key not in {"campaign_schedule", "sequences", "auto_variant_select"}
    }
    normalized["campaign_schedule"] = _normalize_campaign_schedule(
        response["campaign_schedule"]
    )
    normalized["sequences"] = _normalize_sequences(response["sequences"])
    normalized["auto_variant_select"] = response.get("auto_variant_select")
    return normalized


def _validate_campaign_config(value: dict[str, object]) -> dict[str, object]:
    unknown = set(value) - _CAMPAIGN_CONFIG_KEYS
    if unknown:
        raise ValueError(f"unsupported Instantly campaign config keys: {sorted(unknown)}")
    if set(value) != _CAMPAIGN_CONFIG_KEYS:
        raise ValueError("campaign config is incomplete")
    if value["stop_on_reply"] is not True or value["stop_on_auto_reply"] is not True:
        raise ValueError("reply and auto-reply stops are mandatory")
    if value["stop_for_company"] is not False:
        raise ValueError("provider company-wide stop is forbidden in v1")
    if value.get("auto_variant_select") is not None:
        raise ValueError("provider automatic variant selection is forbidden in v1")
    frozen_flags = {
        "open_tracking": False,
        "link_tracking": False,
        "text_only": True,
        "first_email_text_only": True,
        "insert_unsubscribe_header": True,
        "allow_risky_contacts": False,
        "disable_bounce_protect": False,
    }
    if any(value.get(key) is not expected for key, expected in frozen_flags.items()):
        raise ValueError("campaign tracking or transport flags violate frozen v1")
    email_list = value.get("email_list")
    if (
        not isinstance(email_list, list)
        or len(email_list) != 1
        or not isinstance(email_list[0], str)
        or not email_list[0]
    ):
        raise ValueError("campaign must bind exactly one provider account")
    daily_limit = value.get("daily_limit")
    if not isinstance(daily_limit, int) or isinstance(daily_limit, bool):
        raise TypeError("campaign daily limit must be an integer")
    if daily_limit < 1 or daily_limit > 3:
        raise ValueError("campaign daily limit exceeds the frozen mailbox cap")
    schedule = _normalize_campaign_schedule(value.get("campaign_schedule"))
    try:
        start_date = dt.date.fromisoformat(str(schedule["start_date"]))
        end_date = dt.date.fromisoformat(str(schedule["end_date"]))
    except ValueError as exc:
        raise ValueError("campaign schedule dates are invalid") from exc
    schedule_item = schedule["schedules"][0]
    if start_date > end_date or schedule_item["timezone"] not in {
        "Europe/Zurich",
        "Europe/Paris",
    }:
        raise ValueError("campaign schedule jurisdiction is invalid")
    if schedule_item["name"] != "Kivou two-window schedule":
        raise ValueError("campaign schedule name violates frozen v1")
    if schedule_item["timing"] != {"from": "09:00", "to": "17:00"}:
        raise ValueError("campaign schedule hours violate frozen v1")
    if schedule_item["days"] != _expected_weekdays(start_date, end_date):
        raise ValueError("campaign active weekdays violate two-window containment")
    sequences = _normalize_sequences(value.get("sequences"))
    expected_sequences = [
        {
            "steps": [
                {
                    "type": "email",
                    "delay": 4,
                    "delay_unit": "days",
                    "variants": [
                        {
                            "subject": "{{kivou_subject}}",
                            "body": "{{kivou_envelope}}",
                            "v_disabled": False,
                        }
                    ],
                },
                {
                    "type": "email",
                    "variants": [
                        {
                            "subject": "",
                            "body": "{{kivou_follow_up}}",
                            "v_disabled": False,
                        }
                    ],
                },
            ]
        }
    ]
    if sequences != expected_sequences:
        raise ValueError("campaign sequence must be the exact frozen two-step contract")
    return value


def normalized_provider_campaign_config_fingerprint(
    provider_config: dict[str, object],
) -> str:
    """Fingerprint only the canonical, Kivou-authorized comparable subset."""
    return semantic_fingerprint(
        {
            "kind": "instantly-provider-config-semantic-v1",
            "provider_config": _validate_campaign_config(provider_config),
        }
    )


def provider_campaign_configs_match(
    normalized_provider_config: dict[str, object] | None,
    desired_provider_config: dict[str, object],
) -> bool:
    """Compare one canonical semantic representation, never raw GET JSON."""
    if normalized_provider_config is None:
        return False
    try:
        return normalized_provider_campaign_config_fingerprint(
            normalized_provider_config
        ) == normalized_provider_campaign_config_fingerprint(desired_provider_config)
    except (TypeError, ValueError):
        return False


def provider_campaign_config_fingerprint(
    campaign_ref: str, provider_config: dict[str, object]
) -> str:
    """Bind the exact allowlisted provider configuration without raw PII."""
    validated = _validate_campaign_config(provider_config)
    return semantic_fingerprint(
        {
            "kind": "instantly-provider-config-v1",
            "campaign_ref": campaign_ref,
            "normalized_provider_config_fingerprint": (
                normalized_provider_campaign_config_fingerprint(validated)
            ),
        }
    )


def build_provider_campaign_config(
    *,
    step_1_execution_date: dt.date,
    step_2_execution_date: dt.date,
    timezone: str,
    provider_account_id: str,
    daily_limit: int,
) -> dict[str, object]:
    """Return the single frozen V2 campaign subset Kivou can authorize."""
    weekdays = _expected_weekdays(step_1_execution_date, step_2_execution_date)
    return _validate_campaign_config(
        {
            "campaign_schedule": {
                "start_date": step_1_execution_date.isoformat(),
                "end_date": step_2_execution_date.isoformat(),
                "schedules": [
                    {
                        "name": "Kivou two-window schedule",
                        "timing": {"from": "09:00", "to": "17:00"},
                        "days": weekdays,
                        "timezone": timezone,
                    }
                ],
            },
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 4,
                            "delay_unit": "days",
                            "variants": [
                                {
                                    "subject": "{{kivou_subject}}",
                                    "body": "{{kivou_envelope}}",
                                    "v_disabled": False,
                                }
                            ],
                        },
                        {
                            "type": "email",
                            "variants": [
                                {
                                    "subject": "",
                                    "body": "{{kivou_follow_up}}",
                                    "v_disabled": False,
                                }
                            ],
                        },
                    ]
                }
            ],
            "stop_on_reply": True,
            "stop_on_auto_reply": True,
            "stop_for_company": False,
            "email_list": [provider_account_id],
            "daily_limit": daily_limit,
            "open_tracking": False,
            "link_tracking": False,
            "text_only": True,
            "first_email_text_only": True,
            "insert_unsubscribe_header": True,
            "allow_risky_contacts": False,
            "disable_bounce_protect": False,
            "auto_variant_select": None,
        }
    )


class HttpInstantlyProvider:
    """Explicit V2 operations only; no public arbitrary-request escape hatch."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client,
        base_url: str = INSTANTLY_V2_BASE_URL,
    ) -> None:
        if not api_key:
            raise ValueError("Instantly API key is required")
        if base_url.rstrip("/") != INSTANTLY_V2_BASE_URL:
            raise ValueError("only the official Instantly API V2 base URL is supported")
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
        mutation: bool = False,
    ) -> object:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT,
                reconciliation_required=mutation,
            ) from exc
        except httpx.NetworkError as exc:
            raise InstantlyProviderError(
                InstantlyErrorCode.NETWORK,
                reconciliation_required=mutation,
            ) from exc
        retry_after: int | None = None
        if response.status_code == 429:
            raw_retry = response.headers.get("Retry-After")
            retry_after = int(raw_retry) if raw_retry and raw_retry.isdigit() else None
        status_map = {
            401: InstantlyErrorCode.AUTH,
            402: InstantlyErrorCode.PLAN_REQUIRED,
            403: InstantlyErrorCode.PERMISSION,
            429: InstantlyErrorCode.RATE_LIMITED,
        }
        code = status_map.get(response.status_code)
        if code is None and response.status_code >= 500:
            code = InstantlyErrorCode.SERVER_ERROR
        if code is None and response.status_code >= 400:
            code = InstantlyErrorCode.CLIENT_CONTRACT_ERROR
        if code is not None:
            raise InstantlyProviderError(
                code,
                reconciliation_required=mutation and (
                    code in {InstantlyErrorCode.SERVER_ERROR}
                ),
                retry_after_seconds=retry_after,
            )
        if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
            raise InstantlyProviderError(
                InstantlyErrorCode.MALFORMED_RESPONSE,
                reconciliation_required=mutation,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise InstantlyProviderError(
                InstantlyErrorCode.MALFORMED_RESPONSE,
                reconciliation_required=mutation,
            ) from exc

    @staticmethod
    def _campaign(
        value: object,
        *,
        mutation: bool = False,
        require_config: bool = False,
    ) -> ProviderCampaign:
        if not isinstance(value, dict):
            raise InstantlyProviderError(
                InstantlyErrorCode.MALFORMED_RESPONSE,
                reconciliation_required=mutation,
            )
        try:
            normalized_config = (
                normalize_provider_campaign_config(value) if require_config else None
            )
            return ProviderCampaign(
                provider_campaign_id=str(value["id"]),
                name=value["name"],
                status=value["status"],
                not_sending_status=value.get("not_sending_status"),
                normalized_config=normalized_config,
            )
        except (KeyError, ValidationError, TypeError, ValueError) as exc:
            raise InstantlyProviderError(
                InstantlyErrorCode.MALFORMED_RESPONSE,
                reconciliation_required=mutation,
            ) from exc

    def list_campaigns(self, *, search: str) -> tuple[ProviderCampaign, ...]:
        value = self._call("GET", "/campaigns", params={"search": search})
        items = value.get("items", value.get("data", [])) if isinstance(value, dict) else value
        if not isinstance(items, list):
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE)
        return tuple(self._campaign(item) for item in items)

    def get_campaign(self, provider_campaign_id: str) -> ProviderCampaign:
        return self._campaign(
            self._call("GET", f"/campaigns/{provider_campaign_id}"),
            require_config=True,
        )

    def create_campaign(
        self, *, name: str, provider_config: dict[str, object]
    ) -> ProviderCampaign:
        body = {"name": name, **_validate_campaign_config(provider_config)}
        return self._campaign(
            self._call("POST", "/campaigns", json_body=body, mutation=True),
            mutation=True,
        )

    def configure_campaign(
        self, provider_campaign_id: str, *, provider_config: dict[str, object]
    ) -> ProviderCampaign:
        body = _validate_campaign_config(provider_config)
        return self._campaign(
            self._call(
                "PATCH",
                f"/campaigns/{provider_campaign_id}",
                json_body=body,
                mutation=True,
            ),
            mutation=True,
        )

    def activate_campaign(self, provider_campaign_id: str) -> ProviderMutationResult:
        value = self._call(
            "POST", f"/campaigns/{provider_campaign_id}/activate", mutation=True
        )
        return self._mutation(value, fallback_identity=provider_campaign_id)

    def pause_campaign(self, provider_campaign_id: str) -> ProviderMutationResult:
        value = self._call("POST", f"/campaigns/{provider_campaign_id}/pause", mutation=True)
        return self._mutation(value, fallback_identity=provider_campaign_id)

    def get_mailbox_readiness(self, provider_account_email: str) -> dict[str, object]:
        value = self._call("GET", f"/accounts/{provider_account_email}")
        if not isinstance(value, dict):
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE)
        allowed = {
            "status",
            "warmup_status",
            "setup_pending",
            "daily_limit",
            "sending_gap",
            "tracking_domain_status",
        }
        return {key: value.get(key) for key in allowed}

    def create_lead_or_batch(
        self,
        *,
        provider_campaign_id: str,
        leads: tuple[dict[str, object], ...],
    ) -> object:
        if not 1 <= len(leads) <= 10:
            raise ValueError("Kivou micro-campaign lead batch must contain 1 to 10 leads")
        allowed_lead_keys = {"email", "custom_variables", "skip_if_in_workspace"}
        for lead in leads:
            if set(lead) - allowed_lead_keys or not lead.get("email"):
                raise ValueError("lead payload contains unsupported or missing fields")
        if len(leads) == 1:
            body = {**leads[0], "campaign": provider_campaign_id}
            path = "/leads"
        else:
            body = {"campaign_id": provider_campaign_id, "leads": list(leads)}
            path = "/leads/add"
        return self._call(
            "POST",
            path,
            json_body=body,
            mutation=True,
        )

    def list_leads(self, *, provider_campaign_id: str) -> object:
        value = self._call(
            "POST", "/leads/list", json_body={"campaign_id": provider_campaign_id}
        )
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE)
        return {
            **value,
            "items": [self._normalize_lead(item) for item in value["items"]],
        }

    def get_lead(self, provider_lead_id: str) -> object:
        return self._normalize_lead(self._call("GET", f"/leads/{provider_lead_id}"))

    def pause_lead(self, provider_lead_id: str) -> object:
        del provider_lead_id
        # As verified on 2026-08-22, PATCH /leads/{id} exposes lead status only
        # as a read-only numeric response field.  Never fabricate a writable
        # "paused" status. Campaign-wide pause remains the fail-closed fallback.
        raise InstantlyProviderError(
            InstantlyErrorCode.CLIENT_CONTRACT_ERROR,
            reconciliation_required=False,
        )

    def list_webhooks(self) -> object:
        return self._call("GET", "/webhooks")

    def get_webhook_events(self) -> object:
        return self._call("GET", "/webhook-events")

    @staticmethod
    def _normalize_lead(value: object) -> dict[str, object]:
        if not isinstance(value, dict) or not value.get("id"):
            raise InstantlyProviderError(InstantlyErrorCode.MALFORMED_RESPONSE)
        normalized = dict(value)
        if "campaign_id" not in normalized and "campaign" in normalized:
            normalized["campaign_id"] = normalized["campaign"]
        if "custom_variables" not in normalized and "payload" in normalized:
            normalized["custom_variables"] = normalized["payload"]
        return normalized

    @staticmethod
    def _mutation(value: object, *, fallback_identity: str) -> ProviderMutationResult:
        if not isinstance(value, dict):
            raise InstantlyProviderError(
                InstantlyErrorCode.MALFORMED_RESPONSE,
                reconciliation_required=True,
            )
        return ProviderMutationResult(
            provider_identity=str(value.get("id", fallback_identity)),
            status=value.get("status"),
        )


def normalize_mailbox_readiness(
    raw: object, *, observed_at: dt.datetime
) -> MailboxReadiness:
    """Map only bounded V2 account facts and fail closed on incomplete state."""
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("mailbox readiness observation must be timezone-aware")
    if not isinstance(raw, dict):
        return MailboxReadiness(
            state=MailboxReadinessState.UNKNOWN,
            provider_daily_limit=0,
            sending_gap_seconds=0,
            observed_at=observed_at,
        )
    status = str(raw.get("status", "")).strip().casefold().replace(" ", "_")
    warmup = str(raw.get("warmup_status", "")).strip().casefold().replace(" ", "_")
    tracking = (
        str(raw.get("tracking_domain_status", "")).strip().casefold().replace(" ", "_")
    )
    setup_pending = raw.get("setup_pending")
    daily_limit = raw.get("daily_limit")
    sending_gap = raw.get("sending_gap")
    if (
        not isinstance(setup_pending, bool)
        or not isinstance(daily_limit, int)
        or isinstance(daily_limit, bool)
        or not isinstance(sending_gap, int)
        or isinstance(sending_gap, bool)
        or daily_limit < 0
        or sending_gap < 0
    ):
        state = MailboxReadinessState.UNKNOWN
        daily_limit = 0
        sending_gap = 0
    elif status in {"connection_error", "soft_bounce_error", "sending_error", "banned"} or warmup in {"banned", "suspended", "error"} or tracking in {
        "invalid",
        "error",
        "failed",
    }:
        state = MailboxReadinessState.UNHEALTHY
    elif status in {"paused", "maintenance"} or warmup in {"paused", "maintenance"} or daily_limit == 0:
        state = MailboxReadinessState.TEMPORARILY_UNAVAILABLE
    elif (
        status == "active"
        and setup_pending is False
        and warmup in {"active", "completed", "enabled"}
        and tracking in {"active", "verified", "connected", "not_required"}
    ):
        state = MailboxReadinessState.READY
    else:
        state = MailboxReadinessState.UNKNOWN
    return MailboxReadiness(
        state=state,
        provider_daily_limit=daily_limit,
        sending_gap_seconds=sending_gap,
        observed_at=observed_at,
        valid_until=(
            observed_at + dt.timedelta(minutes=5)
            if state is MailboxReadinessState.READY
            else None
        ),
    )


class InstantlyMailboxReadinessSource:
    """Explicit network-backed source; construction and imports perform no I/O."""

    def __init__(self, provider: InstantlyProvider) -> None:
        self._provider = provider

    def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness:
        return normalize_mailbox_readiness(
            self._provider.get_mailbox_readiness(provider_account_id),
            observed_at=observed_at,
        )
