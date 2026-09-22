"""Bounded, deterministic identification from a company's public legal notice."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.mail_provider import normalize_domain
from signals.persistence.schema import acquisition_census_legal_page_cache

LEGAL_PAGE_VERSION = "milomail-legal-page-v3"
_IDENTIFIER = re.compile(
    r"(?i)\b(?:siren|siret|tva(?:\s+intracommunautaire)?)\s*[:°nº.]*\s*"
    r"(?P<id>(?:FR\s*[0-9]{2}\s*)?[0-9](?:[ .-]?[0-9]){8,13})\b"
)
_LEGAL_PATH = re.compile(r"(?i)(mentions[-_ ]?legales|legal[-_ ]?notice|/legal/?|imprint)")
_MAX_BYTES = 262_144


def _luhn(value: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(value)):
        digit = int(char)
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def extract_siren(text: str) -> tuple[str, ...]:
    """Accept only valid SIREN, SIRET or numeric-key FR VAT identifiers."""
    found: set[str] = set()
    for match in _IDENTIFIER.finditer(text[:_MAX_BYTES]):
        compact = re.sub(r"[^A-Za-z0-9]", "", match.group("id")).upper()
        if compact.startswith("FR") and len(compact) == 13:
            key, siren = compact[2:4], compact[4:]
            if _luhn(siren) and int(key) == (12 + 3 * (int(siren) % 97)) % 97:
                found.add(siren)
        elif len(compact) == 14 and _luhn(compact) and _luhn(compact[:9]):
            found.add(compact[:9])
        elif len(compact) == 9 and _luhn(compact):
            found.add(compact)
    return tuple(sorted(found))


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self._ignored += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str) and len(href) <= 512:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.text.append(data)


class LegalPageResolver:
    """Fetch robots, home and at most two internal legal pages; cache evidence only."""

    def __init__(self, engine: Engine, *, client: httpx.Client | None = None,
                 timeout: float = 5.0, cache_ttl_days: int = 7) -> None:
        if not 0 < timeout <= 10 or not 1 <= cache_ttl_days <= 30:
            raise ValueError("legal-page bounds are invalid")
        self.engine = engine
        self.client = client or httpx.Client(follow_redirects=False, timeout=timeout)
        self.timeout = timeout
        self.ttl = dt.timedelta(days=cache_ttl_days)
        self.requests_made = 0

    @staticmethod
    def _public(domain: str) -> bool:
        try:
            addresses = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
            return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global
                                           for item in addresses)
        except (OSError, ValueError):
            return False

    def resolve(self, domain: str, *, at: dt.datetime) -> dict:
        name = normalize_domain(domain)
        key = hashlib.sha256(f"{LEGAL_PAGE_VERSION}\0{name}".encode()).hexdigest()
        with self.engine.connect() as connection:
            cached = connection.execute(sa.select(acquisition_census_legal_page_cache).where(
                acquisition_census_legal_page_cache.c.domain_hash == key,
            )).mappings().one_or_none()
        if cached and cached["expires_at"].replace(tzinfo=dt.UTC) > at:
            return dict(cached["evidence"])
        result: dict = {"siren": None, "source_url": None, "observed_at": at.isoformat(),
                        "version": LEGAL_PAGE_VERSION, "reason": "NO_VALID_LEGAL_IDENTIFIER",
                        "pages_fetched": 0}
        if not self._public(name):
            result["reason"] = "DOMAIN_NOT_PUBLICLY_RESOLVABLE"
        else:
            root = f"https://{name}"
            robot = RobotFileParser()
            try:
                response = self._get(root + "/robots.txt")
                result["pages_fetched"] += 1
                if response is None:
                    result["reason"] = "ROBOTS_UNREACHABLE"
                elif response.status_code in {404, 410}:
                    # RFC 9309 §2.3.1.3: an unavailable robots file permits access.
                    # Other 4xx, redirects and 5xx remain closed here.
                    permitted = lambda _url: True
                elif response.status_code == 200:
                    robot.parse(response.text.splitlines())
                    permitted = lambda url: robot.can_fetch("Kivou-MiloMail-Census", url)
                else:
                    result["reason"] = "ROBOTS_UNREACHABLE_OR_RESTRICTED"
                if response is not None and response.status_code in {200, 404, 410} and permitted(root + "/"):
                    home = self._get(root + "/")
                    result["pages_fetched"] += 1
                    if home is not None and home.status_code == 200 and "text/html" in home.headers.get("content-type", ""):
                        page = _Page()
                        page.feed(home.text)
                        home_identifiers = extract_siren(" ".join(page.text))
                        if len(home_identifiers) == 1:
                            result.update(siren=home_identifiers[0], source_url=root + "/",
                                          reason="SINGLE_VALID_IDENTIFIER_ON_HOME")
                        elif len(home_identifiers) > 1:
                            result["reason"] = "MULTIPLE_LEGAL_IDENTIFIERS"
                        urls = [urljoin(root + "/", href) for href in page.links]
                        urls.extend(root + suffix for suffix in (
                            "/mentions-legales", "/mentions_legales", "/legal-notice",
                            "/imprint", "/legal",
                        ))
                        seen: set[str] = set()
                        for url in urls if result["siren"] is None else ():
                            parsed = urlsplit(url)
                            if (url in seen or parsed.scheme != "https" or
                                    parsed.hostname != name or parsed.port not in (None, 443) or
                                    not _LEGAL_PATH.search(parsed.path) or not permitted(url)):
                                continue
                            seen.add(url)
                            if result["pages_fetched"] >= 4:
                                break
                            legal = self._get(url)
                            result["pages_fetched"] += 1
                            if legal is None or legal.status_code != 200 or "text/html" not in legal.headers.get("content-type", ""):
                                continue
                            parsed_legal = _Page()
                            parsed_legal.feed(legal.text)
                            identifiers = extract_siren(" ".join(parsed_legal.text))
                            if len(identifiers) == 1:
                                result.update(siren=identifiers[0], source_url=url,
                                              reason="SINGLE_VALID_IDENTIFIER")
                                break
                            if len(identifiers) > 1:
                                result["reason"] = "MULTIPLE_LEGAL_IDENTIFIERS"
                                break
            except (httpx.HTTPError, UnicodeError, ValueError):
                result["reason"] = "LEGAL_PAGE_UNAVAILABLE"
        with self.engine.begin() as connection:
            connection.execute(sa.delete(acquisition_census_legal_page_cache).where(
                acquisition_census_legal_page_cache.c.domain_hash == key,
                acquisition_census_legal_page_cache.c.expires_at <= at,
            ))
            from signals.persistence.conflicts import insert_if_absent
            insert_if_absent(connection, acquisition_census_legal_page_cache, {
                "domain_hash": key, "evidence": result, "observed_at": at,
                "expires_at": at + self.ttl,
            }, index_elements=["domain_hash"])
        return result

    def _get(self, url: str) -> httpx.Response | None:
        self.requests_made += 1
        with self.client.stream("GET", url, headers={"User-Agent": "Kivou-MiloMail-Census/1.0",
                                                    "Accept": "text/html,text/plain"},
                                timeout=self.timeout, follow_redirects=False) as response:
            if response.status_code != 200:
                return httpx.Response(response.status_code, headers=response.headers)
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > _MAX_BYTES:
                    return None
                data.extend(chunk)
            return httpx.Response(200, headers=response.headers, content=bytes(data))
