"""Provider-specific display names at the Founder adapter boundary."""

from __future__ import annotations

from enum import StrEnum


class FounderProviderName(StrEnum):
    LLM = "OpenRouter"
    WEB_SEARCH = "Serper"
    CONTACT_DATA = "Apollo"
    DELIVERY = "Instantly"


__all__ = ["FounderProviderName"]
