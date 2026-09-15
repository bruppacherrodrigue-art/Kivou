"""Reject obvious demonstration addresses before prospecting."""

from __future__ import annotations

import re

_EXACT_MARKERS = ("jean.dupont", "john.doe", "prenom.nom", "domain.com", "email.com")
_PLACEHOLDER_WORDS = frozenset(
    {"exemple", "example", "test", "demo", "yourdomain", "monsite"}
)
_CONSUMER_MAILBOX_DOMAINS = frozenset(
    {
        "free.fr",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hotmail.fr",
        "icloud.com",
        "laposte.net",
        "live.com",
        "live.fr",
        "mac.com",
        "me.com",
        "msn.com",
        "orange.fr",
        "outlook.com",
        "outlook.fr",
        "proton.me",
        "protonmail.com",
        "wanadoo.fr",
        "yahoo.com",
        "yahoo.fr",
    }
)


def is_placeholder_email(value: object) -> bool:
    email = str(value or "").strip().casefold()
    if any(marker in email for marker in _EXACT_MARKERS):
        return True
    return bool(_PLACEHOLDER_WORDS.intersection(re.findall(r"[a-z0-9]+", email)))


def is_consumer_mailbox(value: object) -> bool:
    """Return whether an address belongs to a held consumer mailbox provider."""

    email = str(value or "").strip().casefold()
    _local, separator, domain = email.rpartition("@")
    return bool(separator and domain in _CONSUMER_MAILBOX_DOMAINS)


__all__ = ["is_consumer_mailbox", "is_placeholder_email"]
