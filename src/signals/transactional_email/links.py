"""Build transactional links exclusively from the configured public origin."""

from __future__ import annotations

from urllib.parse import quote


def reset_url(origin: str, token: str) -> str:
    return f"{origin}/reset-password?token={quote(token, safe='')}"


def signal_url(origin: str, signal_key: str) -> str:
    return f"{origin}/app/signals/{quote(signal_key, safe='')}"


def preferences_url(origin: str) -> str:
    return f"{origin}/app/notifications"
