"""Emit one signed QA link using runtime keys. Never create or send a campaign."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from urllib.parse import urlsplit

import sqlalchemy as sa

from signals.accounts.icp_input import offer_for_need
from signals.conversion import qa_token
from signals.conversion.recipient_records import bind_recipient, normalize_recipient
from signals.conversion.token import AttributionTokenKeyring
from signals.domain.prospect import require_prospect_eligible
from signals.persistence.schema import contract_award, opportunity_representation
from signals.supplier_discovery.seed import resolve_public_acquisition_context_in_transaction


def mint_url(
    *, engine, keyring: AttributionTokenKeyring, origin: str,
    opportunity: str, wedge: str, country: str, sector: str, need: str,
    ttl: str, now: dt.datetime, recipient_email: str,
) -> str:
    recipient_email = normalize_recipient(recipient_email)
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("A public HTTPS origin is required")
    duration = re.fullmatch(r"([1-9][0-9]*)([hd])", ttl)
    if duration is None or offer_for_need(need) is None:
        raise ValueError("Invalid QA lifetime or need")
    hours = int(duration[1]) * (24 if duration[2] == "d" else 1)
    if hours > 168:
        raise ValueError("QA lifetime exceeds seven days")
    payload = qa_token.QaTokenPayload(
        opportunity_key=opportunity, wedge=wedge, country=country, sector=sector,
        need=need, issued_at=now, expires_at=now + dt.timedelta(hours=hours),
    )
    with engine.begin() as connection:
        exists = connection.scalar(sa.select(sa.exists().where(
            opportunity_representation.c.opportunity_key == opportunity,
            opportunity_representation.c.award_key == contract_award.c.award_key,
            contract_award.c.place_country == country,
        )))
        if exists:
            public = resolve_public_acquisition_context_in_transaction(connection, opportunity)
            place = public.award.place_of_performance
            if place is None or place.country != country:
                raise ValueError("Opportunity unavailable in the requested country")
            require_prospect_eligible(public.award, public.event, as_of=now.date())
        if not exists:
            raise ValueError("Opportunity unavailable in the requested country")
        raw = qa_token.issue(payload, keyring=keyring)
        bind_recipient(
            connection, nonce=payload.nonce, recipient_email=recipient_email,
            expires_at=payload.expires_at, created_at=now,
        )
    print(json.dumps({
        "event": "qa_token_minted", "qa": True,
        "fingerprint": qa_token.fingerprint(raw), "opportunity_key": opportunity,
        "expires_at": payload.expires_at.isoformat(),
    }, sort_keys=True), file=sys.stderr)
    return f"{origin.rstrip('/')}/a/{raw}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("opportunity", "wedge", "country", "sector", "need"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--ttl", default="7d")
    parser.add_argument("--recipient-email", required=True)
    args = parser.parse_args(argv)
    try:
        keyring = qa_token.keyring_from_environment()
    except ValueError:
        print("KIVOU_ATTRIBUTION_HMAC_KEY and its valid version must be loaded", file=sys.stderr)
        return 2
    from signals.api.config import ApiConfig
    from signals.persistence import create_database_engine

    try:
        config = ApiConfig.from_environment()
        if not config.public_site_url:
            raise ValueError("Public origin is not configured")
        engine = create_database_engine()
        try:
            url = mint_url(engine=engine, keyring=keyring, origin=config.public_site_url,
                           now=dt.datetime.now(dt.UTC), **vars(args))
        finally:
            engine.dispose()
    except (ValueError, RuntimeError, sa.exc.SQLAlchemyError):
        print("QA mint refused: check runtime configuration, recipient, opportunity, country, need and TTL",
              file=sys.stderr)
        return 2
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
