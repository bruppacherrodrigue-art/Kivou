"""Rendered-page reduction for untrusted company research evidence."""

from __future__ import annotations

import re
import threading
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

PAGE_TEXT_LIMIT = 800

_EMAIL = re.compile(
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE
)
_PHONE = re.compile(
    r"(?<!\d)(?:(?:\+|00)33[\s.()-]*[1-9]|0[1-9])"
    r"(?:[\s.()-]*\d{2}){4}(?!\d)"
)
_WEBSITE_FIELD = re.compile(
    r"(?:site(?:\s+(?:internet|web))?|website)\s*[:\-]?\s*"
    r"((?:https?://)?(?:www\.)?[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/[^\s,;]*)?)",
    re.IGNORECASE,
)
_DIRECTOR_FIELD = re.compile(
    r"(?:dirigeant|g[ée]rant|pr[ée]sident)\s*[:\-]?\s*"
    r"([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ'’-]+){1,5})",
    re.IGNORECASE,
)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RawRenderedPage(_Contract):
    url: str = Field(min_length=8, max_length=2048)
    status_code: int = Field(ge=100, le=599)
    title: str = Field(default="", max_length=1024)
    main_text: str = Field(default="", max_length=2_000_000)
    body_text: str = Field(default="", max_length=2_000_000)


class DirectoryClues(_Contract):
    website: str | None = Field(default=None, max_length=2048)
    phone: str | None = Field(default=None, max_length=32)
    director: str | None = Field(default=None, max_length=256)


class ReducedRenderedPage(_Contract):
    url: str = Field(min_length=8, max_length=2048)
    status_code: int = Field(ge=100, le=599)
    title: str = Field(default="", max_length=1024)
    text: str = Field(default="", max_length=PAGE_TEXT_LIMIT)
    published_emails: tuple[str, ...] = Field(default=(), max_length=50)
    published_phones: tuple[str, ...] = Field(default=(), max_length=50)


def _compact(value: str) -> str:
    return " ".join(value.split())


def directory_clues_from_text(value: str) -> DirectoryClues:
    website = _WEBSITE_FIELD.search(value)
    phone = _PHONE.search(value)
    director = _DIRECTOR_FIELD.search(value)
    return DirectoryClues(
        website=website.group(1).rstrip(".") if website else None,
        phone=_compact(phone.group(0)) if phone else None,
        director=_compact(director.group(1)).rstrip(".") if director else None,
    )


def reduce_rendered_page(value: RawRenderedPage) -> ReducedRenderedPage:
    compact_main = _compact(value.main_text or value.body_text)[:PAGE_TEXT_LIMIT]
    contacts = _compact(value.body_text or value.main_text)
    return ReducedRenderedPage(
        url=value.url,
        status_code=value.status_code,
        title=_compact(value.title)[:1024],
        text=compact_main,
        published_emails=tuple(
            dict.fromkeys(match.casefold() for match in _EMAIL.findall(contacts))
        )[:50],
        published_phones=tuple(
            dict.fromkeys(_compact(match) for match in _PHONE.findall(contacts))
        )[:50],
    )


class PageRenderer(Protocol):
    def render(self, url: str) -> RawRenderedPage | None: ...


class PlaywrightPageRenderer:
    """Render one page at a time; a lock makes the shared batch browser safe."""

    def __init__(self, *, timeout_ms: int = 8_000) -> None:
        self._timeout_ms = timeout_ms
        self._lock = threading.Lock()
        self._playwright = None
        self._browser = None

    def _start(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)

    def render(self, url: str) -> RawRenderedPage | None:
        with self._lock:
            self._start()
            page = self._browser.new_page()  # type: ignore[union-attr]
            try:
                response = page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout_ms
                )
                if response is None:
                    return None
                status = response.status
                if status < 200 or status >= 400:
                    return None
                title = page.title()
                main_text = page.locator("main").first.inner_text(timeout=500) \
                    if page.locator("main").count() else ""
                body_text = page.locator("body").inner_text(timeout=1_000)
                if not main_text:
                    main_text = page.evaluate(
                        """() => {
                          const clone = document.body.cloneNode(true);
                          clone.querySelectorAll('nav,footer,script,style,noscript,svg')
                            .forEach(node => node.remove());
                          return clone.innerText || clone.textContent || '';
                        }"""
                    )
                return RawRenderedPage(
                    url=page.url,
                    status_code=status,
                    title=title,
                    main_text=main_text,
                    body_text=body_text,
                )
            except Exception:  # noqa: BLE001 - an unrenderable public page is no evidence
                return None
            finally:
                page.close()

    def close(self) -> None:
        with self._lock:
            if self._browser is not None:
                self._browser.close()
                self._browser = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None


__all__ = [
    "PAGE_TEXT_LIMIT",
    "DirectoryClues",
    "PageRenderer",
    "PlaywrightPageRenderer",
    "RawRenderedPage",
    "ReducedRenderedPage",
    "directory_clues_from_text",
    "reduce_rendered_page",
]
