"""Contrats minimaux communs aux adaptateurs de portails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from signals.documents.model import DocumentAccessStatus


@dataclass(frozen=True)
class PortalIdentity:
    company_name: str
    contact_email: str


@dataclass(frozen=True)
class PortalDownloadResult:
    access_status: DocumentAccessStatus
    content: bytes | None = None
    media_type: str | None = None
    detail: str | None = None
    final_url: str | None = None
    byte_size: int | None = None


class AtexoBrowser(Protocol):
    def download(
        self, url: str, identity: PortalIdentity
    ) -> PortalDownloadResult: ...

    def close(self) -> None: ...
