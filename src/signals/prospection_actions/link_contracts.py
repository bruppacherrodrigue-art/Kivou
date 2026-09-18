"""Provider-independent contracts for prospect attribution links."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IssuedProspectLink:
    url: str
    member_ref: str
    token_fingerprint: str
    payload: dict[str, object]
    unsubscribe_url: str | None = None


class ProspectLinkIssuer(Protocol):
    def issue(
        self, *, row: dict[str, object], email: str, at: dt.datetime
    ) -> IssuedProspectLink: ...


def history_id(target_id: str, version: int, event_type: str) -> str:
    return hashlib.sha256(
        f"prospect-history\0{target_id}\0{version}\0{event_type}".encode()
    ).hexdigest()


__all__ = ["IssuedProspectLink", "ProspectLinkIssuer", "history_id"]
