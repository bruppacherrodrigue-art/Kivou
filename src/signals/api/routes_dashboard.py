"""PR1 §5 — `GET /dashboard` : le résumé du jour et la dernière visite.

`previous_seen` est lu AVANT `build_dashboard`, et `account_visit` n'est écrit
qu'APRÈS — dans la MÊME transaction. Un compte qui n'est jamais revenu voit
donc encore `last_seen_at: null` sur cet appel ; c'est le suivant qui verra la
visite d'aujourd'hui.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request

from signals.accounts import service as accounts
from signals.api.dependencies import current_session, request_now
from signals.billing import catalogue, discovery
from signals.billing import service as billing
from signals.billing.access import feed_access
from signals.dashboard.service import build_dashboard
from signals.domain.cpv_labels import cpv_label
from signals.domain.subdivisions import subdivision_label
from signals.engagement.schema import product_event

router = APIRouter()

_PLAN_NAMES = {
    "discovery": "Découverte",
    "essential": "Essential",
    "pro": "Pro",
    "scale": "Scale",
}


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
        profiles = accounts.list_target_icps(connection, account_id=session.account_id)
        active_profile = next((profile for profile in profiles if profile.status == "active"), None)
        billing_state = billing.billing_state(connection, account_id=session.account_id)
        grants = discovery.grants(connection, account_id=session.account_id)
        entitlements = catalogue.entitlements_for(billing_state.plan_code)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        paid_opened = connection.scalar(
            sa.select(sa.func.count(sa.distinct(product_event.c.signal_key))).where(
                product_event.c.account_id == session.account_id,
                product_event.c.event_type == "signal_detail_viewed",
                product_event.c.occurred_at >= month_start,
            )
        ) or 0
        result["profile"] = (
            {
                "name": active_profile.label,
                "sector_label": (
                    cpv_label(active_profile.customer_input.sector_cpv_prefixes[0].ljust(8, "0"), lang=lang)
                    if active_profile.customer_input.sector_cpv_prefixes
                    else active_profile.customer_input.offer_summary or "—"
                ),
                "zone_labels": [
                    subdivision_label(code) or code
                    for code in active_profile.customer_input.territory_subdivisions
                ] or list(active_profile.customer_input.territories),
            }
            if active_profile is not None
            else {"name": "—", "sector_label": "—", "zone_labels": []}
        )
        result["plan"] = {
            "name": _PLAN_NAMES.get(billing_state.plan_code, "—"),
            "opened": len(grants) if billing_state.plan_code == "discovery" else paid_opened,
            "quota": entitlements.granted_signals or None,
            "period_end": (
                billing_state.current_period_end.isoformat()
                if billing_state.current_period_end is not None
                else None
            ),
        }
        if result["top3"]:
            accounts.mark_landing_step(
                connection,
                account_id=session.account_id,
                step="dashboard_ready",
                now=now,
            )
        accounts.touch_last_seen_at(connection, account_id=session.account_id, now=now)
    return result
