"""Retrait anonyme des plateformes ATEXO via leur parcours JavaScript."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from signals.documents.portals.base import AtexoBrowser, PortalDownloadResult, PortalIdentity

_EXECUTABLE_SUFFIXES = {".exe", ".msi", ".dmg", ".app", ".bat", ".cmd", ".ps1"}


class PlaywrightAtexoBrowser:
    """Conserve une session Chromium entre dossiers d'un même run."""

    def __init__(self, *, timeout_ms: int = 60_000) -> None:
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None

    def _session(self):
        if self._context is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context(
                accept_downloads=True,
                user_agent="Kivou/0.1 (contact: contact@kivou.eu)",
            )
        return self._context

    @staticmethod
    def _fill_if_present(page, selector: str, value: str) -> None:
        locator = page.locator(selector)
        if locator.count():
            locator.first.fill(value)

    def download(self, url: str, identity: PortalIdentity) -> PortalDownloadResult:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        page = self._session().new_page()
        page.set_default_timeout(self.timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded")
            link = page.locator("#linkDownloadDce")
            if link.count():
                link.first.click()
                page.wait_for_load_state("domcontentloaded")
            if page.get_by_text(re.compile("captcha", re.IGNORECASE)).count():
                return PortalDownloadResult("portal_blocked", detail="captcha")

            self._fill_if_present(page, '[name$="$nom"]', identity.company_name)
            self._fill_if_present(page, '[name$="$prenom"]', "Service DCE")
            self._fill_if_present(page, '[name$="$email"]', identity.contact_email)
            self._fill_if_present(page, '[name$="$raisonSocial"]', identity.company_name)
            conditions = page.locator('[name$="$accepterConditions"]')
            if conditions.count():
                conditions.first.check()
            anonymous = page.locator('[id$="_choixAnonyme"]')
            if not anonymous.count():
                return PortalDownloadResult(
                    "download_failed", detail="anonymous_option_not_found"
                )
            anonymous.first.check()
            page.get_by_role("button", name=re.compile("Valider", re.IGNORECASE)).click()
            page.wait_for_load_state("domcontentloaded")

            complete = page.get_by_role(
                "link", name=re.compile("Télécharger le Dossier de consultation", re.IGNORECASE)
            )
            if not complete.count():
                return PortalDownloadResult(
                    "download_failed", detail="complete_archive_link_not_found"
                )
            with page.expect_download(timeout=self.timeout_ms) as pending:
                complete.first.click()
            download = pending.value
            suffix = PurePosixPath(download.suggested_filename).suffix.casefold()
            if suffix in _EXECUTABLE_SUFFIXES:
                download.cancel()
                return PortalDownloadResult("unsupported", detail="executable_refused")
            path = Path(download.path())
            size = path.stat().st_size
            return PortalDownloadResult(
                "available",
                content=path.read_bytes(),
                media_type="application/zip",
                final_url=download.url,
                byte_size=size,
            )
        except PlaywrightTimeout:
            return PortalDownloadResult("download_failed", detail="browser_timeout")
        except PlaywrightError as error:
            return PortalDownloadResult(
                "download_failed", detail=f"browser_error:{type(error).__name__}"
            )
        finally:
            page.close()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


class AtexoAdapter:
    def __init__(self, *, browser: AtexoBrowser, identity: PortalIdentity) -> None:
        self.browser = browser
        self.identity = identity

    @staticmethod
    def matches(html: str) -> bool:
        folded = html.casefold()
        markers = (
            "atexo.common.js",
            "atexoscript.fr.js",
            "atexo.events.js",
            "entreprise.entreprisedemandetelechargementdce",
        )
        return sum(marker in folded for marker in markers) >= 2

    def download(self, landing_url: str, _landing_html: str) -> PortalDownloadResult:
        if not self.identity.company_name.strip() or not self.identity.contact_email.strip():
            return PortalDownloadResult("portal_blocked", detail="identity_missing")
        return self.browser.download(landing_url, self.identity)

    def close(self) -> None:
        self.browser.close()
