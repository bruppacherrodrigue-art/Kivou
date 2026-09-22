"""Bounded, deterministic identification from a company's public legal notice."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import re
import socket
import ssl
import uuid
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.http_accounting import (
    AttemptAccountingError,
    LegalHttpAttempt,
    LegalHttpAttemptSink,
    Outcome,
    RequestType,
)
from signals.acquisition_programs.mail_provider import normalize_domain
from signals.persistence.schema import acquisition_census_legal_page_cache

LEGAL_PAGE_VERSION = "milomail-legal-page-v4"
_IDENTIFIER = re.compile(
    r"(?i)\b(?:siren|siret|tva(?:\s+intracommunautaire)?)\s*[:°nº.]*\s*"
    r"(?P<id>(?:FR\s*[0-9]{2}\s*)?[0-9](?:[ .-]?[0-9]){8,13})\b"
)
_LEGAL_PATH = re.compile(r"(?i)(mentions[-_ ]?legales|legal[-_ ]?notice|/legal/?|imprint)")
_OPAQUE_CONTEXT = re.compile(r"[A-Za-z0-9:._-]{1,128}\Z")
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
        self.title: list[str] = []
        self._in_title = False
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self._ignored += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if isinstance(href, str) and len(href) <= 512:
                self.links.append(href)
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._ignored:
            self._ignored -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.text.append(data)
            if self._in_title and sum(map(len, self.title)) < 256:
                self.title.append(data[:256])


class LegalPageResolver:
    """Fetch robots, home and at most two internal legal pages; cache evidence only."""

    def __init__(self, engine: Engine, *, client: httpx.Client | None = None,
                 timeout: float = 5.0, cache_ttl_days: int = 7,
                 attempt_sink: LegalHttpAttemptSink | None = None) -> None:
        if not 0 < timeout <= 10 or not 1 <= cache_ttl_days <= 30:
            raise ValueError("legal-page bounds are invalid")
        self.engine = engine
        self.client = client or httpx.Client(follow_redirects=False, timeout=timeout)
        self.timeout = timeout
        self.ttl = dt.timedelta(days=cache_ttl_days)
        self.requests_made = 0
        self.attempt_sink = attempt_sink

    def _emit(self, *, domain: str, run_id: str | None, company_id: str | None,
              request_type: RequestType, outcome: Outcome,
              attempt_id: str | None = None, http_status: int | None = None) -> str:
        identifier = attempt_id or uuid.uuid4().hex
        if self.attempt_sink is not None:
            try:
                self.attempt_sink(LegalHttpAttempt(
                    attempt_id=identifier, run_id=run_id, company_id=company_id,
                    domain=domain, request_type=request_type,
                    occurred_at=dt.datetime.now(dt.UTC), outcome=outcome,
                    http_status=http_status,
                ))
            except Exception:  # noqa: BLE001 — arbitrary adapter failure must fail closed
                # Never include sink error text: it may contain a DB URL or payload.
                raise AttemptAccountingError("legal-page accounting unavailable") from None
        return identifier

    @staticmethod
    def _public(domain: str) -> bool:
        try:
            addresses = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
            return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global
                                           for item in addresses)
        except ValueError:
            return False

    def resolve(self, domain: str, *, at: dt.datetime,
                run_id: str | None = None, company_id: str | None = None) -> dict:
        if any(value is not None and not _OPAQUE_CONTEXT.fullmatch(value)
               for value in (run_id, company_id)):
            raise ValueError("legal-page accounting requires opaque run and company identifiers")
        name = normalize_domain(domain)
        key = hashlib.sha256(f"{LEGAL_PAGE_VERSION}\0{name}".encode()).hexdigest()
        with self.engine.connect() as connection:
            cached = connection.execute(sa.select(acquisition_census_legal_page_cache).where(
                acquisition_census_legal_page_cache.c.domain_hash == key,
            )).mappings().one_or_none()
        if cached and cached["expires_at"].replace(tzinfo=dt.UTC) > at:
            self._emit(domain=name, run_id=run_id, company_id=company_id,
                       request_type="CACHE", outcome="CACHE_HIT")
            return dict(cached["evidence"])
        self._emit(domain=name, run_id=run_id, company_id=company_id,
                   request_type="CACHE", outcome="CACHE_MISS")
        result: dict = {"siren": None, "source_url": None,
                        "home_title": None, "home_source_url": None,
                        "observed_at": at.isoformat(),
                        "version": LEGAL_PAGE_VERSION, "reason": "NO_VALID_LEGAL_IDENTIFIER",
                        "pages_fetched": 0}
        dns_attempt_id = self._emit(domain=name, run_id=run_id, company_id=company_id,
                                    request_type="DNS", outcome="STARTED")
        try:
            publicly_resolvable = self._public(name)
            dns_outcome: Outcome = "DNS_PUBLIC" if publicly_resolvable else "DNS_REJECTED"
        except OSError:
            publicly_resolvable = False
            dns_outcome = "DNS_ERROR"
        self._emit(domain=name, run_id=run_id, company_id=company_id,
                   request_type="DNS", outcome=dns_outcome,
                   attempt_id=dns_attempt_id)
        if not publicly_resolvable:
            result["reason"] = "DOMAIN_NOT_PUBLICLY_RESOLVABLE"
        else:
            root = f"https://{name}"
            robot = RobotFileParser()
            try:
                response = self._get(root + "/robots.txt", domain=name, run_id=run_id,
                                     company_id=company_id, request_type="ROBOTS")
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
                robots_ready = response is not None and response.status_code in {200, 404, 410}
                home_allowed = robots_ready and permitted(root + "/")
                self._emit(domain=name, run_id=run_id, company_id=company_id,
                           request_type="ROBOTS_POLICY", outcome=(
                               "ROBOTS_ALLOWED" if home_allowed else
                               "ROBOTS_BLOCKED" if robots_ready else "ROBOTS_UNAVAILABLE"
                           ))
                if home_allowed:
                    home = self._get(root + "/", domain=name, run_id=run_id,
                                     company_id=company_id, request_type="HOMEPAGE")
                    result["pages_fetched"] += 1
                    if home is not None and home.status_code == 200 and "text/html" in home.headers.get("content-type", ""):
                        page = _Page()
                        page.feed(home.text)
                        title = " ".join(" ".join(page.title).split())[:256]
                        if title:
                            result.update(home_title=title, home_source_url=root + "/")
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
                                    not _LEGAL_PATH.search(parsed.path)):
                                continue
                            if not permitted(url):
                                self._emit(domain=name, run_id=run_id, company_id=company_id,
                                           request_type="ROBOTS_POLICY", outcome="ROBOTS_BLOCKED")
                                continue
                            seen.add(url)
                            if result["pages_fetched"] >= 4:
                                break
                            legal = self._get(url, domain=name, run_id=run_id,
                                              company_id=company_id, request_type="LEGAL_PAGE")
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

    def _get(self, url: str, *, domain: str, run_id: str | None,
             company_id: str | None, request_type: RequestType) -> httpx.Response | None:
        attempt_id = self._emit(domain=domain, run_id=run_id, company_id=company_id,
                                request_type=request_type, outcome="STARTED")
        self.requests_made += 1
        status: int | None = None
        headers: dict[str, str] = {}
        body: bytes | None = None
        try:
            with self.client.stream("GET", url, headers={
                "User-Agent": "Kivou-MiloMail-Census/1.0",
                "Accept": "text/html,text/plain",
            }, timeout=self.timeout, follow_redirects=False) as response:
                status = response.status_code
                headers = dict(response.headers)
                if status != 200:
                    outcome: Outcome = "REDIRECT_BLOCKED" if 300 <= status < 400 else "HTTP_STATUS"
                elif request_type in {"HOMEPAGE", "LEGAL_PAGE"} and "text/html" not in (
                    response.headers.get("content-type", "").casefold()
                ):
                    outcome = "CONTENT_TYPE_REJECTED"
                else:
                    data: bytearray | None = bytearray()
                    outcome = "HTTP_OK"
                    for chunk in response.iter_bytes():
                        assert data is not None
                        if len(data) + len(chunk) > _MAX_BYTES:
                            outcome = "SIZE_LIMIT"
                            data = None
                            break
                        data.extend(chunk)
                    if data is not None:
                        body = bytes(data)
        except httpx.TimeoutException:
            outcome = "TIMEOUT"
        except ssl.SSLError:
            outcome = "TLS_ERROR"
        except httpx.ConnectError as error:
            cause = error.__cause__
            while cause is not None and not isinstance(cause, ssl.SSLError):
                cause = cause.__cause__
            outcome = "TLS_ERROR" if cause is not None else "CONNECT_ERROR"
        except httpx.HTTPError:
            outcome = "NETWORK_ERROR"
        self._emit(domain=domain, run_id=run_id, company_id=company_id,
                   request_type=request_type, attempt_id=attempt_id, outcome=outcome,
                   http_status=status)
        if outcome in {"TIMEOUT", "TLS_ERROR", "CONNECT_ERROR", "NETWORK_ERROR", "SIZE_LIMIT"}:
            return None
        assert status is not None
        return httpx.Response(status, headers=headers, content=body or b"")
