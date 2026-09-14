"""Budgeted OpenRouter transport shared by usage-specific adapters."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from signals.model_runtime.budget import ModelBudgetStore
from signals.model_runtime.config import ModelRoute

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_RESPONSE_BYTES = 262_144
_PER_MILLION = Decimal("1000000")


def _structured_reasoning(model: str) -> dict[str, object] | None:
    if model.startswith("openai/gpt-5"):
        return {"effort": "minimal", "exclude": True}
    if model in {
        "google/gemini-2.5-flash",
        "moonshotai/kimi-k2.6",
        "x-ai/grok-4.3",
    }:
        return {"enabled": False}
    return None


def estimate_reservation(
    route: ModelRoute,
    *,
    messages: Sequence[Mapping[str, object]],
    max_tokens: int,
) -> Decimal:
    input_tokens = estimate_input_tokens(messages)
    return (
        Decimal(input_tokens) * route.reserve_input_usd_per_million
        + Decimal(max_tokens) * route.reserve_output_usd_per_million
    ) / _PER_MILLION


def estimate_input_tokens(messages: Sequence[Mapping[str, object]]) -> int:
    """Conservative preflight estimate used before a budgeted network call."""

    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return max(1, math.ceil(len(serialized.encode("utf-8")) / 3))


@dataclass(frozen=True)
class MeteredModelResponse:
    call_id: str
    content: str
    model: str
    reserved_usd: Decimal
    actual_usd: Decimal
    input_tokens: int
    output_tokens: int


class OpenRouterGateway:
    def __init__(
        self,
        *,
        api_key: str,
        budgets: ModelBudgetStore,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenRouter API key is required")
        self._api_key = api_key
        self._budgets = budgets
        self._client = client or httpx.Client(timeout=60.0)

    @staticmethod
    def _reservation(
        route: ModelRoute,
        *,
        messages: Sequence[Mapping[str, object]],
        max_tokens: int,
    ) -> Decimal:
        return estimate_reservation(route, messages=messages, max_tokens=max_tokens)

    def json_call(
        self,
        *,
        route: ModelRoute,
        messages: Sequence[Mapping[str, object]],
        schema: Mapping[str, object],
        schema_name: str,
        max_tokens: int,
        siren: str | None = None,
        batch_id: str | None = None,
    ) -> MeteredModelResponse:
        if not 1 <= max_tokens <= 16_384:
            raise ValueError("max_tokens must be between 1 and 16384")
        call_id = str(uuid.uuid4())
        reserved = self._reservation(route, messages=messages, max_tokens=max_tokens)
        self._budgets.reserve(
            route=route,
            estimated_usd=reserved,
            call_id=call_id,
            siren=siren,
            batch_id=batch_id,
        )
        try:
            reasoning = _structured_reasoning(route.model)
            request_payload: dict[str, object] = {
                "model": route.model,
                "max_tokens": max_tokens,
                "messages": list(messages),
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": dict(schema),
                    },
                },
                "provider": {"require_parameters": True},
                "usage": {"include": True},
            }
            if route.model.startswith("openai/gpt-5"):
                request_payload["reasoning"] = reasoning
            else:
                request_payload["temperature"] = 0
                if reasoning is not None:
                    request_payload["reasoning"] = reasoning
            response = self._client.post(
                OPENROUTER_URL,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json=request_payload,
            )
            if response.status_code != 200:
                raise _ProviderFailure(f"PROVIDER_HTTP_{response.status_code}")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise _ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            try:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                usage = payload["usage"]
                input_tokens = int(usage["prompt_tokens"])
                output_tokens = int(usage["completion_tokens"])
                actual = Decimal(str(usage["cost"]))
                if content is None:
                    content = ""
                if not isinstance(content, str) or input_tokens < 0 or output_tokens < 0:
                    raise TypeError
                if not actual.is_finite() or actual < 0:
                    raise ValueError
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise _ProviderFailure("PROVIDER_INVALID_RESPONSE") from error
            self._budgets.succeed(
                call_id=call_id,
                actual_usd=actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return MeteredModelResponse(
                call_id=call_id,
                content=content,
                model=route.model,
                reserved_usd=reserved,
                actual_usd=actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except _ProviderFailure as error:
            self._budgets.fail(call_id=call_id, error_code=error.code)
            raise RuntimeError(error.code) from error
        except httpx.HTTPError as error:
            self._budgets.fail(call_id=call_id, error_code="PROVIDER_NETWORK")
            raise RuntimeError("PROVIDER_NETWORK") from error
        except Exception:
            self._budgets.fail(call_id=call_id, error_code="MODEL_CALL_FAILED")
            raise

    def text_call(
        self,
        *,
        route: ModelRoute,
        messages: Sequence[Mapping[str, object]],
        max_tokens: int,
        siren: str | None = None,
        batch_id: str | None = None,
    ) -> MeteredModelResponse:
        if not 1 <= max_tokens <= 16_384:
            raise ValueError("max_tokens must be between 1 and 16384")
        call_id = str(uuid.uuid4())
        reserved = self._reservation(route, messages=messages, max_tokens=max_tokens)
        self._budgets.reserve(
            route=route,
            estimated_usd=reserved,
            call_id=call_id,
            siren=siren,
            batch_id=batch_id,
        )
        try:
            response = self._client.post(
                OPENROUTER_URL,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": route.model,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "messages": list(messages),
                    "provider": {"require_parameters": True},
                    "usage": {"include": True},
                },
            )
            if response.status_code != 200:
                raise _ProviderFailure(f"PROVIDER_HTTP_{response.status_code}")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise _ProviderFailure("PROVIDER_RESPONSE_TOO_LARGE")
            try:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                usage = payload["usage"]
                input_tokens = int(usage["prompt_tokens"])
                output_tokens = int(usage["completion_tokens"])
                actual = Decimal(str(usage["cost"]))
                if not isinstance(content, str) or input_tokens < 0 or output_tokens < 0:
                    raise TypeError
                if not actual.is_finite() or actual < 0:
                    raise ValueError
            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise _ProviderFailure("PROVIDER_INVALID_RESPONSE") from error
            self._budgets.succeed(
                call_id=call_id,
                actual_usd=actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return MeteredModelResponse(
                call_id=call_id,
                content=content,
                model=route.model,
                reserved_usd=reserved,
                actual_usd=actual,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        except _ProviderFailure as error:
            self._budgets.fail(call_id=call_id, error_code=error.code)
            raise RuntimeError(error.code) from error
        except httpx.HTTPError as error:
            self._budgets.fail(call_id=call_id, error_code="PROVIDER_NETWORK")
            raise RuntimeError("PROVIDER_NETWORK") from error
        except Exception:
            self._budgets.fail(call_id=call_id, error_code="MODEL_CALL_FAILED")
            raise


class _ProviderFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


__all__ = [
    "MAX_RESPONSE_BYTES",
    "OPENROUTER_URL",
    "MeteredModelResponse",
    "OpenRouterGateway",
    "estimate_input_tokens",
    "estimate_reservation",
]
