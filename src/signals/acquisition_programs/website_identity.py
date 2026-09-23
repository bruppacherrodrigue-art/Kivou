"""Bounded public-site identity proof, independent of an official SIRENE match."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.activity_evidence import WebsiteIdentityProof
from signals.acquisition_programs.legal_pages import LEGAL_PAGE_VERSION, LegalPageResolver
from signals.acquisition_programs.mail_provider import normalize_domain
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b1_entry,
    acquisition_census_candidate,
    acquisition_census_company_match,
)

_GENERIC = frozenset({"agence", "cabinet", "conseil", "consulting", "recrutement",
                      "digital", "creative", "services", "france", "groupe"})
_TTL = dt.timedelta(days=7)


def _tokens(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return tuple(re.findall(r"[a-z0-9]+", plain))


def proof_from_legal_page(company_name: str, domain: str,
                          legal: Mapping[str, object]) -> WebsiteIdentityProof | None:
    """Require the whole Apollo company name in the site's own HTML title."""
    title, url, observed = (legal.get("home_title"), legal.get("home_source_url"),
                            legal.get("observed_at"))
    if not all(isinstance(value, str) for value in (title, url, observed)):
        return None
    assert isinstance(title, str) and isinstance(url, str) and isinstance(observed, str)
    name = _tokens(company_name)
    site = _tokens(title)
    if (not name or not any(len(token) >= 4 and token not in _GENERIC
                            for token in name) or len(site) < len(name)):
        return None
    if not any(site[index:index + len(name)] == name
               for index in range(len(site) - len(name) + 1)):
        return None
    normalized_domain = normalize_domain(domain)
    if url != f"https://{normalized_domain}/":
        return None
    try:
        at = dt.datetime.fromisoformat(observed)
        fingerprint = hashlib.sha256(
            f"{LEGAL_PAGE_VERSION}\0{normalized_domain}\0{title}\0{observed}".encode()
        ).hexdigest()
        return WebsiteIdentityProof(
            source_url=url, evidence_id=f"website:{fingerprint}",
            observed_at=at, expires_at=at + _TTL,
            company_domain=normalized_domain, accessible=True,
            identity_matches=True,
        )
    except ValueError:
        return None


def load_website_proofs(engine: Engine, census_id: str, *,
                        at: dt.datetime) -> dict[str, WebsiteIdentityProof]:
    with engine.connect() as connection:
        rows = connection.execute(sa.select(
            acquisition_census_candidate.c.candidate_id,
            acquisition_census_candidate.c.primary_domain,
            acquisition_census_company_match.c.match_evidence,
        ).join(acquisition_census_company_match, sa.and_(
            acquisition_census_company_match.c.census_id ==
            acquisition_census_candidate.c.census_id,
            acquisition_census_company_match.c.provider_organization_id ==
            acquisition_census_candidate.c.provider_organization_id,
        )).where(acquisition_census_candidate.c.census_id == census_id)).mappings().all()
    proofs: dict[str, WebsiteIdentityProof] = {}
    for row in rows:
        raw = row["match_evidence"].get("website_identity")
        if not isinstance(raw, dict):
            continue
        try:
            proof = WebsiteIdentityProof.model_validate(raw)
            host = urlsplit(proof.source_url).hostname
            if (proof.company_domain == row["primary_domain"] and
                    host == row["primary_domain"] and proof.observed_at <= at < proof.expires_at):
                proofs[row["candidate_id"]] = proof
        except ValueError:
            continue
    return proofs


def refresh_website_identity(engine: Engine, *, census_id: str,
                             resolver: LegalPageResolver, max_companies: int,
                             at: dt.datetime) -> dict[str, int]:
    """Refresh only verified-email companies, without Apollo or official API calls."""
    if not 1 <= max_companies <= 500:
        raise ValueError("website refresh must be bounded to 1..500 companies")
    with engine.connect() as connection:
        candidates: dict[str, dict] = {}
        for table in (acquisition_census_b0_entry, acquisition_census_b1_entry):
            rows = connection.execute(sa.select(
                acquisition_census_candidate.c.candidate_id,
                acquisition_census_candidate.c.provider_organization_id,
                acquisition_census_candidate.c.primary_domain,
                acquisition_census_candidate.c.snapshot,
                table.c.result,
            ).join(acquisition_census_candidate,
                   acquisition_census_candidate.c.candidate_id == table.c.candidate_id).where(
                acquisition_census_candidate.c.census_id == census_id,
                table.c.status == "COMPLETE",
            )).mappings()
            for item in rows:
                result = item["result"]
                if isinstance(result, dict) and result.get("verified_email"):
                    candidates[item["provider_organization_id"]] = dict(item)
    checked = confirmed = unknown = 0
    for provider_id, row in sorted(candidates.items()):
        if checked >= max_companies:
            break
        with engine.connect() as connection:
            previous = connection.scalar(sa.select(
                acquisition_census_company_match.c.match_evidence,
            ).where(
                acquisition_census_company_match.c.census_id == census_id,
                acquisition_census_company_match.c.provider_organization_id == provider_id,
            ))
        if isinstance(previous, dict):
            checked_at = previous.get("website_identity_checked_at")
            if isinstance(checked_at, str):
                try:
                    checked_time = dt.datetime.fromisoformat(checked_at)
                    if checked_time <= at < checked_time + _TTL:
                        continue
                except ValueError:
                    pass
        snapshot = row["snapshot"]
        name = snapshot.get("display_name") if isinstance(snapshot, dict) else None
        domain = row["primary_domain"]
        if not isinstance(name, str) or not isinstance(domain, str):
            continue
        legal = resolver.resolve(domain, at=at, run_id=census_id,
                                 company_id=row["candidate_id"])
        proof = proof_from_legal_page(name, domain, legal)
        evidence = dict(previous or {"legal_status": "UNKNOWN",
                                     "match_confidence": "NO_MATCH"})
        evidence["website_identity_checked_at"] = at.isoformat()
        evidence["website_identity"] = proof.model_dump(mode="json") if proof else None
        with engine.begin() as connection:
            values = {"census_id": census_id,
                      "provider_organization_id": provider_id,
                      "match_evidence": evidence, "observed_at": at}
            insert_if_absent(connection, acquisition_census_company_match, values,
                             index_elements=["census_id", "provider_organization_id"])
            if previous is not None:
                connection.execute(sa.update(acquisition_census_company_match).where(
                    acquisition_census_company_match.c.census_id == census_id,
                    acquisition_census_company_match.c.provider_organization_id == provider_id,
                ).values(match_evidence=evidence))
        checked += 1
        confirmed += proof is not None
        unknown += proof is None
    return {"checked": checked, "confirmed": confirmed, "unknown": unknown,
            "apollo_calls": 0, "instantly_mutations": 0, "emails_sent": 0}
