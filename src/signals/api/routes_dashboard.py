"""PR1 §5 — `GET /dashboard` : le résumé du jour et la dernière visite.

`previous_seen` est lu AVANT `build_dashboard`, et `account_visit` n'est écrit
qu'APRÈS — dans la MÊME transaction. Un compte qui n'est jamais revenu voit
donc encore `last_seen_at: null` sur cet appel ; c'est le suivant qui verra la
visite d'aujourd'hui.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from signals.accounts import service as accounts
from signals.api.dependencies import current_session, request_now
from signals.billing import service as billing
from signals.billing.access import feed_access
from signals.dashboard.service import build_dashboard

router = APIRouter()


@router.get("/dashboard")
def get_dashboard(request: Request) -> dict[str, Any]:
    now = request_now(request)
    as_of = now.date()
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
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
        previous_seen = accounts.read_last_seen_at(connection, account_id=session.account_id)
        result = build_dashboard(
            connection,
            account_id=session.account_id,
            now=now,
            as_of=as_of,
            allowed_target_icp_ids=allowed,
            access=access,
            lang=lang,
            previous_seen=previous_seen,
        )
        accounts.touch_last_seen_at(connection, account_id=session.account_id, now=now)
    return result
