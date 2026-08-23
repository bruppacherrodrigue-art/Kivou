"""Authenticated SaaS company profiles, scoped through current unlocked signals."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request

from signals.accounts import service as accounts
from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
from signals.billing import service as billing
from signals.billing.access import feed_access
from signals.companies.contracts import CompanyProfile
from signals.companies.service import company_profile_for_account

router = APIRouter()

_COMPANY_KEY = re.compile(r"^cmp_[A-Za-z0-9_-]{12,60}$")


@router.get("/companies/{company_key}", response_model=CompanyProfile)
def get_company(company_key: str, request: Request) -> CompanyProfile:
    """Return a company only while this account retains one unlocked current signal."""
    now = request_now(request)
    as_of = now.date()
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        if _COMPANY_KEY.fullmatch(company_key) is None:
            raise api_error(404, "company_not_found", "entreprise introuvable")
        user = accounts.current_user(connection, user_id=session.user_id)
        lang = user.locale if user.locale in {"fr", "en"} else "fr"
        access = feed_access(connection, account_id=session.account_id, as_of=as_of)
        accounts.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=access.entitlements.max_territories_per_icp,
            now=now,
        )
        allowed = frozenset(
            billing.feedable_target_icps(
                connection,
                account_id=session.account_id,
                limit=access.entitlements.max_active_icps,
            )
        )
        profile = company_profile_for_account(
            connection,
            company_key=company_key,
            account_id=session.account_id,
            as_of=as_of,
            allowed_target_icp_ids=allowed,
            access=access,
            lang=lang,
        )
    if profile is None:
        raise api_error(404, "company_not_found", "entreprise introuvable")
    return profile

